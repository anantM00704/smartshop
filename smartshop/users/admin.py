from django.contrib import admin

from .models import Address


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'label', 'full_name', 'city', 'pincode', 'is_default', 'updated_at')
    list_filter = ('label', 'is_default', 'state')
    search_fields = ('user__username', 'full_name', 'city', 'pincode')
