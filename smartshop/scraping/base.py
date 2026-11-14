"""Adapter interface: one subclass per data source.

An adapter only knows how to *find* listings on its source and turn them into
ScrapedListing objects. Rate limiting, retries and robots.txt live in PoliteClient;
saving to the database lives in products.ingestion. That keeps adapters tiny.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from .http import HostPolicy, PoliteClient


@dataclass
class ScrapedListing:
    name: str
    url: str
    price: Optional[str] = None
    mrp: Optional[str] = None
    in_stock: bool = True
    image_url: str = ''
    brand: str = ''
    rating: Optional[str] = None
    delivery_date: str = ''
    source_id: str = ''                  # the source's own product id (e.g. Flipkart pid)
    extra: dict = field(default_factory=dict)


class SourceAdapter(ABC):
    name = ''            # registry key, e.g. 'flipkart'
    seller = ''          # stored on Offer.seller, e.g. 'Flipkart'
    kind = 'api'         # 'api' (official, contract-governed) or 'html' (public pages)
    policy = HostPolicy()

    def __init__(self, client=None):
        self.client = client or PoliteClient(policy=self.policy)

    def check_configured(self):
        """Raise NotConfigured if credentials/settings are missing."""

    @abstractmethod
    def search(self, query, limit=10):
        """Return a list of ScrapedListing for a keyword query."""
