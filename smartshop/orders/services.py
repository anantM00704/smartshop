"""Cart and checkout rules. Views stay thin; everything here is enforced server-side."""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from products.models import Product

from .models import CartItem, Order, OrderItem


class CartError(Exception):
    """A user-facing problem with a cart action (message is safe to show)."""


@dataclass
class CartSummary:
    items: list = field(default_factory=list)
    subtotal: Decimal = Decimal('0')
    count: int = 0                 # total units
    unavailable: list = field(default_factory=list)   # items that can't be ordered right now


def cart_count(user):
    if not user.is_authenticated:
        return 0
    return CartItem.objects.filter(user=user).aggregate(n=Sum('quantity'))['n'] or 0


def get_cart(user):
    items = list(CartItem.objects.filter(user=user).select_related('product', 'product__category'))
    summary = CartSummary(items=items)
    for item in items:
        summary.count += item.quantity
        if item.product.price is None or not item.product.is_available:
            summary.unavailable.append(item)
        else:
            summary.subtotal += item.line_total
    return summary


def _clamp(quantity):
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise CartError('Invalid quantity.')
    if quantity < 1:
        raise CartError('Quantity must be at least 1.')
    return min(quantity, CartItem.MAX_QUANTITY)


@transaction.atomic
def add_to_cart(user, product_id, quantity=1):
    quantity = _clamp(quantity)
    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        raise CartError('Product not found.')
    if product.price is None or not product.is_available:
        raise CartError('This product is currently unavailable.')

    item = CartItem.objects.select_for_update().filter(user=user, product=product).first()
    if item:
        item.quantity = min(item.quantity + quantity, CartItem.MAX_QUANTITY)
        item.save(update_fields=['quantity'])
        return item
    if CartItem.objects.filter(user=user).count() >= CartItem.MAX_DISTINCT_ITEMS:
        raise CartError(f'Your cart can hold up to {CartItem.MAX_DISTINCT_ITEMS} different products.')
    return CartItem.objects.create(user=user, product=product, quantity=quantity)


def update_quantity(user, item_id, quantity):
    item = CartItem.objects.filter(user=user, pk=item_id).first()
    if item is None:
        raise CartError('That item is no longer in your cart.')
    item.quantity = _clamp(quantity)
    item.save(update_fields=['quantity'])
    return item


def remove_from_cart(user, item_id):
    deleted, _ = CartItem.objects.filter(user=user, pk=item_id).delete()
    if not deleted:
        raise CartError('That item is no longer in your cart.')


@transaction.atomic
def place_order(user, address):
    """Turn the user's cart into an order delivered to one of their saved addresses."""
    if address.user_id != user.pk:
        raise CartError('Please choose one of your saved addresses.')
    items = list(CartItem.objects.select_for_update().filter(user=user).select_related('product'))
    if not items:
        raise CartError('Your cart is empty.')
    unavailable = [i.product.name for i in items if i.product.price is None or not i.product.is_available]
    if unavailable:
        raise CartError('Remove unavailable items before placing the order: ' + ', '.join(unavailable[:3]))

    order = Order.objects.create(user=user, address=address.as_text(), status='Placed')
    total = Decimal('0')
    for item in items:
        line = OrderItem.objects.create(
            order=order, product=item.product, product_name=item.product.name,
            seller=item.product.source_site or '', unit_price=item.product.price, quantity=item.quantity)
        total += line.line_total
    order.total_amount = total
    order.save(update_fields=['total_amount'])
    CartItem.objects.filter(user=user).delete()
    return order