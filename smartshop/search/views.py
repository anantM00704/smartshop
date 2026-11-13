from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Q, When
from django.http import JsonResponse
from django.shortcuts import render
from fuzzywuzzy import fuzz, process

from products.models import Category, Product
from recommendation.models import SearchHistory

PAGE_SIZE = 24
CATEGORY_MATCH_THRESHOLD = 80
PRODUCT_MATCH_THRESHOLD = 70
MAX_FUZZY_RESULTS = 60


def _filter_by_category(products, category):
    if category.subcategories.exists():
        return products.filter(category__in=category.subcategories.all())
    return products.filter(category=category)


def _parse_price(value):
    try:
        return float(value) if value not in (None, '') else None
    except ValueError:
        return None


def _ranked_text_search(products, query):
    """Exact substring matches first, then fuzzy matches; preserves relevance order."""
    exact_ids = list(products.filter(name__icontains=query).values_list('id', flat=True)[:MAX_FUZZY_RESULTS])
    fuzzy_ids = []
    if len(exact_ids) < MAX_FUZZY_RESULTS:
        choices = dict(products.exclude(id__in=exact_ids).values_list('id', 'name'))
        matches = process.extract(query, choices, limit=MAX_FUZZY_RESULTS - len(exact_ids), scorer=fuzz.partial_ratio)
        fuzzy_ids = [pk for _name, score, pk in matches if score > PRODUCT_MATCH_THRESHOLD]
    ranked = exact_ids + fuzzy_ids
    if not ranked:
        return products.none()
    order = Case(*[When(id=pk, then=pos) for pos, pk in enumerate(ranked)], output_field=IntegerField())
    return products.filter(id__in=ranked).order_by(order)


def search_results(request):
    query = request.GET.get('q', '').strip()
    category_name = request.GET.get('category', '').strip()
    min_price = _parse_price(request.GET.get('min_price'))
    max_price = _parse_price(request.GET.get('max_price'))
    sort = request.GET.get('sort', '')
    page_number = request.GET.get('page', 1)

    products = Product.objects.select_related('category')

    # Record the search once (not on every pagination click).
    if request.user.is_authenticated and query and str(page_number) == '1':
        SearchHistory.objects.create(user=request.user, query=query[:255])

    if query:
        category_names = list(Category.objects.values_list('name', flat=True))
        match = process.extractOne(query, category_names, scorer=fuzz.partial_ratio) if category_names else None
        matched_category = (
            Category.objects.filter(name=match[0]).first()
            if match and match[1] > CATEGORY_MATCH_THRESHOLD else None
        )
        if matched_category:
            products = _filter_by_category(products, matched_category)
        else:
            products = _ranked_text_search(products, query)

    if category_name:
        category = Category.objects.filter(name=category_name).first()
        if category:
            products = _filter_by_category(products, category)

    if min_price is not None:
        products = products.filter(price__gte=min_price)
    if max_price is not None:
        products = products.filter(price__lte=max_price)

    if sort == 'price_asc':
        products = products.order_by('price')
    elif sort == 'price_desc':
        products = products.order_by('-price')
    elif not products.ordered:
        products = products.order_by('id')  # stable order for pagination

    page = Paginator(products, PAGE_SIZE).get_page(page_number)

    # Query string without `page`, for pagination links.
    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'search/search_results.html', {
        'products': page.object_list,
        'page': page,
        'count': page.paginator.count,
        'categories': Category.objects.filter(parent__isnull=True).prefetch_related('subcategories'),
        'query': query,
        'category_name': category_name,
        'min_price': '' if min_price is None else f"{min_price:g}",
        'max_price': '' if max_price is None else f"{max_price:g}",
        'sort': sort,
        'querystring': params.urlencode(),
    })


def autocomplete(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'suggestions': []})

    suggestions = list(
        Category.objects.filter(name__icontains=query).values_list('name', flat=True)[:3]
    )
    suggestions += list(
        Product.objects.filter(Q(name__istartswith=query) | Q(name__icontains=f" {query}"))
        .values_list('name', flat=True)[:10 - len(suggestions)]
    )
    if len(suggestions) < 5:
        names = list(Product.objects.values_list('name', flat=True))
        for name, score in process.extract(query, names, limit=10, scorer=fuzz.partial_ratio):
            if score > PRODUCT_MATCH_THRESHOLD and name not in suggestions:
                suggestions.append(name)
            if len(suggestions) >= 10:
                break
    return JsonResponse({'suggestions': suggestions})
