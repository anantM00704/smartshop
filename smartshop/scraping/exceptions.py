class ScrapeError(Exception):
    """Base class for data-source errors."""


class FetchError(ScrapeError):
    """The request failed after all retries (network error or server error)."""


class RobotsDisallowed(ScrapeError):
    """robots.txt does not allow this URL for our user agent."""


class QuotaExceeded(ScrapeError):
    """Our own daily request budget for this host is used up."""


class RateLimited(ScrapeError):
    """The host asked us to wait longer than we are willing to (Retry-After too long)."""


class Blocked(ScrapeError):
    """The host refused us (401/403/block page). We stop instead of trying to get around it."""


class NotConfigured(ScrapeError):
    """A source needs credentials or settings that are missing."""
