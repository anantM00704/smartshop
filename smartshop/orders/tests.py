from django.test import TestCase
from django.urls import reverse

from orders.models import Order
from products.models import Product
from users.models import CustomUser


class PlaceOrderTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='Shirt', product_url='https://example.com/1')
        self.user = CustomUser.objects.create_user(username='u', mobile_number='1', password='Pass-word-123')
        self.url = reverse('place_order')

    def test_anonymous_user_redirected_to_login(self):
        resp = self.client.post(self.url, {'product_id': self.product.id, 'address': 'Somewhere'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('login'), resp['Location'])
        self.assertFalse(Order.objects.exists())

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_order_created(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {'product_id': self.product.id, 'address': '  221B Baker Street '})
        self.assertRedirects(resp, reverse('orders'))
        order = Order.objects.get()
        self.assertEqual((order.user, order.product, order.address), (self.user, self.product, '221B Baker Street'))

    def test_blank_address_rejected(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {'product_id': self.product.id, 'address': '   '})
        self.assertFalse(Order.objects.exists())

    def test_orders_page_lists_only_own_orders(self):
        other = CustomUser.objects.create_user(username='o', mobile_number='2', password='Pass-word-123')
        Order.objects.create(user=other, product=self.product, address='x', status='Placed')
        self.client.force_login(self.user)
        resp = self.client.get(reverse('orders'))
        self.assertEqual(list(resp.context['orders']), [])
