from .flipkart import FlipkartAffiliateAdapter

# Registry used by `manage.py scrape <source>`.
ADAPTERS = {
    FlipkartAffiliateAdapter.name: FlipkartAffiliateAdapter,
}
