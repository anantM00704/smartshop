from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from users.addresses import addresses_for
from users.models import Address

from . import services
from .models import Order


def _safe_next(request, fallback):
    target = request.POST.get('next') or request.GET.get('next')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return target
    return fallback


@login_required
def cart(request):
    summary = services.get_cart(request.user)
    addresses = addresses_for(request.user)
    return render(request, 'orders/cart.html', {
        'cart': summary,
        'addresses': addresses[:Address.CHECKOUT_LIMIT],
        'address_total': addresses.count(),
        'checkout_limit': Address.CHECKOUT_LIMIT,
    })


@login_required
@require_POST
def cart_add(request):
    try:
        item = services.add_to_cart(request.user, request.POST.get('product_id'), request.POST.get('quantity', 1))
        messages.success(request, f'Added “{item.product.name[:60]}” to your cart.')
    except services.CartError as exc:
        messages.error(request, str(exc))
        return redirect(_safe_next(request, 'search_results'))
    if request.POST.get('buy_now'):
        return redirect('cart')
    return redirect(_safe_next(request, 'cart'))


@login_required
@require_POST
def cart_update(request, item_id):
    try:
        services.update_quantity(request.user, item_id, request.POST.get('quantity'))
    except services.CartError as exc:
        messages.error(request, str(exc))
    return redirect('cart')


@login_required
@require_POST
def cart_remove(request, item_id):
    try:
        services.remove_from_cart(request.user, item_id)
        messages.info(request, 'Item removed from your cart.')
    except services.CartError as exc:
        messages.error(request, str(exc))
    return redirect('cart')


@login_required
@require_POST
def checkout(request):
    address = get_object_or_404(Address, pk=request.POST.get('address_id') or 0, user=request.user)
    try:
        order = services.place_order(request.user, address)
    except services.CartError as exc:
        messages.error(request, str(exc))
        return redirect('cart')
    messages.success(request, f'Order #{order.id} placed! It will be delivered to {address.full_name}, {address.city}.')
    return redirect('orders')


@login_required
def orders(request):
    user_orders = Order.objects.filter(user=request.user).prefetch_related('items')
    return render(request, 'orders/orders.html', {'orders': user_orders})