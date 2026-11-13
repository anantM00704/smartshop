from users.addresses import default_address

from .services import cart_count


def shop(request):
    """Cart badge count and default address for the navbar."""
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return {'cart_count': 0, 'default_address': None}
    return {'cart_count': cart_count(user), 'default_address': default_address(user)}