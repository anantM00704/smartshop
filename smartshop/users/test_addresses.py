from django.test import TestCase
from django.urls import reverse

from .models import Address, CustomUser

VALID = dict(label='home', full_name='Anant M', phone='98765 43210', line1='12 MG Road',
             line2='Near Clock Tower', city='Pilani', state='Rajasthan', pincode='333031')


class AddressTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(username='u', mobile_number='9876543210', password='Pass-word-123')
        self.client.force_login(self.user)

    def add(self, **overrides):
        return self.client.post(reverse('address_add'), {**VALID, **overrides})

    def test_first_address_becomes_default_and_phone_is_normalised(self):
        resp = self.add()
        self.assertRedirects(resp, reverse('address_list'))
        address = Address.objects.get()
        self.assertTrue(address.is_default)
        self.assertEqual(address.phone, '9876543210')

    def test_new_default_replaces_old_default(self):
        self.add()
        self.add(city='Jaipur', is_default='on')
        self.assertEqual(Address.objects.get(is_default=True).city, 'Jaipur')
        self.assertEqual(Address.objects.filter(is_default=True).count(), 1)

    def test_non_default_address_does_not_steal_default(self):
        self.add()
        self.add(city='Jaipur')
        self.assertEqual(Address.objects.get(is_default=True).city, 'Pilani')

    def test_validation(self):
        resp = self.add(pincode='12345', phone='12')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Address.objects.exists())
        self.assertContains(resp, '6-digit PIN code')
        self.assertContains(resp, 'valid mobile number')

    def test_delete_default_promotes_another(self):
        self.add()
        self.add(city='Jaipur')
        default = Address.objects.get(is_default=True)
        self.client.post(reverse('address_delete', args=[default.id]))
        self.assertEqual(Address.objects.get().is_default, True)

    def test_set_default(self):
        self.add()
        self.add(city='Jaipur')
        jaipur = Address.objects.get(city='Jaipur')
        self.client.post(reverse('address_make_default', args=[jaipur.id]))
        jaipur.refresh_from_db()
        self.assertTrue(jaipur.is_default)
        self.assertEqual(Address.objects.filter(is_default=True).count(), 1)

    def test_edit_keeps_default(self):
        self.add()
        address = Address.objects.get()
        self.client.post(reverse('address_edit', args=[address.id]), {**VALID, 'city': 'Kota'})
        address.refresh_from_db()
        self.assertEqual((address.city, address.is_default), ('Kota', True))

    def test_cap_on_saved_addresses(self):
        for i in range(Address.MAX_PER_USER):
            Address.objects.create(user=self.user, **{**VALID, 'phone': '9876543210', 'is_default': i == 0})
        resp = self.add()
        self.assertEqual(Address.objects.count(), Address.MAX_PER_USER)
        self.assertContains(resp, f'up to {Address.MAX_PER_USER} addresses')

    def test_cannot_touch_another_users_address(self):
        other = CustomUser.objects.create_user(username='o', mobile_number='2', password='Pass-word-123')
        theirs = Address.objects.create(user=other, **{**VALID, 'phone': '9876543210', 'is_default': True})
        self.assertEqual(self.client.get(reverse('address_edit', args=[theirs.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('address_delete', args=[theirs.id])).status_code, 404)
        self.assertTrue(Address.objects.filter(pk=theirs.pk).exists())

    def test_next_redirect_only_to_same_site(self):
        resp = self.add(next='/cart/')
        self.assertRedirects(resp, '/cart/', fetch_redirect_response=False)
        resp = self.add(next='https://evil.example.com/', city='Kota')
        self.assertRedirects(resp, reverse('address_list'))

    def test_add_form_prefilled_from_account(self):
        resp = self.client.get(reverse('address_add'))
        self.assertContains(resp, 'value="9876543210"')

    def test_navbar_shows_default_address(self):
        self.add()
        resp = self.client.get(reverse('address_list'))
        self.assertContains(resp, 'Pilani 333031')

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('address_list')).status_code, 302)
