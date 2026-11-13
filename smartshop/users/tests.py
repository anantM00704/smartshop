from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import CustomUser, PasswordResetOTP
from . import otp as otp_service

SMTP_ON = dict(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST_USER='shop@example.com',
    EMAIL_HOST_PASSWORD='x',
)


class SignUpTests(TestCase):
    def test_signup_creates_user_and_profile_with_mobile(self):
        resp = self.client.post(reverse('sign_up'), {
            'username': 'newuser', 'email': 'new@example.com', 'mobile_number': '9876543210',
            'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
        })
        self.assertEqual(resp.status_code, 302)
        user = CustomUser.objects.get(username='newuser')
        self.assertEqual(user.profile.mobile_number, '9876543210')


@override_settings(**SMTP_ON)
class MobilePasswordResetTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='alice', email='alice@example.com', mobile_number='9876543210', password='Old-pass-123')

    def request_code(self):
        return self.client.post(reverse('password_reset_mobile'), {'mobile': '9876543210'})

    def test_unknown_mobile_shows_error(self):
        resp = self.client.post(reverse('password_reset_mobile'), {'mobile': '0000000000'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PasswordResetOTP.objects.count(), 0)

    def test_code_is_emailed_and_full_flow_resets_password(self):
        resp = self.request_code()
        self.assertRedirects(resp, reverse('password_reset_mobile_verify'))
        self.assertEqual(len(mail.outbox), 1)
        code = PasswordResetOTP.objects.get(user=self.user).otp
        self.assertIn(code, mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ['alice@example.com'])

        resp = self.client.post(reverse('password_reset_mobile_verify'), {'otp': code})
        self.assertRedirects(resp, reverse('password_reset_mobile_set_new_password'))
        self.assertFalse(PasswordResetOTP.objects.exists())  # single use

        resp = self.client.post(reverse('password_reset_mobile_set_new_password'), {
            'new_password1': 'Brand-new-pass-456', 'new_password2': 'Brand-new-pass-456'})
        self.assertRedirects(resp, reverse('login'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Brand-new-pass-456'))

    def test_wrong_code_counts_attempts_then_locks(self):
        self.request_code()
        for _ in range(otp_service.MAX_VERIFY_ATTEMPTS):
            self.client.post(reverse('password_reset_mobile_verify'), {'otp': 'xxxxxx'})
        resp = self.client.post(reverse('password_reset_mobile_verify'), {'otp': 'xxxxxx'})
        self.assertRedirects(resp, reverse('password_reset_mobile'))
        self.assertFalse(PasswordResetOTP.objects.exists())

    def test_expired_code_rejected(self):
        self.request_code()
        otp_obj = PasswordResetOTP.objects.get(user=self.user)
        PasswordResetOTP.objects.filter(pk=otp_obj.pk).update(created_at=timezone.now() - timedelta(minutes=6))
        resp = self.client.post(reverse('password_reset_mobile_verify'), {'otp': otp_obj.otp})
        self.assertRedirects(resp, reverse('password_reset_mobile'))

    def test_resend_cooldown_does_not_issue_new_code(self):
        self.request_code()
        first = PasswordResetOTP.objects.get(user=self.user).otp
        self.request_code()
        self.assertEqual(PasswordResetOTP.objects.get(user=self.user).otp, first)
        self.assertEqual(len(mail.outbox), 1)

    def test_set_password_requires_verified_session(self):
        resp = self.client.get(reverse('password_reset_mobile_set_new_password'))
        self.assertRedirects(resp, reverse('password_reset_mobile'))

    def test_weak_password_rejected(self):
        self.request_code()
        code = PasswordResetOTP.objects.get(user=self.user).otp
        self.client.post(reverse('password_reset_mobile_verify'), {'otp': code})
        resp = self.client.post(reverse('password_reset_mobile_set_new_password'), {
            'new_password1': '123', 'new_password2': '123'})
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Old-pass-123'))

    @mock.patch.dict('os.environ', {'TWILIO_ACCOUNT_SID': 'AC1', 'TWILIO_AUTH_TOKEN': 't', 'TWILIO_FROM_NUMBER': '+15550001111'})
    @mock.patch('users.otp.urllib.request.urlopen')
    def test_sms_sent_via_twilio_when_configured(self, urlopen):
        urlopen.return_value.__enter__.return_value.status = 201
        self.request_code()
        req = urlopen.call_args[0][0]
        self.assertIn('/Accounts/AC1/Messages.json', req.full_url)
        self.assertIn(b'To=%2B919876543210', req.data)


@override_settings(**SMTP_ON)
class UsernameRecoveryTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='alice', email='alice@example.com', mobile_number='9876543210', password='Old-pass-123')

    def test_otp_email_and_success_message_include_username(self):
        self.client.post(reverse('password_reset_mobile'), {'mobile': '9876543210'})
        self.assertIn('Your username, in case you\'ve forgotten: alice', mail.outbox[0].body)
        code = PasswordResetOTP.objects.get(user=self.user).otp
        self.client.post(reverse('password_reset_mobile_verify'), {'otp': code})
        resp = self.client.post(reverse('password_reset_mobile_set_new_password'), {
            'new_password1': 'Brand-new-pass-456', 'new_password2': 'Brand-new-pass-456'}, follow=True)
        self.assertContains(resp, 'alice')

    def test_forgot_username_emails_username(self):
        resp = self.client.post(reverse('forgot_username'), {'email': 'ALICE@example.com'})
        self.assertRedirects(resp, reverse('login'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('alice', mail.outbox[0].body)

    def test_forgot_username_unknown_email_same_response_no_mail(self):
        resp = self.client.post(reverse('forgot_username'), {'email': 'nobody@example.com'})
        self.assertRedirects(resp, reverse('login'))
        self.assertEqual(len(mail.outbox), 0)

    def test_email_link_reset_pages_render_and_email_has_username(self):
        for name in ('password_reset_options', 'password_reset', 'forgot_username'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        resp = self.client.post(reverse('password_reset'), {'email': 'alice@example.com'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.get(resp['Location']).status_code, 200)
        self.assertIn('alice', mail.outbox[0].body)


class PreferenceExtractionTests(TestCase):
    """Sentences as produced by browser speech recognition."""

    def check(self, text, expected):
        from .nlp_utils import extract_preferences_from_text
        self.assertEqual(extract_preferences_from_text(text), expected, msg=text)

    def test_full_sentence(self):
        self.check('I am a man 5 feet 8 inches tall weighing 70 kg and I am 25 years old I like slim fit',
                   {'preferred_department': 'Men', 'height_cm': 173, 'weight_kg': 70,
                    'age_group': '25-34', 'preferred_fit': 'slim'})

    def test_centimetres_not_mistaken_for_metres(self):
        self.check('my height is 175 cm and weight is 68 kilograms', {'height_cm': 175, 'weight_kg': 68})
        self.check('female 160 centimeters loose fit',
                   {'preferred_department': 'Women', 'height_cm': 160, 'preferred_fit': 'loose'})

    def test_number_words(self):
        self.check('I am six feet tall and weigh seventy kilos', {'height_cm': 183, 'weight_kg': 70})
        self.check('five feet eleven inches and seventy two kilos', {'height_cm': 180, 'weight_kg': 72})

    def test_feet_formats(self):
        self.check('I am 5 foot 10', {'height_cm': 178})
        self.check('height 5.8 feet', {'height_cm': 173})       # Indian style: 5 ft 8 in
        self.check('I\'m 5\'8" and 65 kg', {'height_cm': 173, 'weight_kg': 65})
        self.check('I am 1.75 meters tall', {'height_cm': 175})

    def test_age_is_not_read_as_height(self):
        self.check('I am a woman aged 30 with relaxed fit',
                   {'preferred_department': 'Women', 'age_group': '25-34', 'preferred_fit': 'relaxed'})
        self.check('I am 22 my weight is 55 kg', {'weight_kg': 55, 'age_group': '18-24'})

    def test_department_variants_and_first_mention_wins(self):
        self.check('I prefer the mens department', {'preferred_department': 'Men'})
        self.check('I am a man shopping for women', {'preferred_department': 'Men'})

    def test_pounds(self):
        self.check('I weigh 150 pounds and I am 5 ft 6 in', {'height_cm': 168, 'weight_kg': 68})

    def test_nothing_recognised(self):
        self.check('hello there', {})


class PreferenceApiTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(username='u', mobile_number='1', password='Pass-word-123')
        self.url = reverse('process_preferences')

    def test_requires_login(self):
        resp = self.client.post(self.url, '{"text": "man"}', content_type='application/json')
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforced(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        resp = client.post(self.url, '{"text": "man"}', content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_extracts_and_validates(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, '{"text": "I am a man, 6 feet, 80 kg"}', content_type='application/json')
        self.assertEqual(resp.json(), {'status': 'success', 'data': {
            'preferred_department': 'Men', 'height_cm': 183, 'weight_kg': 80}})
        self.assertEqual(self.client.post(self.url, '{}', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(self.url, 'not json', content_type='application/json').status_code, 400)

    def test_profile_page_renders_saved_values(self):
        self.user.profile.height_cm = 173
        self.user.profile.preferred_fit = 'slim'
        self.user.profile.save()
        self.client.force_login(self.user)
        resp = self.client.get(reverse('profile'))
        self.assertContains(resp, 'id="id_height_cm"')
        self.assertContains(resp, 'value="173"')
        self.assertContains(resp, '<option value="slim" selected>')
        self.assertContains(resp, 'id="preference-feedback"')


class OtpHelperTests(TestCase):
    def test_generate_is_six_digits(self):
        for _ in range(50):
            code = otp_service.generate_otp()
            self.assertRegex(code, r'^\d{6}$')

    def test_masking(self):
        self.assertEqual(otp_service.mask_mobile('9876543210'), '******3210')
        self.assertEqual(otp_service.mask_email('alice@example.com'), 'al***@example.com')
