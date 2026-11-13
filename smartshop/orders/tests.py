from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from orders.models import CartItem, Order
from products.models import Product
from users.models import Address, CustomUser

ADDRESS = dict(label='home', full_name='Anant M', phone='9876543210', line1='12 MG Road',
               city='Pilani', state='Rajasthan', pincode='333031')


class CartTests(TestCase):
    def setUp(self):
        self.shirt = Product.objects.create(name='Shirt', product_url='https://example.com/1',
                                            price=Decimal('999'), source_site='Amazon')
        self.phone = Product.objects.create(name='Phone', product_url='https://example.com/2', price=Decimal('15000'))
        self.no_price = Product.objects.create(name='Mystery', product_url='https://example.com/3')
        self.user = CustomUser.objects.create_user(username='u', mobile_number='1', password='Pass-word-123')
        self.client.force_login(self.user)

    def add(self, product, quantity=1, **extra):
        return self.client.post(reverse('cart_add'), {'product_id': product.id, 'quantity': quantity, **extra})

    def test_add_increments_and_caps_quantity(self):
        self.add(self.shirt)
        self.add(self.shirt, 3)
        self.assertEqual(CartItem.objects.get().quantity, 4)
        self.add(self.shirt, 50)
        self.assertEqual(CartItem.objects.get().quantity, CartItem.MAX_QUANTITY)

    def test_unavailable_and_missing_products_rejected(self):
        self.add(self.no_price)
        self.client.post(reverse('cart_add'), {'product_id': 99999})
        self.client.post(reverse('cart_add'), {'product_id': self.shirt.id, 'quantity': 'abc'})
        self.client.post(reverse('cart_add'), {'product_id': self.shirt.id, 'quantity': 0})
        self.assertFalse(CartItem.objects.exists())

    def test_buy_now_goes_to_cart_and_next_is_respected(self):
        self.assertRedirects(self.add(self.shirt, buy_now='1'), reverse('cart'))
        resp = self.add(self.phone, next='/search/?q=phone')
        self.assertRedirects(resp, '/search/?q=phone', fetch_redirect_response=False)
        resp = self.add(self.phone, next='https://evil.example.com/')
        self.assertRedirects(resp, reverse('cart'))

    def test_cart_page_totals_and_navbar_count(self):
        self.add(self.shirt, 2)
        self.add(self.phone)
        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.context['cart'].subtotal, Decimal('16998'))
        self.assertEqual(resp.context['cart_count'], 3)
        self.assertContains(resp, '₹16998')

    def test_update_and_remove(self):
        self.add(self.shirt)
        item = CartItem.objects.get()
        self.client.post(reverse('cart_update', args=[item.id]), {'quantity': 5})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 5)
        self.client.post(reverse('cart_remove', args=[item.id]))
        self.assertFalse(CartItem.objects.exists())

    def test_cannot_modify_another_users_cart(self):
        other = CustomUser.objects.create_user(username='o', mobile_number='2', password='Pass-word-123')
        theirs = CartItem.objects.create(user=other, product=self.shirt, quantity=1)
        self.client.post(reverse('cart_update', args=[theirs.id]), {'quantity': 9})
        self.client.post(reverse('cart_remove', args=[theirs.id]))
        theirs.refresh_from_db()
        self.assertEqual(theirs.quantity, 1)

    def test_get_on_actions_not_allowed_and_login_required(self):
        self.assertEqual(self.client.get(reverse('cart_add')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('cart')).status_code, 302)
        self.assertEqual(self.add(self.shirt).status_code, 302)
        self.assertFalse(CartItem.objects.exists())


class CheckoutTests(TestCase):
    def setUp(self):
        self.shirt = Product.objects.create(name='Shirt', product_url='https://example.com/1',
                                            price=Decimal('999'), source_site='Amazon')
        self.user = CustomUser.objects.create_user(username='u', mobile_number='1', password='Pass-word-123')
        self.address = Address.objects.create(user=self.user, is_default=True, **ADDRESS)
        self.client.force_login(self.user)

    def checkout(self, address=None):
        return self.client.post(reverse('checkout'), {'address_id': (address or self.address).id})

    def test_checkout_creates_order_with_price_snapshot_and_clears_cart(self):
        CartItem.objects.create(user=self.user, product=self.shirt, quantity=2)
        resp = self.checkout()
        self.assertRedirects(resp, reverse('orders'))
        order = Order.objects.get()
        self.assertEqual(order.total_amount, Decimal('1998'))
        self.assertIn('Pilani, Rajasthan - 333031', order.address)
        item = order.items.get()
        self.assertEqual((item.product_name, item.seller, item.unit_price, item.quantity),
                         ('Shirt', 'Amazon', Decimal('999'), 2))
        self.assertFalse(CartItem.objects.exists())

        # later price or address changes don't rewrite the order
        self.shirt.price = Decimal('1299'); self.shirt.save()
        self.address.city = 'Jaipur'; self.address.save()
        item.refresh_from_db(); order.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal('999'))
        self.assertIn('Pilani', order.address)

    def test_empty_cart_rejected(self):
        self.assertRedirects(self.checkout(), reverse('cart'))
        self.assertFalse(Order.objects.exists())

    def test_unavailable_item_blocks_checkout(self):
        CartItem.objects.create(user=self.user, product=self.shirt, quantity=1)
        self.shirt.is_available = False; self.shirt.save()
        self.checkout()
        self.assertFalse(Order.objects.exists())
        self.assertTrue(CartItem.objects.exists())

    def test_cannot_ship_to_another_users_address(self):
        other = CustomUser.objects.create_user(username='o', mobile_number='2', password='Pass-word-123')
        theirs = Address.objects.create(user=other, is_default=True, **ADDRESS)
        CartItem.objects.create(user=self.user, product=self.shirt, quantity=1)
        self.assertEqual(self.checkout(theirs).status_code, 404)
        self.assertFalse(Order.objects.exists())

    def test_cart_page_shows_at_most_five_addresses_with_view_all_link(self):
        for i in range(6):
            Address.objects.create(user=self.user, **{**ADDRESS, 'city': f'City{i}'})
        CartItem.objects.create(user=self.user, product=self.shirt, quantity=1)
        resp = self.client.get(reverse('cart'))
        self.assertEqual(len(resp.context['addresses']), 5)
        self.assertEqual(resp.context['addresses'][0], self.address)   # default first
        self.assertContains(resp, 'View all 7 saved addresses')
        self.assertContains(resp, reverse('address_list'))

    def test_orders_page_lists_only_own_orders(self):
        other = CustomUser.objects.create_user(username='o', mobile_number='2', password='Pass-word-123')
        Order.objects.create(user=other, address='x')
        CartItem.objects.create(user=self.user, product=self.shirt, quantity=1)
        self.checkout()
        resp = self.client.get(reverse('orders'))
        self.assertEqual([o.user for o in resp.context['orders']], [self.user])
        self.assertContains(resp, 'Shirt')
