from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render

from products.models import Category, Product
from recommendation.models import SearchHistory

MAX_RECENT_PRODUCTS = 6
MAX_RECOMMENDED_PRODUCTS = 6


def _products_matching(queries, limit):
    """Products whose name or category contains any of the given search queries."""
    condition = Q()
    for q in queries:
        condition |= Q(name__icontains=q) | Q(category__name__icontains=q)
    if not condition:
        return Product.objects.none()
    return Product.objects.filter(condition).select_related('category').distinct()[:limit]


@login_required
def dashboard(request):
    history = SearchHistory.objects.filter(user=request.user)

    # Distinct recent queries, newest first.
    recent_queries = []
    for q in history.order_by('-searched_at').values_list('query', flat=True)[:50]:
        if q.lower() not in (r.lower() for r in recent_queries):
            recent_queries.append(q)
        if len(recent_queries) == 5:
            break

    pick_up_products = list(_products_matching(recent_queries, MAX_RECENT_PRODUCTS))

    # Categories the user engaged with, most frequent first; fall back to the largest categories.
    category_ids = [p.category_id for p in pick_up_products if p.category_id]
    categories_to_explore = list(
        Category.objects.filter(id__in=category_ids).annotate(n=Count('products')).order_by('-n')[:6]
    ) or list(
        Category.objects.filter(parent__isnull=False).annotate(n=Count('products')).order_by('-n')[:6]
    )

    recommended_products = list(
        Product.objects.filter(category__in=categories_to_explore, price__isnull=False)
        .exclude(id__in=[p.id for p in pick_up_products])
        .select_related('category')
        .order_by('?')[:MAX_RECOMMENDED_PRODUCTS]
    )

    return render(request, 'dashboard/dashboard.html', {
        'pick_up_products': pick_up_products,
        'categories_to_explore': categories_to_explore,
        'recommended_products': recommended_products,
        'recent_queries': recent_queries,
    })
