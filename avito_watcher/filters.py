"""Клиентские фильтры поверх URL-фильтров Авито."""

from __future__ import annotations

from .config import SearchConfig
from .scraper import Listing


def passes(listing: Listing, search: SearchConfig) -> bool:
    """Проверяет объявление против дополнительных фильтров поиска."""
    title = (listing.title or "").lower()

    if search.keywords and not any(k in title for k in search.keywords):
        return False

    if search.exclude_keywords and any(k in title for k in search.exclude_keywords):
        return False

    price = listing.price_value
    if search.max_price is not None and price is not None and price > search.max_price:
        return False
    if search.min_price is not None and price is not None and price < search.min_price:
        return False

    return True
