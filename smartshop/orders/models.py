from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from products.models import Product


class CartItem(models.Model):
    """One product in a user's cart. Prices are read live from the product until checkout."""
    MAX_QUANTITY = 10
    MAX_DISTINCT_ITEMS = 50

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(MAX_QUANTITY)])
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'product'], name='uniq_cart_user_product'),
        ]

    def __str__(self):
        return f'{self.quantity} x {self.product}'

    @property
    def line_total(self):
        return (self.product.price or Decimal('0')) * self.quantity


class Order(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    address = models.TextField(help_text='Delivery address as it was when the order was placed')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField(max_length=20, default='Placed')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Order #{self.id}'


class OrderItem(models.Model):
    """A product line on an order, with name and price frozen at checkout."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=500)
    seller = models.CharField(max_length=100, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveSmallIntegerField(default=1)

    def __str__(self):
        return f'{self.quantity} x {self.product_name}'

    @property
    def line_total(self):
        return self.unit_price * self.quantity
