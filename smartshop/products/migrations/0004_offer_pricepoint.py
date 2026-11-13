import django.db.models.deletion
from django.db import migrations, models


def backfill_offers(apps, schema_editor):
    """Give every existing product one offer plus its first price-history row."""
    Product = apps.get_model('products', 'Product')
    Offer = apps.get_model('products', 'Offer')
    PricePoint = apps.get_model('products', 'PricePoint')
    for product in Product.objects.all().iterator():
        offer = Offer.objects.create(
            product=product, seller=product.source_site or 'Unknown',
            url=product.product_url, price=product.price,
            in_stock=product.is_available, delivery_date=product.delivery_date or '')
        PricePoint.objects.create(offer=offer, price=product.price, in_stock=product.is_available)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0003_product_reviews_alter_product_delivery_date_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Offer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('seller', models.CharField(max_length=100)),
                ('url', models.URLField(max_length=2000)),
                ('price', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('mrp', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('in_stock', models.BooleanField(default=True)),
                ('delivery_date', models.CharField(blank=True, default='', max_length=100)),
                ('last_seen', models.DateTimeField(auto_now=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='offers', to='products.product')),
            ],
        ),
        migrations.CreateModel(
            name='PricePoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('price', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('in_stock', models.BooleanField(default=True)),
                ('recorded_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('offer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='price_history', to='products.offer')),
            ],
            options={'ordering': ['-recorded_at']},
        ),
        migrations.AddConstraint(
            model_name='offer',
            constraint=models.UniqueConstraint(fields=('product', 'seller'), name='uniq_offer_product_seller'),
        ),
        migrations.AddIndex(
            model_name='offer',
            index=models.Index(fields=['price'], name='products_of_price_8206fc_idx'),
        ),
        migrations.RunPython(backfill_offers, migrations.RunPython.noop),
    ]
