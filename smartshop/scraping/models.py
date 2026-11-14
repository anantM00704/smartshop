from django.db import models


class ScrapeRun(models.Model):
    """One execution of an adapter for a query: what was fetched and what changed."""
    STATUS_CHOICES = [('running', 'Running'), ('ok', 'OK'), ('partial', 'Partial'), ('failed', 'Failed')]

    source = models.CharField(max_length=50)
    query = models.CharField(max_length=255)
    category = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')
    fetched = models.PositiveIntegerField(default=0)
    products_created = models.PositiveIntegerField(default=0)
    offers_created = models.PositiveIntegerField(default=0)
    price_changes = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [models.Index(fields=['source', '-started_at'])]

    def __str__(self):
        return f'{self.source} "{self.query}" ({self.status})'
