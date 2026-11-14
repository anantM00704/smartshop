"""Run an adapter for a query and push results through the shared ingestion service."""
import logging

from django.utils import timezone

from products.ingestion import Listing, ingest_listing
from products.models import Category

from .exceptions import ScrapeError
from .models import ScrapeRun

logger = logging.getLogger(__name__)


def resolve_category(name, parent_name=''):
    if not name:
        return None
    category = Category.objects.filter(name=name).first()
    if category is None:
        parent = Category.objects.get_or_create(name=parent_name, parent=None)[0] if parent_name else None
        category = Category.objects.create(name=name, parent=parent)
    return category


def run_query(adapter, query, category_name='', parent_category='', limit=10, dry_run=False):
    """Fetch listings for one query. Returns (ScrapeRun or None for dry runs, listings)."""
    run = None if dry_run else ScrapeRun.objects.create(
        source=adapter.name, query=query[:255], category=category_name[:255])
    try:
        listings = adapter.search(query, limit=limit)
    except ScrapeError as exc:
        if run:
            run.status, run.error, run.finished_at = 'failed', str(exc), timezone.now()
            run.save()
        raise

    if dry_run:
        return None, listings

    category = resolve_category(category_name, parent_category)
    run.fetched = len(listings)
    errors = []
    for scraped in listings:
        try:
            result = ingest_listing(Listing(
                name=scraped.name, seller=adapter.seller, url=scraped.url, category=category,
                price=scraped.price, mrp=scraped.mrp, in_stock=scraped.in_stock,
                image_url=scraped.image_url, rating=scraped.rating, delivery_date=scraped.delivery_date))
        except ValueError as exc:
            run.skipped += 1
            errors.append(f'{scraped.name[:60]}: {exc}')
            continue
        run.products_created += int(result['product_created'])
        run.offers_created += int(result['offer_created'])
        run.price_changes += int(result['price_changed'])

    run.status = 'partial' if errors else 'ok'
    run.error = '\n'.join(errors[:20])
    run.finished_at = timezone.now()
    run.save()
    logger.info('Scrape %s', run)
    return run, listings
