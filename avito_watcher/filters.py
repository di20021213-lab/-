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

    # Свежесть: старше max_age — пропускаем. Неизвестный возраст (не разобрали дату)
    # НЕ отсеиваем: объявление всё равно новое для нас (его ID не было в базе),
    # и лучше лишний раз показать, чем молча потерять выгодное из-за смены вёрстки.
    if search.max_age_minutes is not None and listing.age_minutes is not None:
        if listing.age_minutes > search.max_age_minutes:
            return False

    price = listing.price_value
    has_bounds = search.max_price is not None or search.min_price is not None
    if has_bounds and price is None:
        # Задан ценовой диапазон, а цена не указана («договорная») — вне диапазона.
        return False
    if search.max_price is not None and price > search.max_price:
        return False
    if search.min_price is not None and price < search.min_price:
        return False

    return True
