#!/bin/sh
set -e

# Run migrations on start unless disabled (on AWS we run them as a one-off task instead).
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    python manage.py migrate --noinput
fi

# Seed the product catalog into an empty database.
if [ "${LOAD_CATALOG:-true}" = "true" ]; then
    if [ "$(python manage.py shell -c 'from products.models import Product; print(Product.objects.exists())')" = "False" ]; then
        echo "Empty catalog: loading products fixture"
        python manage.py loaddata catalog
    fi
fi

exec "$@"
