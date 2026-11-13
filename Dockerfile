# SmartShop Django app (gunicorn + WhiteNoise)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SQLITE_PATH=/data/db.sqlite3

WORKDIR /app

# Dependencies first for better layer caching
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY smartshop/ .
COPY docker/entrypoint.sh /entrypoint.sh

# Static files are collected at build time (a throwaway key is fine here)
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /data && chown -R app:app /app /data

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "smartshop.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
