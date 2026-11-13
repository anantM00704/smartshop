from django.db import models

class Category(models.Model):
    name = models.CharField(max_length=255)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subcategories')

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Categories'

class Product(models.Model):
    name = models.CharField(max_length=500)
    product_url = models.URLField(max_length=2000)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_url = models.URLField(max_length=2000, blank=True)
    delivery_date = models.CharField(max_length=100, blank=True, null=True)
    image_url = models.URLField(max_length=2000, blank=True)
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, related_name='products')
    rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    source_site = models.CharField(max_length=100, default="Unknown")
    reviews = models.TextField(blank=True, null=True)
    is_available = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Offer(models.Model):
    """One seller's listing of a product (the same product can have many offers)."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='offers')
    seller = models.CharField(max_length=100)
    url = models.URLField(max_length=2000)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    mrp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    in_stock = models.BooleanField(default=True)
    delivery_date = models.CharField(max_length=100, blank=True, default='')
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['product', 'seller'], name='uniq_offer_product_seller'),
        ]
        indexes = [models.Index(fields=['price'])]

    def __str__(self):
        return f"{self.product_id} @ {self.seller}"


class PricePoint(models.Model):
    """Append-only price history; a row is written only when price or stock changes."""
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='price_history')
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    in_stock = models.BooleanField(default=True)
    recorded_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-recorded_at']
