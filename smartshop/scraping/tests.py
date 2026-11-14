from decimal import Decimal
from io import StringIO

import httpx
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from products.models import Offer, PricePoint, Product

from .adapters.flipkart import FlipkartAffiliateAdapter, SEARCH_URL, parse_search_response
from .exceptions import (Blocked, FetchError, NotConfigured, QuotaExceeded, RateLimited,
                         RobotsDisallowed)
from .http import HostPolicy, PoliteClient
from .models import ScrapeRun
from .pipeline import run_query


class FakeClock:
    """now()/sleep() pair: sleeping just advances time and is recorded."""
    def __init__(self):
        self.t = 1_800_000_000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 2))
        self.t += seconds


def make_client(handler, clock=None, **policy):
    clock = clock or FakeClock()
    defaults = dict(min_interval=0, respect_robots=False, cache_ttl=0)
    defaults.update(policy)
    calls = []

    def recording_handler(request):
        calls.append(request)
        return handler(request)

    client = PoliteClient(policy=HostPolicy(**defaults), user_agent='TestBot/1.0',
                          transport=httpx.MockTransport(recording_handler),
                          sleep=clock.sleep, now=clock.now, rand=lambda: 0.0)
    return client, calls, clock


def responses(*items):
    """Handler returning the given responses in order (last one repeats)."""
    items = list(items)

    def handler(request):
        item = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(item, Exception):
            raise item
        return item
    return handler


class ScrapingTestCase(TestCase):
    def setUp(self):
        cache.clear()   # rate-limit, quota, block and response state live in the cache


class RateLimitTests(ScrapingTestCase):
    def test_min_interval_between_requests_to_same_host(self):
        client, calls, clock = make_client(responses(httpx.Response(200, text='ok')), min_interval=3)
        client.get('https://a.example.com/1')
        client.get('https://a.example.com/2')
        self.assertEqual(clock.sleeps, [3.0])
        client.get('https://b.example.com/1')         # other host: no wait
        self.assertEqual(clock.sleeps, [3.0])

    def test_daily_quota(self):
        client, calls, _ = make_client(responses(httpx.Response(200, text='ok')), daily_quota=2)
        client.get('https://a.example.com/1')
        client.get('https://a.example.com/2')
        with self.assertRaises(QuotaExceeded):
            client.get('https://a.example.com/3')
        self.assertEqual(len(calls), 2)


class RetryTests(ScrapingTestCase):
    def test_retries_server_error_with_backoff(self):
        client, calls, clock = make_client(responses(
            httpx.Response(503), httpx.Response(502), httpx.Response(200, text='finally')))
        self.assertEqual(client.get('https://a.example.com/').text, 'finally')
        self.assertEqual(clock.sleeps, [2.0, 4.0])            # 2s, 4s (jitter fixed at 0)
        self.assertEqual(len(calls), 3)

    def test_honours_retry_after(self):
        client, _, clock = make_client(responses(
            httpx.Response(429, headers={'Retry-After': '5'}), httpx.Response(200, text='ok')))
        client.get('https://a.example.com/')
        self.assertEqual(clock.sleeps, [5.0])

    def test_refuses_to_wait_too_long(self):
        client, calls, _ = make_client(responses(httpx.Response(429, headers={'Retry-After': '3600'})))
        with self.assertRaises(RateLimited):
            client.get('https://a.example.com/')
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_max_retries(self):
        client, calls, _ = make_client(responses(httpx.Response(500)), max_retries=3)
        with self.assertRaises(FetchError):
            client.get('https://a.example.com/')
        self.assertEqual(len(calls), 4)                       # first try + 3 retries

    def test_client_errors_are_not_retried(self):
        client, calls, _ = make_client(responses(httpx.Response(404)))
        with self.assertRaises(FetchError):
            client.get('https://a.example.com/missing')
        self.assertEqual(len(calls), 1)

    def test_network_errors_are_retried(self):
        client, calls, _ = make_client(responses(
            httpx.ConnectError('boom'), httpx.Response(200, text='ok')))
        self.assertEqual(client.get('https://a.example.com/').text, 'ok')
        self.assertEqual(len(calls), 2)


class BlockingTests(ScrapingTestCase):
    def test_403_pauses_host_and_later_calls_send_nothing(self):
        client, calls, _ = make_client(responses(httpx.Response(403)))
        with self.assertRaises(Blocked):
            client.get('https://a.example.com/1')
        with self.assertRaises(Blocked):
            client.get('https://a.example.com/2')
        self.assertEqual(len(calls), 1)

    def test_captcha_page_counts_as_block(self):
        page = httpx.Response(200, text='<html><title>Are you a robot?</title> solve this captcha</html>',
                              headers={'content-type': 'text/html'})
        client, _, _ = make_client(responses(page))
        with self.assertRaises(Blocked):
            client.get('https://a.example.com/')

    def test_401_means_bad_credentials_without_pausing(self):
        client, calls, _ = make_client(responses(httpx.Response(401), httpx.Response(200, text='ok')))
        with self.assertRaises(NotConfigured):
            client.get('https://api.example.com/')
        self.assertEqual(client.get('https://api.example.com/').text, 'ok')


class RobotsTests(ScrapingTestCase):
    def robots_handler(self, robots_response):
        def handler(request):
            if request.url.path == '/robots.txt':
                return robots_response
            return httpx.Response(200, text='page')
        return handler

    def test_disallowed_path_is_refused(self):
        robots = httpx.Response(200, text='User-agent: *\nDisallow: /private/\n')
        client, calls, _ = make_client(self.robots_handler(robots), respect_robots=True)
        self.assertEqual(client.get('https://a.example.com/public/x').text, 'page')
        with self.assertRaises(RobotsDisallowed):
            client.get('https://a.example.com/private/x')
        self.assertEqual([c.url.path for c in calls], ['/robots.txt', '/public/x'])   # robots fetched once

    def test_missing_robots_allows_everything(self):
        client, _, _ = make_client(self.robots_handler(httpx.Response(404)), respect_robots=True)
        self.assertEqual(client.get('https://a.example.com/anything').text, 'page')

    def test_robots_server_error_is_treated_as_disallow(self):
        client, _, _ = make_client(self.robots_handler(httpx.Response(500)), respect_robots=True)
        with self.assertRaises(RobotsDisallowed):
            client.get('https://a.example.com/anything')

    def test_sends_honest_user_agent(self):
        client, calls, _ = make_client(responses(httpx.Response(200, text='ok')))
        client.get('https://a.example.com/')
        self.assertEqual(calls[0].headers['User-Agent'], 'TestBot/1.0')


class CachingTests(ScrapingTestCase):
    def test_fresh_response_served_from_cache(self):
        client, calls, _ = make_client(responses(httpx.Response(200, text='v1')), cache_ttl=600)
        client.get('https://a.example.com/p', params={'q': 'x'})
        second = client.get('https://a.example.com/p', params={'q': 'x'})
        self.assertTrue(second.from_cache)
        self.assertEqual(len(calls), 1)

    def test_stale_response_revalidated_with_etag(self):
        client, calls, clock = make_client(responses(
            httpx.Response(200, text='v1', headers={'ETag': '"abc"'}),
            httpx.Response(304)), cache_ttl=60)
        client.get('https://a.example.com/p')
        clock.t += 120                                         # cache entry is now stale
        again = client.get('https://a.example.com/p')
        self.assertEqual(calls[1].headers['If-None-Match'], '"abc"')
        self.assertEqual((again.text, again.from_cache), ('v1', True))


FLIPKART_PAYLOAD = {
    'productInfoList': [
        {'productBaseInfoV1': {
            'productId': 'MOBGTAGPTB3VS24W', 'title': 'Apple iPhone 15 (Black, 128 GB)',
            'productUrl': 'https://dl.flipkart.com/dl/apple-iphone-15/p/itm6ac?pid=MOBGTAGPTB3VS24W&affid=abc',
            'maximumRetailPrice': {'amount': 79900, 'currency': 'INR'},
            'flipkartSellingPrice': {'amount': 61999, 'currency': 'INR'},
            'flipkartSpecialPrice': {'amount': 59999, 'currency': 'INR'},
            'imageUrls': {'200x200': 'https://img/200.jpg', '400x400': 'https://img/400.jpg'},
            'productBrand': 'Apple', 'inStock': True, 'discountPercentage': 24.0},
         'productShippingInfoV1': {'sellerName': 'SuperComNet'}},
        {'productBaseInfoV1': {
            'productId': 'MOBX', 'title': 'Apple iPhone 15 (Pink, 256 GB)',
            'productUrl': 'https://dl.flipkart.com/dl/apple-iphone-15-pink/p/itm7?pid=MOBX',
            'flipkartSellingPrice': {'amount': 72999, 'currency': 'INR'},
            'imageUrls': {'unknown': 'https://img/orig.jpg'}, 'inStock': False}},
        {'productBaseInfoV1': {'title': 'No URL, skipped'}},
        {},
    ]
}


class FlipkartAdapterTests(ScrapingTestCase):
    def test_parse_prefers_special_price_and_best_image(self):
        first, second = parse_search_response(FLIPKART_PAYLOAD)
        self.assertEqual((first.name, first.price, first.mrp, first.image_url, first.brand, first.source_id),
                         ('Apple iPhone 15 (Black, 128 GB)', '59999', '79900', 'https://img/400.jpg',
                          'Apple', 'MOBGTAGPTB3VS24W'))
        self.assertEqual((second.price, second.mrp, second.in_stock, second.image_url),
                         ('72999', None, False, 'https://img/orig.jpg'))

    def test_parse_tolerates_empty_or_odd_payloads(self):
        self.assertEqual(parse_search_response({}), [])
        self.assertEqual(parse_search_response(None), [])
        self.assertEqual(parse_search_response({'productInfoList': None}), [])

    @override_settings(FLIPKART_AFFILIATE_ID='', FLIPKART_AFFILIATE_TOKEN='')
    def test_missing_keys_raise_not_configured(self):
        with self.assertRaises(NotConfigured):
            FlipkartAffiliateAdapter(client=make_client(responses(httpx.Response(200)))[0]).search('x')

    @override_settings(FLIPKART_AFFILIATE_ID='aff123', FLIPKART_AFFILIATE_TOKEN='tok456')
    def test_search_sends_auth_headers_and_caps_result_count(self):
        client, calls, _ = make_client(responses(httpx.Response(200, json=FLIPKART_PAYLOAD)))
        listings = FlipkartAffiliateAdapter(client=client).search('iphone 15', limit=50)
        self.assertEqual(len(listings), 2)
        request = calls[0]
        self.assertEqual(str(request.url).split('?')[0], SEARCH_URL)
        self.assertEqual(request.url.params['query'], 'iphone 15')
        self.assertEqual(request.url.params['resultCount'], '10')
        self.assertEqual((request.headers['Fk-Affiliate-Id'], request.headers['Fk-Affiliate-Token']),
                         ('aff123', 'tok456'))


@override_settings(FLIPKART_AFFILIATE_ID='aff123', FLIPKART_AFFILIATE_TOKEN='tok456')
class PipelineTests(ScrapingTestCase):
    def adapter(self, *payloads):
        client, calls, _ = make_client(responses(*[httpx.Response(200, json=p) for p in payloads]))
        return FlipkartAffiliateAdapter(client=client)

    def test_run_ingests_products_offers_and_logs_run(self):
        run, _ = run_query(self.adapter(FLIPKART_PAYLOAD), 'iphone 15', 'Mobile Phones', 'Electronics')
        self.assertEqual((run.status, run.fetched, run.products_created, run.offers_created),
                         ('ok', 2, 2, 2))
        product = Product.objects.get(name='Apple iPhone 15 (Black, 128 GB)')
        self.assertEqual(product.category.parent.name, 'Electronics')
        self.assertEqual(product.price, Decimal('59999'))
        self.assertEqual(product.image_url, 'https://img/400.jpg')
        offer = product.offers.get()
        self.assertEqual((offer.seller, offer.mrp), ('Flipkart', Decimal('79900')))
        self.assertEqual(offer.url, 'https://dl.flipkart.com/dl/apple-iphone-15/p/itm6ac?pid=MOBGTAGPTB3VS24W')

    def test_second_run_records_price_change_only(self):
        cheaper = {'productInfoList': [dict(FLIPKART_PAYLOAD['productInfoList'][0])]}
        cheaper['productInfoList'][0] = {'productBaseInfoV1': {
            **FLIPKART_PAYLOAD['productInfoList'][0]['productBaseInfoV1'],
            'flipkartSpecialPrice': {'amount': 57999, 'currency': 'INR'}}}
        run_query(self.adapter(FLIPKART_PAYLOAD), 'iphone 15', 'Mobile Phones')
        cache.clear()                                  # bypass the response cache for the re-run
        run, _ = run_query(self.adapter(cheaper), 'iphone 15', 'Mobile Phones')
        self.assertEqual((run.products_created, run.offers_created, run.price_changes), (0, 0, 1))
        self.assertEqual(Product.objects.get(name__contains='Black').price, Decimal('57999'))
        self.assertEqual(PricePoint.objects.filter(offer__product__name__contains='Black').count(), 2)

    def test_failed_fetch_is_recorded(self):
        client, _, _ = make_client(responses(httpx.Response(403)))
        with self.assertRaises(Blocked):
            run_query(FlipkartAffiliateAdapter(client=client), 'iphone', 'Mobile Phones')
        run = ScrapeRun.objects.get()
        self.assertEqual(run.status, 'failed')
        self.assertIn('refused', run.error)
        self.assertFalse(Offer.objects.exists())

    def test_dry_run_saves_nothing(self):
        run, listings = run_query(self.adapter(FLIPKART_PAYLOAD), 'iphone 15', dry_run=True)
        self.assertIsNone(run)
        self.assertEqual(len(listings), 2)
        self.assertFalse(Product.objects.exists())
        self.assertFalse(ScrapeRun.objects.exists())


class CommandTests(ScrapingTestCase):
    @override_settings(FLIPKART_AFFILIATE_ID='', FLIPKART_AFFILIATE_TOKEN='')
    def test_command_explains_missing_keys(self):
        with self.assertRaisesMessage(CommandError, 'FLIPKART_AFFILIATE_ID'):
            call_command('scrape', 'flipkart', '-q', 'iphone', stdout=StringIO())
