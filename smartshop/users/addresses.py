"""Saved-address rules: one default per user, first address becomes default, capped count."""
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Address


def addresses_for(user):
    return Address.objects.filter(user=user)


def default_address(user):
    return addresses_for(user).filter(is_default=True).first()


@transaction.atomic
def save_address(address, make_default=False):
    """Create or update an address, keeping exactly one default per user."""
    user_addresses = Address.objects.select_for_update().filter(user=address.user)
    if address.pk is None and user_addresses.count() >= Address.MAX_PER_USER:
        raise ValidationError(f'You can save up to {Address.MAX_PER_USER} addresses. Delete one to add another.')

    has_other_default = user_addresses.filter(is_default=True).exclude(pk=address.pk).exists()
    if make_default or not has_other_default:
        user_addresses.filter(is_default=True).exclude(pk=address.pk).update(is_default=False)
        address.is_default = True
    elif address.pk is None:
        address.is_default = False
    address.save()
    return address


@transaction.atomic
def set_default(address):
    Address.objects.select_for_update().filter(user=address.user, is_default=True) \
        .exclude(pk=address.pk).update(is_default=False)
    if not address.is_default:
        address.is_default = True
        address.save(update_fields=['is_default', 'updated_at'])


@transaction.atomic
def delete_address(address):
    was_default = address.is_default
    user = address.user
    address.delete()
    if was_default:
        replacement = Address.objects.select_for_update().filter(user=user).order_by('-updated_at').first()
        if replacement:
            replacement.is_default = True
            replacement.save(update_fields=['is_default', 'updated_at'])
