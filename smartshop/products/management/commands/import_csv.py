"""Import scraped CSV exports through the shared ingestion service.

Each known export file has its own column names (from the original scraping tool);
COLUMN_MAPS translates them to listing fields. Unknown files fall back to generic names.
"""
import os

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from products.ingestion import Listing, clean_text, ingest_listing
from products.models import Category

# field -> candidate column names, first non-empty wins
COLUMN_MAPS = {
    'shirts_amazon.csv': {
        'name': ['brand_shirt', 'brand_name'], 'url': ['brand_shirt_url'],
        'price': ['brand_price'], 'delivery_date': ['brand_delivery_date'],
    },
    'shirt_flipkart.csv': {
        'name': ['name_shirt_type', 'name_name'], 'url': ['name_shirt_type_url'], 'price': ['name_price'],
    },
    'earphones.csv': {'name': ['name_name'], 'price': ['name_price']},
    'earphones_flipkart.csv': {'name': ['name_name'], 'url': ['name_price_url'], 'price': ['name_price']},
    'tops_amazon.csv': {
        'name': ['brand_type', 'brand_name'], 'url': ['brand_type_url'],
        'price': ['brand_price'], 'delivery_date': ['brand_delivery_date_name'],
    },
    'lipstick_amazon.csv': {
        'name': ['name_name'], 'url': ['name_url'], 'price': ['name_price'],
        'delivery_date': ['name_delivery_date_name'],
    },
    'lipstick_nykaa.csv': {'name': ['name_name'], 'url': ['name_url'], 'price': ['name_price']},
}

GENERIC_MAP = {
    'name': ['name', 'brand_name', 'brand_shirt', 'brand_type', 'name_name'],
    'url': ['product_url', 'url', 'name_url', 'brand_shirt_url', 'brand_type_url'],
    'price': ['price', 'name_price', 'brand_price'],
    'mrp': ['mrp', 'original_price'],
    'delivery_date': ['delivery_date', 'brand_delivery_date', 'brand_delivery_date_name'],
}
COMMON_FIELDS = {
    'image_url': ['image_url', 'image'],
    'rating': ['rating', 'name_ratings'],
}


def detect_seller(file_name, explicit=None):
    if explicit:
        return explicit
    for seller in ('Amazon', 'Flipkart', 'Nykaa', 'Myntra'):
        if seller.lower() in file_name:
            return seller
    return 'Unknown'


def pick(row, columns):
    for column in columns:
        value = clean_text(row.get(column))
        if value:
            return value
    return ''


class Command(BaseCommand):
    help = 'Import products from a scraped CSV into a main category > sub category.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='CSV file to import')
        parser.add_argument('--main_category', type=str, required=True, help='Main category name')
        parser.add_argument('--sub_category', type=str, required=True, help='Subcategory name')
        parser.add_argument('--seller', type=str, help='Seller name (default: detected from file name)')

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        try:
            df = pd.read_csv(csv_file, dtype=str, keep_default_na=False)
        except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
            raise CommandError(f'Cannot read {csv_file}: {exc}')

        main_cat, _ = Category.objects.get_or_create(name=options['main_category'], parent=None)
        category, _ = Category.objects.get_or_create(name=options['sub_category'], parent=main_cat)
        file_name = os.path.basename(csv_file).lower()
        seller = detect_seller(file_name, options.get('seller'))
        columns = {**GENERIC_MAP, **COLUMN_MAPS.get(file_name, {}), **COMMON_FIELDS}

        totals = {'product_created': 0, 'offer_created': 0, 'price_changed': 0, 'skipped': 0}
        for _, row in df.iterrows():
            fields = {field: pick(row, cols) for field, cols in columns.items()}
            if not fields['name']:
                totals['skipped'] += 1
                continue
            result = ingest_listing(Listing(
                name=fields['name'], seller=seller, url=fields.get('url', ''), category=category,
                price=fields.get('price'), mrp=fields.get('mrp'), image_url=fields.get('image_url', ''),
                rating=fields.get('rating'), delivery_date=fields.get('delivery_date', ''),
            ))
            for key, value in result.items():
                totals[key] += int(value)

        self.stdout.write(self.style.SUCCESS(
            f"{len(df)} rows from {seller} into {main_cat} > {category}: "
            f"{totals['product_created']} new products, {totals['offer_created']} new offers, "
            f"{totals['price_changed']} price changes, {totals['skipped']} skipped"))
