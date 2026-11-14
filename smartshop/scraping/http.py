"""PoliteClient: the only way adapters talk to the outside world.

Guarantees, per host:
  * rate limit   - at least `min_interval` seconds between requests
  * daily quota  - at most `daily_quota` requests per day (our own budget)
  * robots.txt   - honoured when `respect_robots` is on (always on for HTML sources)
  * retries      - 429 / 5xx / network errors retried with exponential backoff + jitter,
                   honouring Retry-After; we give up rather than wait unreasonably long
  * circuit breaker - 403 or a block/CAPTCHA page pauses the host for `block_cooldown`;
                   we never try to get around a block
  * caching      - successful GET responses cached for `cache_ttl`; ETag revalidation

State lives in Django's cache, so pointing CACHES at Redis makes every worker share it.
"""
import email.utils
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from django.conf import settings
from django.core.cache import cache

from .exceptions import Blocked, FetchError, NotConfigured, QuotaExceeded, RateLimited, RobotsDisallowed

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504, 599}
BLOCK_STATUSES = {403}
BLOCK_MARKERS = ('captcha', 'are you a robot', 'access denied', 'unusual traffic')


@dataclass(frozen=True)
class HostPolicy:
    min_interval: float = 3.0          # seconds between requests to the host
    daily_quota: int = 2000            # our own cap per day
    max_retries: int = 3
    backoff_base: float = 2.0          # 2s, 4s, 8s (+ jitter)
    max_wait: float = 60.0             # longest single wait we accept (Retry-After or backoff)
    timeout: float = 15.0
    respect_robots: bool = True
    cache_ttl: int = 30 * 60           # seconds; 0 disables response caching
    block_cooldown: int = 6 * 60 * 60  # pause after being refused


@dataclass
class Response:
    url: str
    status: int
    text: str
    headers: dict
    from_cache: bool = False

    def json(self):
        return json.loads(self.text)


def _key(*parts):
    return 'scrape:' + ':'.join(parts)


def _retry_after_seconds(value, now):
    """Retry-After is either delta-seconds or an HTTP date."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value).timestamp()
            return max(0.0, when - now)
        except (TypeError, ValueError):
            return None


class PoliteClient:
    def __init__(self, policy=None, user_agent=None, transport=None,
                 sleep=time.sleep, now=time.time, rand=random.random):
        self.policy = policy or HostPolicy()
        self.user_agent = user_agent or settings.SCRAPER_USER_AGENT
        self._sleep, self._now, self._rand = sleep, now, rand
        self._http = httpx.Client(
            transport=transport, timeout=self.policy.timeout, follow_redirects=True,
            headers={'User-Agent': self.user_agent, 'Accept-Encoding': 'gzip, deflate'})
        self._robots = {}

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- public -----------------------------------------------------------------
    def get(self, url, params=None, headers=None):
        full_url = f'{url}?{urlencode(params, doseq=True)}' if params else url
        host = urlsplit(full_url).netloc.lower()

        self._check_not_blocked(host)
        if self.policy.respect_robots and not self._robots_allows(full_url):
            raise RobotsDisallowed(f'robots.txt disallows {full_url}')

        cache_key = _key('resp', hashlib.sha256(full_url.encode()).hexdigest())
        cached = cache.get(cache_key) if self.policy.cache_ttl else None
        if cached and cached.get('fresh_until', 0) > self._now():
            return Response(full_url, cached['status'], cached['text'], cached['headers'], from_cache=True)

        request_headers = dict(headers or {})
        if cached and cached['headers'].get('etag'):
            request_headers['If-None-Match'] = cached['headers']['etag']

        response = self._send(host, full_url, request_headers)

        if response.status_code == 304 and cached:
            self._store(cache_key, cached['status'], cached['text'], cached['headers'])
            return Response(full_url, cached['status'], cached['text'], cached['headers'], from_cache=True)

        text = response.text
        if response.status_code == 401:
            # Bad or expired credentials: fail fast, but don't pause the host.
            raise NotConfigured(f'{host} rejected our credentials (HTTP 401). Check the API keys in .env.')
        if response.status_code in BLOCK_STATUSES or self._looks_blocked(response, text):
            self._block(host, f'HTTP {response.status_code}')
            raise Blocked(f'{host} refused the request (HTTP {response.status_code}); paused for '
                          f'{self.policy.block_cooldown // 3600}h')
        if response.status_code >= 400:
            raise FetchError(f'HTTP {response.status_code} for {full_url}')

        resp_headers = {k.lower(): v for k, v in response.headers.items()
                        if k.lower() in ('etag', 'content-type', 'last-modified')}
        if self.policy.cache_ttl:
            self._store(cache_key, response.status_code, text, resp_headers)
        return Response(full_url, response.status_code, text, resp_headers)

    # ---- internals --------------------------------------------------------------
    def _send(self, host, url, headers):
        attempt = 0
        while True:
            self._throttle(host)
            try:
                response = self._http.get(url, headers=headers)
            except httpx.TransportError as exc:          # DNS, connect, read timeouts...
                status, retry_after, error = None, None, exc
            else:
                if response.status_code not in RETRY_STATUSES:
                    return response
                status, error = response.status_code, None
                retry_after = _retry_after_seconds(response.headers.get('Retry-After'), self._now())

            attempt += 1
            if attempt > self.policy.max_retries:
                raise FetchError(f'Giving up on {url} after {attempt} attempts '
                                 f'({status or type(error).__name__})')
            wait = retry_after if retry_after is not None else \
                self.policy.backoff_base * (2 ** (attempt - 1)) * (1 + self._rand())
            if wait > self.policy.max_wait:
                raise RateLimited(f'{host} asked us to wait {wait:.0f}s; not waiting that long')
            logger.info('Retrying %s in %.1fs (attempt %d, %s)', url, wait, attempt, status or error)
            self._sleep(wait)

    def _throttle(self, host):
        """Enforce min_interval between requests and the daily quota."""
        day = time.strftime('%Y%m%d', time.gmtime(self._now()))
        quota_key = _key('quota', host, day)
        used = cache.get(quota_key, 0)
        if used >= self.policy.daily_quota:
            raise QuotaExceeded(f'Daily quota of {self.policy.daily_quota} requests to {host} used up')

        last_key = _key('last', host)
        last = cache.get(last_key)
        if last is not None:
            wait = last + self.policy.min_interval - self._now()
            if wait > 0:
                self._sleep(wait)
        cache.set(last_key, self._now(), timeout=max(60, int(self.policy.min_interval * 10)))
        cache.set(quota_key, used + 1, timeout=2 * 24 * 3600)

    def _robots_allows(self, url):
        parts = urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        parser = self._robots.get(origin)
        if parser is None:
            parser = RobotFileParser()
            try:
                self._throttle(parts.netloc.lower())
                resp = self._http.get(f'{origin}/robots.txt')
                if resp.status_code >= 500:
                    parser.disallow_all = True          # server trouble: be conservative
                elif resp.status_code >= 400:
                    parser.allow_all = True             # no robots.txt: everything allowed
                else:
                    parser.parse(resp.text.splitlines())
            except httpx.TransportError:
                parser.disallow_all = True
            self._robots[origin] = parser
        return parser.can_fetch(self.user_agent, url)

    def _looks_blocked(self, response, text):
        if 'html' not in response.headers.get('content-type', ''):
            return False
        head = text[:5000].lower()
        return any(marker in head for marker in BLOCK_MARKERS)

    def _block(self, host, reason):
        logger.warning('Pausing requests to %s for %ss: %s', host, self.policy.block_cooldown, reason)
        cache.set(_key('blocked', host), reason, timeout=self.policy.block_cooldown)

    def _check_not_blocked(self, host):
        reason = cache.get(_key('blocked', host))
        if reason:
            raise Blocked(f'{host} is paused after an earlier refusal ({reason})')

    def _store(self, cache_key, status, text, headers):
        cache.set(cache_key, {'status': status, 'text': text, 'headers': headers,
                              'fresh_until': self._now() + self.policy.cache_ttl},
                  timeout=self.policy.cache_ttl * 4)   # keep a while longer for ETag revalidation
