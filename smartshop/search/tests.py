from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from products.models import Category, Product
from recommendation.models import SearchHistory
from users.models import CustomUser


def make_catalog():
    electronics = Category.objects.create(name='Electronics')
    phones = Category.objects.create(name='Mobile Phones', parent=electronics)
    fashion = Category.objects.create(name="Men's Fashion")
    shirts = Category.objects.create(name='Shirts', parent=fashion)
    Product.objects.create(name='Apple iPhone 15 (128 GB) - Black', product_url='https://example.com/1', price=Decimal('59499'), category=phones, source_site='Amazon')
    Product.objects.create(name='Samsung Galaxy S24', product_url='https://example.com/2', price=Decimal('74999'), category=phones, source_site='Flipkart')
    Product.objects.create(name='Allen Solly Slim Fit Shirt', product_url='https://example.com/3', price=Decimal('999'), category=shirts, source_site='Amazon')
    return phones, shirts


class SearchTests(TestCase):
    def setUp(self):
        self.phones, self.shirts = make_catalog()
        self.url = reverse('search_results')

    def names(self, resp):
        return [p.name for p in resp.context['products']]

    def test_urls_are_not_duplicated(self):
        self.assertEqual(self.url, '/search/')
        self.assertEqual(reverse('autocomplete'), '/autocomplete/')
        self.assertEqual(reverse('orders'), '/orders/')

    def test_text_search_finds_product_with_typo(self):
        resp = self.client.get(self.url, {'q': 'iphne 15'})
        self.assertIn('Apple iPhone 15 (128 GB) - Black', self.names(resp))

    def test_exact_match_ranked_first(self):
        resp = self.client.get(self.url, {'q': 'Samsung'})
        self.assertEqual(self.names(resp)[0], 'Samsung Galaxy S24')

    def test_category_query_filters_by_category(self):
        resp = self.client.get(self.url, {'q': 'shirts'})
        self.assertEqual(self.names(resp), ['Allen Solly Slim Fit Shirt'])

    def test_parent_category_includes_subcategories(self):
        resp = self.client.get(self.url, {'category': 'Electronics'})
        self.assertEqual(resp.context['count'], 2)

    def test_price_filter_and_sort(self):
        resp = self.client.get(self.url, {'min_price': '1000', 'sort': 'price_desc'})
        self.assertEqual(self.names(resp), ['Samsung Galaxy S24', 'Apple iPhone 15 (128 GB) - Black'])

    def test_invalid_price_is_ignored(self):
        resp = self.client.get(self.url, {'min_price': 'abc'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['count'], 3)

    def test_pagination(self):
        for i in range(30):
            Product.objects.create(name=f'Bulk item {i}', product_url='https://example.com/x', category=self.shirts)
        resp = self.client.get(self.url, {'page': 2})
        self.assertEqual(resp.context['page'].number, 2)
        self.assertEqual(len(resp.context['products']), 33 - 24)

    def test_history_recorded_once_for_logged_in_user(self):
        user = CustomUser.objects.create_user(username='u', mobile_number='1', password='Pass-word-123')
        self.client.force_login(user)
        self.client.get(self.url, {'q': 'iphone'})
        self.client.get(self.url, {'q': 'iphone', 'page': 2})
        self.assertEqual(SearchHistory.objects.filter(user=user).count(), 1)

    def test_autocomplete(self):
        resp = self.client.get(reverse('autocomplete'), {'q': 'sams'})
        self.assertIn('Samsung Galaxy S24', resp.json()['suggestions'])
        self.assertEqual(self.client.get(reverse('autocomplete'), {'q': 's'}).json()['suggestions'], [])


class DashboardTests(TestCase):
    def setUp(self):
        make_catalog()
        self.user = CustomUser.objects.create_user(username='u', mobile_number='1', password='Pass-word-123')
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)

    def test_recent_searches_drive_pick_up_section(self):
        SearchHistory.objects.create(user=self.user, query='iphone')
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual([p.name for p in resp.context['pick_up_products']], ['Apple iPhone 15 (128 GB) - Black'])
        self.assertIn('Mobile Phones', [c.name for c in resp.context['categories_to_explore']])
        self.assertContains(resp, 'Apple iPhone 15')

    def test_new_user_gets_fallback_categories(self):
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['categories_to_explore'])
