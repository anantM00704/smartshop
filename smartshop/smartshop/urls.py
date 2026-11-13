from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import path, include
from django.shortcuts import redirect


def healthz(request):
    """Liveness/readiness probe for Docker and the load balancer."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'db_unavailable'}, status=503)


urlpatterns = [
    path('healthz', healthz, name='healthz'),
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('users/', include('users.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('orders/', include('orders.urls')),
    path('cart/', include('orders.cart_urls')),
    path('', include('search.urls')),  # /search/ and /autocomplete/
    path('', lambda request: redirect('login')),  # Redirect root URL to the login page
]
