"""OTP generation and delivery for password reset.

Delivery channels are tried in order; the OTP counts as delivered if any channel succeeds.
  - SMS via Twilio: enabled when TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER are set.
  - Email: enabled when the user has an email address and SMTP is configured.
  - Console: when DEBUG is on, the OTP is also logged to the server terminal for local testing.
"""
import base64
import logging
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

OTP_TTL_MINUTES = 5
MAX_VERIFY_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60


def generate_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def mask_email(email):
    name, _, domain = email.partition('@')
    return f"{name[:2]}{'*' * max(len(name) - 2, 1)}@{domain}"


def mask_mobile(mobile):
    return f"{'*' * max(len(mobile) - 4, 0)}{mobile[-4:]}"


def _to_e164(mobile):
    digits = ''.join(ch for ch in mobile if ch.isdigit() or ch == '+')
    if digits.startswith('+'):
        return digits
    country_code = os.environ.get('SMS_DEFAULT_COUNTRY_CODE', '+91')
    return f"{country_code}{digits[-10:]}"


def _send_sms_twilio(mobile, message):
    sid = os.environ.get('TWILIO_ACCOUNT_SID')
    token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_number = os.environ.get('TWILIO_FROM_NUMBER')
    if not (sid and token and from_number):
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = urllib.parse.urlencode({'To': _to_e164(mobile), 'From': from_number, 'Body': message}).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Authorization', 'Basic ' + base64.b64encode(f"{sid}:{token}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("Twilio SMS failed: %s", exc)
        return False


def _send_email(email, otp):
    if not (email and settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD):
        return False
    try:
        send_mail(
            subject='Your SmartShop password reset code',
            message=(
                f"Your SmartShop verification code is {otp}.\n\n"
                f"It expires in {OTP_TTL_MINUTES} minutes. If you didn't request this, ignore this email."
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
        )
        return True
    except Exception as exc:  # SMTP errors vary widely; never crash the reset flow
        logger.warning("OTP email failed: %s", exc)
        return False


def deliver_otp(user, mobile, otp):
    """Send the OTP over every available channel. Returns a list of masked destinations reached."""
    reached = []
    message = f"{otp} is your SmartShop verification code. Valid for {OTP_TTL_MINUTES} minutes."
    if _send_sms_twilio(mobile, message):
        reached.append(f"SMS to {mask_mobile(mobile)}")
    if _send_email(user.email, otp):
        reached.append(f"email to {mask_email(user.email)}")
    if settings.DEBUG:
        logger.warning("[DEV] OTP for %s is %s", mask_mobile(mobile), otp)
    return reached
