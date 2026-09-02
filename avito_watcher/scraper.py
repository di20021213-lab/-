"""Парсер страницы поиска Авито на Playwright (Chromium)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)

BASE_URL = "https://www.avito.ru"

# Сколько ждать появления объявлений на уже загруженной странице.
ITEMS_WAIT_MS = 15000

# Признаки того, что нас встретил антибот/капча, а не выдача.
ANTIBOT_MARKERS = (
    "подтвердите, что запросы отправляли вы",
    "доступ ограничен",
    "проблема с ip",
    "you have been blocked",
    "are you a robot",
    "checking your browser",
)

# JS, который вытаскивает объявления по стабильным data-marker атрибутам.
_EXTRACT_JS = r"""
() => {
  const items = Array.from(document.querySelectorAll('[data-marker="item"]'));
  return items.map(el => {
    const id = el.getAttribute('data-item-id') || el.id || null;

    const titleEl = el.querySelector('[data-marker="item-title"]');
    let url = titleEl ? titleEl.getAttribute('href') : null;
    let title = null;
    if (titleEl) {
      title = (titleEl.getAttribute('title') || titleEl.innerText || '').trim();
    }

    const metaPrice = el.querySelector('meta[itemprop="price"]');
    const priceEl = el.querySelector('[data-marker="item-price"]');
    let price = null;
    if (priceEl) price = (priceEl.innerText || '').trim();
    let priceValue = metaPrice ? metaPrice.getAttribute('content') : null;

    const dateEl = el.querySelector('[data-marker="item-date"]');
    const dateText = dateEl ? (dateEl.innerText || '').trim() : null;

    const addrEl = el.querySelector('[data-marker="item-address"]')
      || el.querySelector('[class*="geo-"]');
    let location = addrEl ? (addrEl.innerText || '').trim() : null;
    if (location) location = location.replace(/\s+/g, ' ');

    const imgEl = el.querySelector('img');
    let image = null;
    if (imgEl) {
      image = imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || null;
      if (!image) {
        const ss = imgEl.getAttribute('srcset');
        if (ss) image = ss.split(',')[0].trim().split(' ')[0];
      }
    }

    return { id, url, title, price, priceValue, dateText, location, image };
  }).filter(x => x.id);
}
"""


class AntibotError(Exception):
    """Страница вернула антибот/капчу вместо выдачи."""


@dataclass
class Listing:
    id: str
    title: Optional[str]
    price: Optional[str]
    price_value: Optional[int]
    url: Optional[str]
    location: Optional[str]
    date_text: Optional[str]
    image_url: Optional[str]


def _parse_price(price_value, price_text) -> Optional[int]:
    if price_value:
        try:
            return int(price_value)
        except (TypeError, ValueError):
            pass
    if price_text:
        digits = re.sub(r"[^\d]", "", price_text)
        if digits:
            return int(digits)
    return None


def _absolutize(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return BASE_URL + url
    return url


class AvitoScraper:
    """Контекстный менеджер: держит один браузер на всё время работы."""

    def __init__(
        self,
        headless: bool = True,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout_ms: int = 45000,
        executable_path: Optional[str] = None,
    ) -> None:
        self.headless = headless
        self.proxy = proxy
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        # Путь к готовому браузеру (если Playwright не должен качать свой).
        self.executable_path = executable_path
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "AvitoScraper":
        self._pw = sync_playwright().start()
        launch_kwargs = {"headless": self.headless}
        if self.proxy:
            launch_kwargs["proxy"] = {"server": self.proxy}
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path
        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            user_agent=self.user_agent,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1366, "height": 900},
        )
        self._context.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, *exc) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except Exception:  # noqa: BLE001 - на закрытии игнорируем всё
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass

    def fetch(self, url: str) -> list[Listing]:
        """Загружает страницу поиска и возвращает список объявлений (первая страница)."""
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)

            # Проверка на антибот до ожидания выдачи.
            body_text = (page.inner_text("body")[:4000] if page.query_selector("body") else "").lower()
            if any(marker in body_text for marker in ANTIBOT_MARKERS):
                raise AntibotError("Похоже на антибот/капчу Авито (нужен другой IP/прокси).")

            # Объявления у Авито есть уже в исходном HTML, поэтому ждём их недолго:
            # иначе пустая выдача стопорила бы цикл на весь request_timeout_ms.
            try:
                page.wait_for_selector('[data-marker="item"]',
                                       timeout=min(self.timeout_ms, ITEMS_WAIT_MS))
            except PWTimeout:
                # либо антибот, либо пустая выдача — различаем по тексту
                body_text = (page.inner_text("body")[:4000]).lower()
                if any(marker in body_text for marker in ANTIBOT_MARKERS):
                    raise AntibotError("Антибот/капча Авито (нужен другой IP/прокси).")
                log.info("Выдача пуста или изменилась вёрстка: %s", url)
                return []

            raw = page.evaluate(_EXTRACT_JS)
        finally:
            page.close()

        listings: list[Listing] = []
        for r in raw:
            listings.append(
                Listing(
                    id=str(r["id"]),
                    title=r.get("title"),
                    price=r.get("price"),
                    price_value=_parse_price(r.get("priceValue"), r.get("price")),
                    url=_absolutize(r.get("url")),
                    location=r.get("location"),
                    date_text=r.get("dateText"),
                    image_url=r.get("image"),
                )
            )
        return listings
