import json
import os
import tempfile
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .ingestion import Listing, canonical_url, clean_text, ingest_listing, parse_rating, to_decimal
from .models import Category, Offer, PricePoint, Product


class CleaningTests(TestCase):
    def test_canonical_amazon_url_strips_tracking(self):
        url = 'https://www.amazon.in/Apple-iPhone-15-128-GB/dp/b0chx1w1xy/ref=sr_1_1?keywords=iphone&qid=1'
        self.assertEqual(canonical_url(url), 'https://www.amazon.in/dp/B0CHX1W1XY')

    def test_canonical_flipkart_url_keeps_only_pid(self):
        url = 'https://www.flipkart.com/samsung-s24/p/itm123?pid=MOBGX&lid=LST&marketplace=FLIPKART'
        self.assertEqual(canonical_url(url), 'https://www.flipkart.com/samsung-s24/p/itm123?pid=MOBGX')

    def test_canonical_other_url_drops_query(self):
        self.assertEqual(canonical_url('https://www.nykaa.com/lipstick/p/123?utm=x#r'), 'https://www.nykaa.com/lipstick/p/123')
        self.assertEqual(canonical_url(''), '')

    def test_clean_text_handles_nan_and_whitespace(self):
        self.assertEqual(clean_text(float('nan')), '')
        self.assertEqual(clean_text('nan'), '')
        self.assertEqual(clean_text('  Slim   Fit\nShirt '), 'Slim Fit Shirt')

    def test_to_decimal(self):
        self.assertEqual(to_decimal('₹1,299.00'), Decimal('1299.00'))
        self.assertIsNone(to_decimal('N/A'))
        self.assertIsNone(to_decimal(float('nan')))
        self.assertIsNone(to_decimal('-5'))

    def test_parse_rating(self):
        self.assertEqual(parse_rating('4.2 out of 5 stars'), Decimal('4.2'))
        self.assertIsNone(parse_rating('12 ratings out of'))  # 12 > 5
        self.assertIsNone(parse_rating(''))


class IngestListingTests(TestCase):
    def setUp(self):
        self.phones = Category.objects.create(name='Mobile Phones')

    def listing(self, **overrides):
        data = dict(name='Apple iPhone 15', seller='Amazon', url='https://www.amazon.in/x/dp/B0CHX1W1XY/ref=a',
                    category=self.phones, price='59,999', mrp='69,900', rating='4.5 out of 5')
        data.update(overrides)
        return Listing(**data)

    def test_first_ingest_creates_product_offer_and_history(self):
        result = ingest_listing(self.listing())
        self.assertEqual(result, {'product_created': True, 'offer_created': True, 'price_changed': True})
        product = Product.objects.get()
        self.assertEqual(product.price, Decimal('59999'))
        self.assertEqual(product.rating, Decimal('4.5'))
        self.assertEqual(product.offers.get().url, 'https://www.amazon.in/dp/B0CHX1W1XY')
        self.assertEqual(PricePoint.objects.count(), 1)

    def test_same_listing_again_records_no_new_history(self):
        ingest_listing(self.listing())
        result = ingest_listing(self.listing(url='https://www.amazon.in/dp/B0CHX1W1XY?tag=other'))
        self.assertEqual(result, {'product_created': False, 'offer_created': False, 'price_changed': False})
        self.assertEqual((Product.objects.count(), Offer.objects.count(), PricePoint.objects.count()), (1, 1, 1))

    def test_price_change_appends_history_and_updates_product(self):
        ingest_listing(self.listing())
        result = ingest_listing(self.listing(price='54999'))
        self.assertTrue(result['price_changed'])
        self.assertEqual(Product.objects.get().price, Decimal('54999'))
        self.assertEqual(list(PricePoint.objects.values_list('price', flat=True)), [Decimal('54999'), Decimal('59999')])

    def test_second_seller_joins_same_product_and_best_price_wins(self):
        ingest_listing(self.listing())
        ingest_listing(self.listing(name='apple iphone 15', seller='Flipkart',
                                    url='https://www.flipkart.com/iphone/p/itm1?pid=MOB1', price='58999'))
        product = Product.objects.get()
        self.assertEqual(product.offers.count(), 2)
        self.assertEqual(product.price, Decimal('58999'))

    def test_out_of_stock_keeps_last_known_price(self):
        ingest_listing(self.listing())
        ingest_listing(self.listing(in_stock=False))
        product = Product.objects.get()
        self.assertFalse(product.is_available)
        self.assertEqual(product.price, Decimal('59999'))

    def test_empty_urls_do_not_merge_different_products(self):
        ingest_listing(self.listing(name='boAt Airdopes 141', url=''))
        ingest_listing(self.listing(name='JBL Tune 230NC', url=''))
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(Offer.objects.count(), 2)

    def test_existing_metadata_not_overwritten_but_gaps_filled(self):
        ingest_listing(self.listing(image_url=''))
        ingest_listing(self.listing(image_url='https://img/1.jpg', rating='3.0'))
        product = Product.objects.get()
        self.assertEqual(product.image_url, 'https://img/1.jpg')
        self.assertEqual(product.rating, Decimal('4.5'))

    def test_missing_name_rejected(self):
        with self.assertRaises(ValueError):
            ingest_listing(self.listing(name='  '))


class CommandTests(TestCase):
    def write_temp(self, suffix, content):
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, 'w', encoding='utf8') as fh:
            fh.write(content)
        self.addCleanup(os.remove, path)
        return path

    def test_ingest_listings_command(self):
        path = self.write_temp('.json', json.dumps([
            {'name': 'Galaxy S24', 'seller': 'Flipkart', 'url': 'https://www.flipkart.com/s24/p/i?pid=P1',
             'price': '74,999', 'category': 'Mobile Phones', 'main_category': 'Electronics'},
            {'name': 'Galaxy S24', 'seller': 'Amazon', 'url': 'https://www.amazon.in/dp/B0CS5XW6TN', 'price': 73999,
             'category': 'Mobile Phones'},
            {'seller': 'Amazon'},
        ]))
        out, err = StringIO(), StringIO()
        call_command('ingest_listings', path, stdout=out, stderr=err)
        self.assertIn('1 new products, 2 new offers', out.getvalue())
        self.assertIn('1 skipped', out.getvalue())
        product = Product.objects.get()
        self.assertEqual(product.category.parent.name, 'Electronics')
        self.assertEqual(product.price, Decimal('73999'))

    def test_import_csv_maps_columns_and_ignores_empty_cells(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        target = os.path.join(tmpdir.name, 'lipstick_amazon.csv')  # mapping is keyed on the file name
        with open(target, 'w', encoding='utf8') as fh:
            fh.write(
                'name_name,name_url,name_price,name_delivery_date_name,name_ratings\n'
                'Maybelline Matte Lipstick,https://www.amazon.in/m/dp/B01ABCDEFG/ref=x,"₹ 349",Tomorrow,4.1 out of 5 stars\n'
                'Lakme 9to5,,,,\n'
                ',,199,,\n'
            )

        out = StringIO()
        call_command('import_csv', target, main_category="Women's Fashion", sub_category='Lipsticks', stdout=out)
        self.assertIn('2 new products', out.getvalue())
        self.assertIn('1 skipped', out.getvalue())
        maybelline = Product.objects.get(name='Maybelline Matte Lipstick')
        self.assertEqual((maybelline.price, maybelline.rating, maybelline.source_site),
                         (Decimal('349'), Decimal('4.1'), 'Amazon'))
        self.assertEqual(maybelline.product_url, 'https://www.amazon.in/dp/B01ABCDEFG')
        lakme = Product.objects.get(name='Lakme 9to5')
        self.assertIsNone(lakme.price)
        self.assertEqual(lakme.delivery_date or '', '')
        self.assertNotIn('nan', (lakme.product_url, lakme.image_url))
