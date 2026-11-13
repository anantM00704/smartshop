import json

from django.core.management.base import BaseCommand, CommandError

from products.ingestion import Listing, clean_text, ingest_listing
from products.models import Category


class Command(BaseCommand):
    help = ("Ingest listings from a JSON file: a list of objects with name, seller, url, "
            "price and optional mrp, in_stock, image_url, rating, delivery_date, "
            "category (sub-category name) and main_category (parent name, used when creating it).")

    def add_arguments(self, parser):
        parser.add_argument('json_file')

    def handle(self, *args, **options):
        try:
            with open(options['json_file'], encoding='utf8') as fh:
                rows = json.load(fh)
        except (OSError, ValueError) as exc:
            raise CommandError(f'Cannot read {options["json_file"]}: {exc}')
        if not isinstance(rows, list):
            raise CommandError('Expected a JSON list of listing objects')

        categories = {}
        totals = {'product_created': 0, 'offer_created': 0, 'price_changed': 0, 'skipped': 0}
        for index, row in enumerate(rows):
            if not (isinstance(row, dict) and clean_text(row.get('name')) and clean_text(row.get('seller'))):
                totals['skipped'] += 1
                self.stderr.write(f'Row {index}: missing name or seller, skipped')
                continue
            category = self._category(categories, clean_text(row.get('category')), clean_text(row.get('main_category')))
            listing = Listing(
                name=row['name'], seller=row['seller'], url=row.get('url', ''),
                category=category, price=row.get('price'), mrp=row.get('mrp'),
                in_stock=bool(row.get('in_stock', True)), image_url=row.get('image_url', ''),
                rating=row.get('rating'), delivery_date=row.get('delivery_date', ''),
            )
            try:
                result = ingest_listing(listing)
            except ValueError as exc:
                totals['skipped'] += 1
                self.stderr.write(f'Row {index}: {exc}, skipped')
                continue
            for key, value in result.items():
                totals[key] += int(value)

        self.stdout.write(self.style.SUCCESS(
            f"{len(rows)} rows: {totals['product_created']} new products, {totals['offer_created']} new offers, "
            f"{totals['price_changed']} price changes, {totals['skipped']} skipped"))

    @staticmethod
    def _category(cache, name, parent_name):
        if not name:
            return None
        key = (name, parent_name)
        if key not in cache:
            category = Category.objects.filter(name=name).first()
            if category is None:
                parent = Category.objects.get_or_create(name=parent_name, parent=None)[0] if parent_name else None
                category = Category.objects.create(name=name, parent=parent)
            cache[key] = category
        return cache[key]
