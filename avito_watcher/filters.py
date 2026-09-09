"""Клиентские фильтры поверх URL-фильтров Авито."""

from __future__ import annotations

from typing import Optional

from .config import SearchConfig
from .dates import format_age
from .scraper import Listing


def explain(listing: Listing, search: SearchConfig) -> Optional[str]:
    """Причина, по которой объявление не подходит, либо None если подходит."""
    title = (listing.title or "").lower()

    if search.keywords and not any(k in title for k in search.keywords):
        return f"в заголовке нет ни одного из {search.keywords}"

    if search.exclude_keywords:
        hit = next((k for k in search.exclude_keywords if k in title), None)
        if hit:
            return f"в заголовке стоп-слово «{hit}»"

    # Свежесть: старше max_age — пропускаем. Неизвестный возраст (Авито не показал
    # дату — так бывает у магазинов) по умолчанию НЕ отсеиваем: объявление всё
    # равно новое для нас, и лучше лишний раз показать, чем молча потерять
    # выгодное. Но если такого мусора много, помогает require_age: true.
    if search.max_age_minutes is not None:
        if listing.age_minutes is not None:
            if listing.age_minutes > search.max_age_minutes:
                return (f"старше max_age ({format_age(listing.age_minutes)} > "
                        f"{format_age(search.max_age_minutes)})")
        elif listing.min_age_minutes is not None:
            # Даты нет, но объявление стоит НИЖЕ датированного — значит оно не
            # моложе того. Этого достаточно, чтобы отсеять старьё, не рискуя
            # выбросить свежее объявление с непрочитанной датой.
            if listing.min_age_minutes > search.max_age_minutes:
                return (f"старше max_age (не моложе {format_age(listing.min_age_minutes)} "
                        f"по позиции в выдаче)")
        elif search.require_age:
            return "возраст неизвестен, а включён require_age"

    price = listing.price_value
    has_bounds = search.max_price is not None or search.min_price is not None
    if has_bounds and price is None:
        # Задан ценовой диапазон, а цена не указана («договорная») — вне диапазона.
        return "цена не указана, а задан ценовой диапазон"
    if search.max_price is not None and price > search.max_price:
        return f"дороже max_price ({price} > {search.max_price})"
    if search.min_price is not None and price < search.min_price:
        return f"дешевле min_price ({price} < {search.min_price})"

    return None


def passes(listing: Listing, search: SearchConfig) -> bool:
    """Проверяет объявление против дополнительных фильтров поиска."""
    return explain(listing, search) is None
