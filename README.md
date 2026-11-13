# SmartShop: Product Search & Recommendations

[![CI](https://github.com/anantM00704/smartshop/actions/workflows/ci.yml/badge.svg)](https://github.com/anantM00704/smartshop/actions/workflows/ci.yml)

SmartShop is a Django e-commerce aggregator: it brings product listings collected from Amazon, Flipkart and Nykaa into one catalog, with typo-tolerant search, personalised recommendations, voice-assisted profile setup and simple order placement.

> This is the actively developed continuation of the original course project. See the [Roadmap](#roadmap) for what's being built next (REST API, Next.js storefront, Redis/Kafka, chatbot, AWS deployment, mobile app).

---

## Features

- **Product catalog:** 342 products across 8 categories (mobiles, earphones, shirts, tops, lipsticks) gathered from Amazon, Flipkart and Nykaa, shipped as a fixture (`products/fixtures/catalog.json`).
- **Search:** exact matches first, then fuzzy (typo-tolerant) matches; queries that name a category browse that category. Price filter, price sorting and pagination.
- **Autocomplete:** debounced suggestions in the navbar on every page.
- **Personalised dashboard:** "Pick Up Where You Left Off" (from your recent searches), "Categories to Explore" and "Top Picks".
- **Voice/text profile input:** describe yourself ("men, 175 cm, 70 kg, slim fit") and the profile form fills itself (Web Speech API + rule-based NLP).
- **Location awareness:** "Deliver to" label from browser geolocation.
- **Orders:** place an order from a product card and view it under *Your Orders*.
- **Accounts and recovery:**
  - Password reset via email link or a 6-digit code (sent to the account email, and by SMS when Twilio is configured).
  - Codes are single use and expire after 5 minutes, with a 60 s resend cooldown and a limit of 5 attempts.
  - "Forgot username" emails the username, and reset emails include it too.

## Tech stack

| Layer | Now | Planned |
|---|---|---|
| Backend | Django 5.0 (server-rendered templates) | Django REST Framework API |
| Frontend | Bootstrap 5, vanilla JS | Next.js + Tailwind, React Native app |
| Database | PostgreSQL 16 in Docker (SQLite for quick local runs) | Amazon RDS |
| Search | Substring + fuzzywuzzy ranking | Postgres full-text / OpenSearch |
| Serving | gunicorn + WhiteNoise in Docker | ECS Fargate behind an ALB, CloudFront CDN |
| CI | GitHub Actions (tests + Docker smoke test) | + deploy to AWS |

---

## Getting started

### Option A: Local Python (Windows PowerShell)

```powershell
git clone https://github.com/anantM00704/smartshop.git
cd smartshop
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                 # then edit .env (see below)

cd smartshop
python manage.py migrate
python manage.py loaddata catalog      # load the product catalog
python manage.py createsuperuser       # optional, for /admin
python manage.py runserver
```

Open http://127.0.0.1:8000/.

### Option B: Docker

```powershell
copy .env.example .env    # set DJANGO_SECRET_KEY at minimum
docker compose up --build
```

This starts two containers: **PostgreSQL 16** (`db`) and the Django app (`web`). Open http://localhost:8000/. The app runs migrations and loads the catalog on first start. Data lives in the `pg_data` volume, and `docker compose down -v` resets it. You can check health at http://localhost:8000/healthz.

Without Docker, the app uses SQLite. Set `DATABASE_URL` (for example `postgres://smartshop:smartshop-local-only@localhost:5432/smartshop` with `docker compose up -d db`) to use Postgres instead.

### Configuration (`.env`)

`.env` is git-ignored. Never commit real credentials.

| Variable | Purpose |
|---|---|
| `DJANGO_DEBUG` | `true` for local development |
| `DJANGO_SECRET_KEY` | Required when debug is off |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Gmail address and [App Password](https://myaccount.google.com/apppasswords). Without them, emails are printed to the console |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Optional SMS delivery for reset codes |

### Tests

```powershell
cd smartshop
python manage.py test
```

---

## Project structure

```
smartshop/                 repo root
├── Dockerfile, docker-compose.yml, docker/entrypoint.sh
├── .github/workflows/ci.yml
├── requirements.txt, .env.example
└── smartshop/             Django project (run manage.py from here)
    ├── smartshop/         settings, root URLs (incl. /healthz), WSGI
    ├── products/          Category & Product models, import_csv command, catalog fixture
    ├── search/            search results + autocomplete
    ├── dashboard/         personalised dashboard
    ├── recommendation/    search/view history models
    ├── orders/            order placement and listing
    ├── users/             custom user, profile, OTP/email recovery, voice NLP
    ├── templates/         base layout, search page, product card partial
    └── static/            CSS, JS, images
```

## Catalog data model and ingestion

- **Product:** the canonical item. `price` always holds the cheapest in-stock offer, falling back to the last known price.
- **Offer:** one seller's listing of a product (Amazon, Flipkart, Nykaa and so on), with price, MRP, stock and URL. One product can have many offers, which enables price comparison.
- **PricePoint:** append-only price history. A row is written only when price or stock changes.

Everything enters through one service, `products/ingestion.py` (`ingest_listing`). It cleans values (`₹1,299`, `NaN`, `4.2 out of 5 stars`), strips tracking parameters from URLs (Amazon becomes `/dp/<ASIN>`, and for Flipkart only `pid` is kept), matches an existing offer or product, and records price changes.

```powershell
# Scraped CSV exports (column mappings for the original Amazon/Flipkart/Nykaa files)
python manage.py import_csv path\to\shirts_amazon.csv --main_category "Men's Fashion" --sub_category Shirts

# JSON list of listings (what scrapers and API clients will produce)
python manage.py ingest_listings listings.json
```

Each `ingest_listings` item has `name`, `seller`, `url` and `price`, plus optional `mrp`, `in_stock`, `image_url`, `rating`, `delivery_date`, `category` and `main_category`.

Scrapers (official affiliate APIs plus Playwright, scheduled and feeding Kafka) are next. See the roadmap.

---

## Roadmap

0. **Hygiene:** secrets out of code, bug fixes, tests, Docker, CI. ✅
1. **Data layer:** PostgreSQL, multi-seller offers and price history, ingestion pipeline (affiliate APIs + Playwright), product images to S3.
2. **API and search:** DRF `/api/v1` with JWT, Postgres full-text search, Redis-backed autocomplete.
3. **Scale:** Redis caching, sessions and rate limits; Kafka events; CloudFront CDN; load testing.
4. **Commerce:** cart, checkout, simulated payment gateway with signed webhooks, returns and refunds.
5. **Support chatbot:** Claude-powered assistant for product discovery, order tracking and returns.
6. **UI redesign:** Next.js storefront in the style of modern quick-commerce and fashion apps.
7. **AWS:** Terraform, ECS Fargate, ALB, RDS, ElastiCache, MSK, S3 + CloudFront, CI/CD.
8. **Mobile app:** React Native (Expo) on the same API.

---

## Screenshots

1. Dashboard
   ![Dashboard homepage](https://github.com/user-attachments/assets/e44816db-bd96-490a-afd5-84629d4539b5)
2. Profile
   ![Profile](https://github.com/user-attachments/assets/a745bbda-13f1-4b1e-a529-60676d3de165)
3. Categories
   ![Categories section](https://github.com/user-attachments/assets/6fb1a24e-69f3-4d69-9ac7-82c4cd510540)
4. Orders
   ![Orders section](https://github.com/user-attachments/assets/236726cc-ce9e-44a1-acb8-b448067441f9)

## Authors

- Anant Malhotra
