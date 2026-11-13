"""Ingestion service: the single entry point for adding or updating listings.

Scrapers, affiliate-API clients and CSV imports all call ``ingest_listing`` so that
offers, price history and the product's denormalised best price stay consistent.
"""
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from django.db import transaction
from django.db.models import Min

from .models import Category, Offer, PricePoint, Product

_AMAZON_ASIN = re.compile(r'/(?:dp|gp/product)/([A-Z0-9]{10})', re.IGNORECASE)


def canonical_url(url: str) -> str:
    """Strip tracking noise so the same listing always maps to the same URL.

    Amazon:   .../Some-Name/dp/B0CHX1W1XY/ref=sr_1_1?keywords=... -> https://www.amazon.in/dp/B0CHX1W1XY
    Flipkart: keep only the `pid` query parameter, which identifies the item.
    Others:   drop query string and fragment.
    """
    url = (url or '').strip()
    if not url:
        return ''
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if 'amazon.' in host:
        match = _AMAZON_ASIN.search(parts.path)
        if match:
            return f"{parts.scheme or 'https'}://{host}/dp/{match.group(1).upper()}"
    if 'flipkart.' in host:
        pid = parse_qs(parts.query).get('pid')
        query = urlencode({'pid': pid[0]}) if pid else ''
        return urlunsplit((parts.scheme or 'https', host, parts.path.rstrip('/'), query, ''))
    return urlunsplit((parts.scheme or 'https', host, parts.path.rstrip('/') or '/', '', ''))


def clean_text(value) -> str:
    """Normalise CSV/scraper cell values: None/NaN/'nan' -> '', collapse whitespace."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ''
    text = ' '.join(str(value).split())
    return '' if text.lower() in ('nan', 'none', 'null') else text


@dataclass
class Listing:
    name: str
    seller: str
    url: str
    category: Optional[Category] = None
    price: Optional[Decimal] = None
    mrp: Optional[Decimal] = None
    in_stock: bool = True
    image_url: str = ''
    rating: Optional[Decimal] = None
    delivery_date: str = ''


def to_decimal(value) -> Optional[Decimal]:
    """Parse '₹1,299.00', 1299, '1299' ... into a Decimal; None when unusable."""
    value = clean_text(value)
    if not value:
        return None
    try:
        result = Decimal(value.replace('₹', '').replace('Rs.', '').replace(',', '').strip())
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


_FIRST_NUMBER = re.compile(r'\d+(?:\.\d+)?')


def parse_rating(value) -> Optional[Decimal]:
    """'4.2 out of 5 stars' / '4.2' / 4.2 -> Decimal('4.2'); only 0-5 accepted."""
    match = _FIRST_NUMBER.search(clean_text(value))
    if not match:
        return None
    rating = Decimal(match.group()).quantize(Decimal('0.1'))
    return rating if 0 <= rating <= 5 else None


def _refresh_best_price(product: Product) -> None:
    """Keep Product.price = cheapest in-stock offer (else cheapest known), so search/sort keep working."""
    priced = product.offers.filter(price__isnull=False)
    best = priced.filter(in_stock=True).aggregate(m=Min('price'))['m']
    if best is None:
        best = priced.aggregate(m=Min('price'))['m']
    product.price = best
    product.is_available = product.offers.filter(in_stock=True).exists()
    product.save(update_fields=['price', 'is_available', 'last_updated'])


@transaction.atomic
def ingest_listing(listing: Listing) -> dict:
    """Upsert a listing. Returns {'product_created', 'offer_created', 'price_changed'}."""
    name = clean_text(listing.name)
    seller = clean_text(listing.seller)
    if not name or not seller:
        raise ValueError('listing needs a name and a seller')
    url = canonical_url(clean_text(listing.url))
    price = to_decimal(listing.price)
    mrp = to_decimal(listing.mrp)
    rating = parse_rating(listing.rating)
    image_url = clean_text(listing.image_url)
    delivery_date = clean_text(listing.delivery_date)

    # 1) Same seller + same listing URL is the strongest identity. Never match on an empty URL.
    offer = (Offer.objects.select_related('product').filter(seller=seller, url=url).first()
             if url else None)
    product_created = False
    if offer is None:
        # 2) Otherwise match the product by name within the category (case-insensitive).
        product = Product.objects.filter(name__iexact=name, category=listing.category).first()
        if product is None:
            product = Product.objects.create(
                name=name, product_url=url, category=listing.category,
                image_url=image_url, rating=rating, source_site=seller)
            product_created = True
        offer, offer_created = Offer.objects.get_or_create(
            product=product, seller=seller,
            defaults={'url': url, 'price': price, 'mrp': mrp,
                      'in_stock': listing.in_stock, 'delivery_date': delivery_date})
    else:
        product, offer_created = offer.product, False

    price_changed = offer_created or offer.price != price or offer.in_stock != listing.in_stock
    if not offer_created:
        offer.url = url or offer.url
        offer.price, offer.mrp = price, mrp
        offer.in_stock, offer.delivery_date = listing.in_stock, delivery_date
        offer.save()
    if price_changed:
        PricePoint.objects.create(offer=offer, price=price, in_stock=listing.in_stock)

    # Fill gaps in product metadata without overwriting good data.
    changed = []
    if image_url and not product.image_url:
        product.image_url = image_url; changed.append('image_url')
    if rating is not None and product.rating is None:
        product.rating = rating; changed.append('rating')
    if url and not product.product_url:
        product.product_url = url; changed.append('product_url')
    if changed:
        product.save(update_fields=changed)

    _refresh_best_price(product)
    return {'product_created': product_created, 'offer_created': offer_created,
            'price_changed': price_changed}
