from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone
import datetime
from django.db.models.signals import post_save
from django.dispatch import receiver

class CustomUser(AbstractUser):
    mobile_number = models.CharField(max_length=15, unique=True)
    # email field is already present in AbstractUser

class PasswordResetOTP(models.Model):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    def is_valid(self):
        return timezone.now() < self.created_at + datetime.timedelta(minutes=5)
    
class Profile(models.Model):
    DEPARTMENT_CHOICES = [('Men', 'Men'), ('Women', 'Women')]
    AGE_GROUP_CHOICES = [
        ('18-24', '18-24'), ('25-34', '25-34'), ('35-44', '35-44'),
        ('45-54', '45-54'), ('55+', '55+'),
    ]
    FIT_CHOICES = [
        ('slim', 'Slim Fit'), ('regular', 'Regular Fit'), ('relaxed', 'Relaxed Fit'),
        ('loose', 'Loose Fit'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True)
    mobile_number = models.CharField(max_length=15, blank=True)  # Editable field
    delivery_location = models.TextField(blank=True)
    preferred_department = models.CharField(max_length=10, choices=DEPARTMENT_CHOICES, blank=True, null=True)
    height_cm = models.PositiveIntegerField(verbose_name="Height (cm)", blank=True, null=True)
    weight_kg = models.PositiveIntegerField(verbose_name="Weight (kg)", blank=True, null=True)
    age_group = models.CharField(max_length=10, choices=AGE_GROUP_CHOICES, blank=True, null=True)
    preferred_fit = models.CharField(max_length=10, choices=FIT_CHOICES, blank=True, null=True)
    
    def __str__(self):
        return f'{self.user.username} Profile'
    
class Address(models.Model):
    """A saved delivery address. A user may keep several; exactly one can be the default."""
    MAX_PER_USER = 20          # hard cap on stored addresses
    CHECKOUT_LIMIT = 5         # how many the cart/checkout shows before "View all"

    LABEL_CHOICES = [('home', 'Home'), ('work', 'Work'), ('other', 'Other')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='addresses')
    label = models.CharField(max_length=10, choices=LABEL_CHOICES, default='home')
    full_name = models.CharField('Full name', max_length=100)
    phone = models.CharField('Mobile number', max_length=15, validators=[
        RegexValidator(r'^\+?\d{10,14}$', 'Enter a valid mobile number (10 to 14 digits).')])
    line1 = models.CharField('Flat, house no., building', max_length=200)
    line2 = models.CharField('Area, street, landmark', max_length=200, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField('PIN code', max_length=6, validators=[
        RegexValidator(r'^[1-9]\d{5}$', 'Enter a valid 6-digit PIN code.')])
    is_default = models.BooleanField('Use as default address', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-updated_at']
        verbose_name_plural = 'Addresses'
        constraints = [
            models.UniqueConstraint(fields=['user'], condition=Q(is_default=True),
                                    name='one_default_address_per_user'),
        ]

    def __str__(self):
        return f'{self.get_label_display()}: {self.full_name}, {self.city}'

    @property
    def street(self):
        return ', '.join(part for part in (self.line1, self.line2) if part)

    def as_text(self):
        """Snapshot stored on orders, so later edits don't change past orders."""
        return (f'{self.full_name}, {self.street}, {self.city}, {self.state} - {self.pincode}. '
                f'Phone: {self.phone}')


# Signal to create Profile when a new CustomUser is created
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

# Signal to save Profile when CustomUser is saved
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def save_user_profile(sender, instance, **kwargs):
    profile, _ = Profile.objects.get_or_create(user=instance)
    profile.save()