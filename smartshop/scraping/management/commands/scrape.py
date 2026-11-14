from django.core.management.base import BaseCommand, CommandError

from scraping.adapters import ADAPTERS
from scraping.exceptions import ScrapeError
from scraping.pipeline import run_query


class Command(BaseCommand):
    help = ('Fetch listings from a data source and ingest them. Example:\n'
            '  manage.py scrape flipkart --query "iphone 15" --query "galaxy s24" '
            '--category "Mobile Phones" --main-category Electronics')

    def add_arguments(self, parser):
        parser.add_argument('source', choices=sorted(ADAPTERS))
        parser.add_argument('--query', '-q', action='append', required=True,
                            help='Search query (repeat for several)')
        parser.add_argument('--category', default='', help='Sub-category to file products under')
        parser.add_argument('--main-category', default='', help='Parent category (used if the sub-category is new)')
        parser.add_argument('--limit', type=int, default=10, help='Results per query (source maximum applies)')
        parser.add_argument('--dry-run', action='store_true', help='Fetch and print, but save nothing')

    def handle(self, *args, **opts):
        adapter = ADAPTERS[opts['source']]()
        try:
            adapter.check_configured()
        except ScrapeError as exc:
            raise CommandError(str(exc))

        failures = 0
        try:
            for query in opts['query']:
                try:
                    run, listings = run_query(adapter, query, opts['category'], opts['main_category'],
                                              limit=opts['limit'], dry_run=opts['dry_run'])
                except ScrapeError as exc:
                    failures += 1
                    self.stderr.write(self.style.ERROR(f'[{query}] {exc}'))
                    continue
                if opts['dry_run']:
                    self.stdout.write(f'[{query}] {len(listings)} listings (dry run, nothing saved):')
                    for item in listings:
                        self.stdout.write(f'  Rs {item.price or "-":>8}  {item.name[:70]}')
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f'[{query}] fetched {run.fetched}: {run.products_created} new products, '
                        f'{run.offers_created} new offers, {run.price_changes} price changes, {run.skipped} skipped'))
        finally:
            adapter.client.close()
        if failures == len(opts['query']):
            raise CommandError('All queries failed.')
