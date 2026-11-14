from django.contrib import admin

from .models import ScrapeRun


@admin.register(ScrapeRun)
class ScrapeRunAdmin(admin.ModelAdmin):
    list_display = ('started_at', 'source', 'query', 'status', 'fetched',
                    'products_created', 'offers_created', 'price_changes', 'skipped')
    list_filter = ('source', 'status')
    search_fields = ('query', 'error')
    readonly_fields = [f.name for f in ScrapeRun._meta.fields]
