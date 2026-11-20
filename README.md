# SmartShop: Multi-Seller Product Search & Price Comparison

[![CI](https://github.com/anantM00704/smartshop/actions/workflows/ci.yml/badge.svg)](https://github.com/anantM00704/smartshop/actions/workflows/ci.yml)

SmartShop is a Django e-commerce aggregator. It collects product listings from Indian marketplaces (Amazon, Flipkart, Nykaa) into one catalog. On top of that catalog it offers typo-tolerant search, personalised recommendations, a cart with saved addresses and order placement, and voice-assisted profile setup. Its data model supports price comparison across sellers (Skyscanner-style).

It started as an Information Retrieval course project. It is now being rebuilt into a production-grade, scalable platform: REST API, Next.js storefront, Redis/Kafka, semantic search, a support chatbot, AWS deployment and a mobile app.

---

## Project status at a glance

| Phase | Scope | Status |
|---|---|---|
| 0. Hygiene and security baseline | Secrets out of code, git history scrubbed, bug fixes, tests, Docker, CI | ✅ Done |
| 1. Data layer | PostgreSQL, multi-seller offers, price history, ingestion service | ✅ Done |
| 1b. Data sources | Polite scraping framework + Flipkart Affiliate API adapter | ✅ Done (awaiting live API keys) |
| 4a. Commerce (part) | Cart, saved addresses, checkout without payment, order snapshots | ✅ Done |
| — | Voice/text profile autofill (NLP) fix | ✅ Done |
| 2a. Security hardening | Login lockout, rate limiting, CAPTCHA, Argon2, OTP caps | 🚧 Next |
| 3. Caching and indexes | Redis cache-aside, sessions, shared rate limits, DB indexes | ⏳ Planned |
| 2b. IR search | BM25 full-text search, embeddings (pgvector), hybrid ranking, evaluation | ⏳ Planned |
| 5. Price comparison page | Cross-site product matching, offers side by side, price history | ⏳ Planned |
| 2c. REST API | DRF `/api/v1` with JWT (web + mobile) | ⏳ Planned |
| 4b. Payments and returns | Simulated payment gateway with signed webhooks, returns/refunds | ⏳ Planned |
| 6. Support chatbot | Claude-powered assistant: product discovery, order tracking, returns | ⏳ Planned |
| 7. UI redesign | Next.js + Tailwind storefront (quick-commerce/fashion style) | ⏳ Planned |
| 8. AWS deployment | Terraform, ECS Fargate, ALB, RDS, ElastiCache, MSK, S3 + CloudFront | ⏳ Planned |
| 9. Mobile app | React Native (Expo) on the same API | ⏳ Planned |

> **For resume or portfolio summaries:** describe only the ✅ rows and the "Engineering highlights" below as completed work. ⏳/🚧 items are planned and should be presented as roadmap or in-progress, not as shipped.

### Key numbers (verifiable in the repo)

- **108 automated tests** across 5 Django apps: users 40, scraping 26, products 16, search 13, orders 13. They run in CI against **PostgreSQL 16**.
- **342 products** in **8 categories** from **3 marketplaces**, shipped as a 1,034-record fixture (products, offers, price history, categories).
- **CI pipeline** (GitHub Actions): system check, missing-migration check, full test suite on Postgres, fixture load, Docker image build, and a container smoke test (health, login, search, static files).

---

## Engineering highlights

Each item lists the situation, what was done, and the outcome. These are written to be turned directly into STAR resume points.

### 1. Secured a codebase that had leaked credentials
- **Situation:** the original public repository had a Gmail SMTP app password and the Django `SECRET_KEY` hardcoded in settings. It also had the SQLite database (user hashes, OTPs) and compiled files committed.
- **Action:** moved all configuration to environment variables (`.env` + python-dotenv), with fail-fast checks when debug is off. Rewrote git history with `git-filter-repo` to remove the secrets, the database and the compiled files, then migrated the project to a new private repository. Added `.gitignore`, `.env.example` and production hardening (proxy SSL header, secure cookies, HSTS switches).
- **Result:** zero secrets in the migrated history (verified by searching every commit for the leaked values). The app now runs on newly issued credentials kept only in `.env`, and the old repository was left untouched.

### 2. Hardened account recovery against abuse
- **Situation:** the mobile password reset only *printed* the OTP to the server console, so users never received it. Codes came from a non-cryptographic RNG with no attempt limit, the email-link reset pages were missing (the flow crashed), and signup crashed on a missing import.
- **Action:**
  - Built OTP delivery by email, with optional SMS through the Twilio REST API.
  - Generated codes with `secrets` and compared them in constant time.
  - Made codes single-use with a 5-minute expiry, a 5-attempt lockout and a 60-second resend cooldown.
  - Added a "forgot username" flow that doesn't reveal which accounts exist.
  - Built the missing email-link reset pages.
- **Result:** all recovery paths work end to end and are covered by tests: delivery, expiry, lockout, cooldown, weak-password rejection and the enumeration-safe responses.

### 3. Designed a multi-seller catalog for price comparison
- **Situation:** each product row was one seller's listing, identified by `(name, category)`. The same item from two sites overwrote itself, and there was no price history. Imported CSVs stored empty cells as the text "nan".
- **Action:**
  - Introduced **Product → Offer (per seller) → PricePoint (append-only history)**.
  - Built a single ingestion service used by every source. It cleans prices, ratings and NaN cells.
  - It canonicalises URLs: Amazon becomes `/dp/<ASIN>`, and Flipkart keeps only `pid`.
  - It never matches on empty URLs, records a price point only when price or stock changes, and keeps `Product.price` equal to the best in-stock offer.
- **Result:** a data migration backfilled 342 offers and 342 price points with no data loss. CSV, JSON and API imports all share one tested code path (16 tests).

### 4. Built a polite, block-aware scraping framework
- **Situation:** the project needed fresh prices from marketplaces without getting blocked or breaching terms of use.
- **Action:**
  - Wrote a `PoliteClient` with per-host rate limits and daily quotas.
  - It retries with exponential backoff and jitter, honours `Retry-After` (refusing waits over 60 s), and respects robots.txt for HTML sources.
  - A **circuit breaker** pauses a host for 6 h on a 403 or CAPTCHA page instead of evading it, and a 401 is reported as bad credentials.
  - Responses are cached with ETag revalidation, and requests carry an honest User-Agent.
  - Added a pluggable adapter interface and a **Flipkart Affiliate API** adapter written from the official docs.
  - Every run is logged in a `ScrapeRun` table.
- **Result:** 26 deterministic tests using a fake HTTP transport and a fake clock run in under 1 second. The state lives in Django's cache, so it becomes shared across workers once the cache points at Redis.

### 5. Containerised the app and automated quality gates
- **Situation:** there was no `requirements.txt`, Dockerfile, CI or real test suite, and the README described features that didn't exist.
- **Action:**
  - Wrote a Docker image (Python 3.12-slim, gunicorn, WhiteNoise, non-root user, health check).
  - Its entrypoint migrates and seeds the catalog into an empty database.
  - docker-compose runs the app with PostgreSQL 16.
  - Added a `/healthz` endpoint for load balancers.
  - Set up GitHub Actions to run tests on Postgres plus a Docker smoke test.
- **Result:** `docker compose up` brings up a working stack from a fresh clone, and every push is verified automatically.

### 6. Cart, saved addresses and checkout
- **Situation:** users had to type a delivery address into every product card, and an order could hold only one product.
- **Action:**
  - Added a cart (quantity 1–10, live prices) and saved addresses (up to 20 per user). A database partial unique constraint guarantees exactly one default address.
  - Checkout shows 5 addresses with "View all".
  - Orders now have `OrderItem`s whose product name, seller and price are frozen at checkout, plus a snapshot of the address.
  - Ownership is checked on every operation, and redirects only go to same-site URLs.
- **Result:** a migration converted the 10 existing single-product orders with no data loss. 26 new tests cover carts, addresses, checkout and access control.

### 7. Fixed search, recommendations and the voice NLP
- **Search:** results used to come from a fuzzy filter on names (`name__in`) with no ranking. It now ranks exact matches first, then typo-tolerant fuzzy matches, using product IDs, with pagination, price sorting and debounced autocomplete.
- **Recommendations:** the dashboard sections were always empty (a template/view variable mismatch). They now use the user's search history.
- **Voice NLP:** the rule-based parser that turns speech transcripts into profile fields read "175 cm" as metres and ages as heights. It was rewritten to handle number words ("five feet eight"), feet+inches, Indian decimal feet, cm/m/kg/lbs and context-aware ages, with regression tests for each case.

---

## Features (current)

- **Catalog and search:** 342 products, relevance-ranked typo-tolerant search, category browsing, price filter and sort, pagination, navbar autocomplete.
- **Personalised dashboard:** "Pick Up Where You Left Off", "Categories to Explore" and "Top Picks" from search history.
- **Cart and checkout:** add to cart / buy now, quantities, saved addresses, place order (payment not enabled yet), order history with frozen prices.
- **Profile:** voice/text autofill (Web Speech API + NLP), preferences, saved-address management, and "Deliver to" showing the default address.
- **Accounts:** sign-up, login, password reset by email link or OTP (email/SMS), and username recovery.
- **Data:** ingestion from CSV/JSON/APIs, multi-seller offers, price history, and the polite scraping framework.

## Architecture

**Today:** Django monolith (server-rendered) → PostgreSQL 16, packaged with Docker and verified by CI.

**Target:**
```
Clients: Next.js web (SSR)  ·  React Native app
        │  CloudFront CDN (static assets, images)
        ▼
   AWS ALB (HTTPS, WAF rate rules)
        ├── /api/*   → ECS Fargate: Django + DRF (stateless, autoscaled)
        ├── /chat/*  → ECS Fargate: chatbot service (Claude tool use)
        └── /*       → ECS Fargate: Next.js
Django → RDS PostgreSQL (+ read replica, pgvector)
       → ElastiCache Redis (cache, sessions, carts, rate limits)
       → Kafka / MSK (product.scraped, order.created, payment.events, search.events)
Workers: scrapers, ingestion consumer, notifications (SES)  ·  S3 for images
```

## Tech stack

| Layer | Now | Planned |
|---|---|---|
| Backend | Django 5.0, server-rendered templates | Django REST Framework, JWT |
| Frontend | Bootstrap 5, vanilla JS | Next.js + Tailwind; React Native (Expo) |
| Database | PostgreSQL 16 (SQLite for quick local runs) | Amazon RDS + read replica, pgvector |
| Search | Exact + fuzzy (fuzzywuzzy) ranking | Postgres full-text (BM25-style) + embeddings, hybrid ranking |
| Data ingestion | Ingestion service, httpx PoliteClient, Flipkart Affiliate API | More affiliate APIs, scheduled runs, Kafka |
| Caching / queues | (none) | Redis, Kafka (MSK) |
| Serving | gunicorn + WhiteNoise in Docker | ECS Fargate behind ALB, CloudFront |
| CI/CD | GitHub Actions: tests on Postgres + Docker smoke test | Deploy to AWS (blue/green), pip-audit |

---

## Roadmap (detailed)

### Phase 2a: Security hardening (next)
- **Brute force and credential stuffing:** lock accounts after repeated login failures per username and IP (django-axes), with a CAPTCHA (Cloudflare Turnstile) after repeated failures.
- **Request flooding:** per-IP and per-user **rate limits** on login, sign-up, password reset, search and cart actions, stored in Redis. On AWS, add WAF rate-based rules and AWS Shield Standard.
- **OTP bombing and SMS pumping:** per-IP and per-number daily caps on top of the existing cooldown and attempt limits.
- **Password storage:** switch to **Argon2** as the primary hasher. Existing PBKDF2 hashes (720,000 iterations) are upgraded on the user's next login.
- **Other:** security headers (CSP, HSTS), `pip-audit` and Dependabot in CI, admin 2FA.

### Phase 3: Caching, indexes and events
- **Redis cache-aside:** product pages, search results, autocomplete, homepage recommendations and the cart badge. Entries expire on a TTL and are invalidated by ingestion.
- **Sessions and limits:** sessions in Redis, and shared rate-limit and scraper state.
- **Fewer writes:** search history and view counters are buffered in Redis and batch-written, instead of one database write per request.
- **Indexes:** GIN trigram on product name, GIN full-text index, `(category, price)`, `(user, searched_at)`, and HNSW for vectors. Each is verified with `EXPLAIN ANALYZE`.
- **Events:** Kafka topics (`product.scraped`, `order.created`, `search.events`) with an outbox pattern. Load-test with k6 and track p95 latency and cache hit rate.

### Phase 2b: Information-retrieval search and recommendations
- **Lexical:** Postgres full-text search with BM25-style ranking. This fixes category-name over-matching ("iphone" returning all phones).
- **Semantic:** sentence embeddings (`all-MiniLM-L6-v2`, 384 dimensions) stored in **pgvector**, with **cosine similarity** (equivalent to Euclidean distance on normalised vectors).
- **Hybrid ranking:** BM25 and vector results combined with **Reciprocal Rank Fusion**.
- **Uses:** cross-site product matching for price comparison, "similar products", and homepage "Recommended for you" (nearest neighbours to the user's taste vector) plus trending items.
- **Evaluation:** precision@k, recall@k, nDCG and MRR on a labelled query set.

### Phase 5: Price comparison page
Product detail page with every seller's offer side by side (cheapest first), MRP and discount, a price-history chart, and "price dropped" and "lowest in 30 days" badges.

### Phase 2c: REST API
DRF `/api/v1` with JWT for products, search, cart, checkout, orders, addresses and recommendations. OpenAPI docs via drf-spectacular. Shared by the web app and the mobile app.

### Phase 4b: Payments, returns and refunds
- **Payments:** a mock payment gateway with HMAC-signed webhooks, timestamp tolerance, idempotency keys and replay protection.
- **Order lifecycle:** an order state machine (placed → paid → shipped → delivered → return requested → refunded).
- **Later:** swap in Razorpay or Stripe test mode with the same webhook handler.

### Phase 6: Support chatbot
- **Tools:** a Claude API assistant with `search_products`, `track_order`, `create_return_request`, `refund_status` and FAQ lookup over chunked and embedded policy documents (RAG).
- **Safety:** every call is authorised with the user's JWT, conversation memory is kept in Redis, responses stream, and the bot asks for confirmation before any action.

### Phase 7: UI redesign
Next.js (App Router) + TypeScript + Tailwind, mobile-first. Category rails, filter drawer, product gallery, cart drawer, skeleton loaders, and SEO via server-side rendering.

### Phase 8: AWS deployment
Terraform: VPC, ALB + ACM TLS, ECS Fargate services with autoscaling, RDS Multi-AZ, ElastiCache, MSK, S3 + CloudFront, Secrets Manager, Route 53, WAF and CloudWatch alarms. CI/CD deploys blue/green to ECS, with migrations run as a one-off task.

### Phase 9: Mobile app
React Native (Expo) on the `/api/v1` JWT API, with push notifications driven by order events.

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
| `DATABASE_URL` | Optional Postgres URL (SQLite otherwise) |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Gmail address and [App Password](https://myaccount.google.com/apppasswords). Without them, emails are printed to the console |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Optional SMS delivery for reset codes |
| `FLIPKART_AFFILIATE_ID`, `FLIPKART_AFFILIATE_TOKEN` | Flipkart Affiliate API credentials for the scraper |

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
    ├── products/          Product / Offer / PricePoint, ingestion service, import commands, fixture
    ├── scraping/          PoliteClient, adapter interface, Flipkart adapter, pipeline, `scrape` command
    ├── search/            ranked search + autocomplete
    ├── dashboard/         personalised dashboard
    ├── recommendation/    search/view history models
    ├── orders/            cart, checkout services, orders and order items
    ├── users/             custom user, profile, saved addresses, OTP/email recovery, voice NLP
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

# JSON list of listings (what scrapers and API clients produce)
python manage.py ingest_listings listings.json
```

Each `ingest_listings` item has `name`, `seller`, `url` and `price`, plus optional `mrp`, `in_stock`, `image_url`, `rating`, `delivery_date`, `category` and `main_category`.

## Data sources (scraping framework)

All external fetching goes through `scraping/http.py` (`PoliteClient`), which enforces these rules per host:

| Rule | Behaviour |
|---|---|
| Rate limit | Minimum gap between requests (Flipkart API: 1 s, about 5% of the documented 20 req/s) and a daily quota |
| Retries | 429/5xx/network errors are retried with exponential backoff and jitter, honouring `Retry-After`. It gives up rather than waiting more than 60 s |
| robots.txt | Always honoured for HTML sources. Official APIs are governed by their API terms instead |
| Circuit breaker | A 403 or a CAPTCHA/block page pauses that host for 6 h. **We never try to get around a block** |
| Caching | GET responses are cached (30 min) and revalidated with ETags |
| Identity | Honest `User-Agent` (`SCRAPER_USER_AGENT`). No browser impersonation |

We store only facts (name, price, MRP, stock, link) and always link back to the seller. Preferred sources are official affiliate APIs. Scraping Amazon's HTML is deliberately avoided.

| Source | Type | Status |
|---|---|---|
| Flipkart Affiliate API | Official API | Ready. Needs `FLIPKART_AFFILIATE_ID` and `FLIPKART_AFFILIATE_TOKEN` from [affiliate.flipkart.com](https://affiliate.flipkart.com) |
| Amazon PA-API, affiliate networks (Nykaa/Myntra) | Official APIs | Planned |

```powershell
python manage.py scrape flipkart -q "iphone 15" --dry-run          # preview, saves nothing
python manage.py scrape flipkart -q "iphone 15" -q "galaxy s24" --category "Mobile Phones" --main-category Electronics
```

Every run is logged as a `ScrapeRun` (fetched, new products/offers, price changes, errors), visible in `/admin`.

---

## Screenshots

These are from the original course-project version. Updated screenshots will follow the UI redesign.

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
