"""Клиентские фильтры поверх URL-фильтров Авито."""

from __future__ import annotations

import re
from typing import Optional

from .config import SearchConfig, match_model
from .dates import format_age
from .scraper import Listing


_PUNCT = re.compile(r"[^0-9a-zа-я]+")


def _flat(text: str) -> str:
    """Заголовок без пунктуации: слова через один пробел.

    Продавцы пишут «Star wars: Dark Forces Remaster», а ключевое слово в
    конфиге — «star wars dark forces». Без этой чистки двоеточие ломало поиск
    подстроки, и поиск молча не находил ничего: ни ошибки, ни пустой выдачи —
    просто ноль подходящих, что со стороны неотличимо от «объявлений нет».
    """
    return " " + _PUNCT.sub(" ", (text or "").lower().replace("ё", "е")).strip() + " "


def explain(listing: Listing, search: SearchConfig) -> Optional[str]:
    """Причина, по которой объявление не подходит, либо None если подходит."""
    title = _flat(listing.title)

    if search.keywords and not any(_flat(k).strip() in title for k in search.keywords):
        return f"в заголовке нет ни одного из {search.keywords}"

    if search.exclude_keywords:
        hit = next((k for k in search.exclude_keywords
                    if _flat(k).strip() in title), None)
        if hit:
            return f"в заголовке стоп-слово «{hit}»"

    # Стоп-слова по карточке целиком: имя продавца, значок «Магазин», кусок
    # описания. Текст карточки пришёл вместе с выдачей, лишних запросов к Авито
    # это не стоит. Ловит то, чего в заголовке нет и не будет: у комиссионки
    # заголовок как у частника, а вот вокруг него — «скупаем приставки и диски».
    if search.exclude_card_keywords and listing.card_text:
        card = _flat(listing.card_text)
        hit = next((k for k in search.exclude_card_keywords
                    if _flat(k).strip() in card), None)
        if hit:
            return f"в карточке стоп-слово «{hit}»"

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

    # Потолок по модели важнее общего: 4000 ₽ — находка для 1060 и переплата
    # для 750 Ti, одной цифрой это не выразить.
    max_price = search.max_price
    if search.models:
        rule = match_model(listing.title, search.models)
        if rule is None:
            return "модель не из списка"
        max_price = rule.max_price

    has_bounds = max_price is not None or search.min_price is not None
    if has_bounds and price is None:
        # Задан ценовой диапазон, а цена не указана («договорная») — вне диапазона.
        return "цена не указана, а задан ценовой диапазон"
    if max_price is not None and price > max_price:
        rule = match_model(listing.title, search.models) if search.models else None
        limit = f"{rule.name}: {max_price}" if rule else str(max_price)
        return f"дороже потолка ({price} > {limit})"
    if search.min_price is not None and price < search.min_price:
        return f"дешевле min_price ({price} < {search.min_price})"

    return None


def passes(listing: Listing, search: SearchConfig) -> bool:
    """Проверяет объявление против дополнительных фильтров поиска."""
    return explain(listing, search) is None
