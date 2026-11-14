"""Flipkart Affiliate API (official, contract-governed).

Docs: https://affiliate.flipkart.com/api-docs/af_prod_ref.html
  GET https://affiliate-api.flipkart.net/affiliate/1.0/search.json?query=...&resultCount=1..10
  Headers: Fk-Affiliate-Id, Fk-Affiliate-Token
  Response: {"productInfoList": [{"productBaseInfoV1": {...}, "productShippingInfoV1": {...}}]}
Flipkart's FAQ allows 20 calls/second per affiliate; we stay far below that.
"""
from django.conf import settings

from ..base import ScrapedListing, SourceAdapter
from ..exceptions import NotConfigured
from ..http import HostPolicy

SEARCH_URL = 'https://affiliate-api.flipkart.net/affiliate/1.0/search.json'
MAX_RESULTS = 10                     # documented maximum for resultCount
IMAGE_SIZES = ('400x400', '800x800', '200x200', 'unknown')


def _amount(price):
    if isinstance(price, dict) and price.get('amount') is not None:
        return str(price['amount'])
    return None


def _image(image_urls):
    if not isinstance(image_urls, dict) or not image_urls:
        return ''
    for size in IMAGE_SIZES:
        if image_urls.get(size):
            return image_urls[size]
    return next(iter(image_urls.values()), '') or ''


def parse_search_response(data):
    """Turn a search.json payload into ScrapedListings, skipping malformed items."""
    listings = []
    for item in (data or {}).get('productInfoList') or []:
        base = (item or {}).get('productBaseInfoV1') or {}
        title, url = base.get('title'), base.get('productUrl')
        if not title or not url:
            continue
        price = _amount(base.get('flipkartSpecialPrice')) or _amount(base.get('flipkartSellingPrice'))
        listings.append(ScrapedListing(
            name=title,
            url=url,
            price=price,
            mrp=_amount(base.get('maximumRetailPrice')),
            in_stock=bool(base.get('inStock', True)),
            image_url=_image(base.get('imageUrls')),
            brand=base.get('productBrand') or '',
            source_id=base.get('productId') or '',
            extra={'discount_percentage': base.get('discountPercentage'),
                   'seller': ((item.get('productShippingInfoV1') or {}).get('sellerName') or '')},
        ))
    return listings


class FlipkartAffiliateAdapter(SourceAdapter):
    name = 'flipkart'
    seller = 'Flipkart'
    kind = 'api'
    # Official API: access is governed by the affiliate agreement, so robots.txt (written
    # for crawlers of the public site) doesn't apply. 1 req/s is ~5% of the allowed rate.
    policy = HostPolicy(min_interval=1.0, daily_quota=5000, respect_robots=False, cache_ttl=30 * 60)

    def check_configured(self):
        if not (settings.FLIPKART_AFFILIATE_ID and settings.FLIPKART_AFFILIATE_TOKEN):
            raise NotConfigured(
                'Flipkart Affiliate API keys are missing. Sign up at https://affiliate.flipkart.com, '
                'create an API token, and set FLIPKART_AFFILIATE_ID and FLIPKART_AFFILIATE_TOKEN in .env.')

    def search(self, query, limit=MAX_RESULTS):
        self.check_configured()
        response = self.client.get(
            SEARCH_URL,
            params={'query': query, 'resultCount': max(1, min(int(limit), MAX_RESULTS))},
            headers={'Fk-Affiliate-Id': settings.FLIPKART_AFFILIATE_ID,
                     'Fk-Affiliate-Token': settings.FLIPKART_AFFILIATE_TOKEN},
        )
        return parse_search_response(response.json())
