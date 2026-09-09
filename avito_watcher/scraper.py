"""Парсер страницы поиска Авито на Playwright (Chromium)."""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlparse

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from .dates import parse_age_minutes

log = logging.getLogger(__name__)

BASE_URL = "https://www.avito.ru"

# Сколько ждать появления объявлений на уже загруженной странице.
ITEMS_WAIT_MS = 15000

# Страница объявления: описание + блок параметров («Состояние: …»).
DETAILS_SELECTOR = (
    '[data-marker="item-view/item-description"], [itemprop="description"], '
    '[data-marker="item-view/item-params"]'
)
DETAILS_WAIT_MS = 8000

# Что не грузим: видео и шрифты — тяжёлые и на содержимое не влияют.
# Картинки грузим намеренно, хотя это и десятки запросов: без них Авито не
# подставляет в <img> настоящие ссылки, и в уведомление нечего вложить.
# Заодно браузер, который не тянет ни одной картинки, выглядит неестественно.
BLOCKED_RESOURCES = {"media", "font"}

# Сколько раз повторить при 429/блокировке и с какой паузой. 429 — это лимит по
# IP, он снимается только временем, поэтому пауза растёт: 20 с, 40 с, 80 с…
FETCH_RETRIES = 3
RETRY_DELAY_S = 20

# Аргументы запуска Chromium, которые убирают самые заметные следы автоматизации.
LAUNCH_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
)
# Этот флаг Playwright добавляет сам; из-за него браузер объявляет себя ботом.
IGNORE_DEFAULT_ARGS = ("--enable-automation",)

# Прячем navigator.webdriver: в обычном Chrome он undefined, у Playwright — true.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""

# Заголовки, которые настоящий браузер шлёт, а Playwright по умолчанию — нет.
EXTRA_HEADERS = {
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
}

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

    // Дата публикации. Авито меняет разметку, а без даты ломается фильтр
    // свежести (неразобранная дата не отсеивается — объявление проходит как
    // «возраст неизвестен»). Поэтому пробуем несколько селекторов, а если ни
    // один не сработал — ищем в карточке текст, похожий на дату.
    let dateText = null;
    for (const sel of ['[data-marker="item-date"]', '[data-marker="item/date"]', 'time']) {
      const dEl = el.querySelector(sel);
      const txt = dEl ? (dEl.innerText || dEl.textContent || '').trim() : '';
      if (txt) { dateText = txt; break; }
    }
    if (!dateText) {
      const dateLike = /(только что|сегодня|вчера|назад|\d{1,2}\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр))/i;
      for (const node of el.querySelectorAll('p, span, div')) {
        const txt = (node.textContent || '').trim();
        if (txt && txt.length <= 40 && dateLike.test(txt)) { dateText = txt; break; }
      }
    }

    const addrEl = el.querySelector('[data-marker="item-address"]')
      || el.querySelector('[class*="geo-"]');
    let location = addrEl ? (addrEl.innerText || '').trim() : null;
    if (location) location = location.replace(/\s+/g, ' ');

    // Картинка объявления. Из srcset берём САМУЮ КРУПНУЮ (первая — это мелкая
    // превьюшка), заглушки (data:, 1x1, placeholder) не считаем за картинку.
    const usable = (u) => u && !u.startsWith('data:') && !/placeholder|stub|blank/i.test(u);
    const biggest = (ss) => {
      if (!ss) return null;
      let best = null, bestW = -1;
      for (const part of ss.split(',')) {
        const bits = part.trim().split(/\s+/);
        if (!bits[0]) continue;
        const w = parseInt((bits[1] || '').replace(/\D/g, ''), 10) || 0;
        if (w >= bestW) { bestW = w; best = bits[0]; }
      }
      return best;
    };

    let image = null;
    for (const imgEl of el.querySelectorAll('img')) {
      const candidates = [
        biggest(imgEl.getAttribute('srcset')),
        biggest(imgEl.getAttribute('data-srcset')),
        imgEl.getAttribute('src'),
        imgEl.getAttribute('data-src'),
      ];
      image = candidates.find(usable) || null;
      if (image) break;
    }

    return { id, url, title, price, priceValue, dateText, location, image };
  }).filter(x => x.id);
}
"""


def _matching_user_agent(browser) -> Optional[str]:
    """UA под реальную версию браузера и реальную платформу (Linux).

    Подставлять выдуманный UA опасно: Chromium параллельно шлёт client hints
    (Sec-CH-UA, Sec-CH-UA-Platform) со своей НАСТОЯЩЕЙ версией и платформой.
    Если UA говорит «Chrome 124 на Windows», а подсказки — «Chrome 141 на Linux»,
    расхождение видно антиботу в одну проверку. Поэтому собираем UA из версии
    самого браузера; слово Headless в него не попадает.
    """
    try:
        major = browser.version.split(".")[0]
        int(major)
    except (AttributeError, ValueError, IndexError):
        return None
    return (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )


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
    # Сколько минут прошло с публикации (None — не смогли разобрать дату).
    age_minutes: Optional[int] = None


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


def _proxy_config(proxy_url: str) -> dict:
    """Разбирает URL прокси в формат Playwright.

    Chromium НЕ понимает логин и пароль внутри --proxy-server: часть
    user:pass@ он молча отбрасывает, подключается без авторизации и виснет.
    Поэтому их нужно передавать отдельными полями username/password.
    """
    u = urlparse(proxy_url)
    server = f"{u.scheme}://{u.hostname}"
    if u.port:
        server = f"{server}:{u.port}"
    cfg = {"server": server}
    if u.username:
        cfg["username"] = unquote(u.username)
    if u.password:
        cfg["password"] = unquote(u.password)
    return cfg


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
        launch_kwargs = {
            "headless": self.headless,
            "args": list(LAUNCH_ARGS),
            "ignore_default_args": list(IGNORE_DEFAULT_ARGS),
        }
        if self.proxy:
            launch_kwargs["proxy"] = _proxy_config(self.proxy)
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path

        # channel="chromium" — это НОВЫЙ headless-режим обычного Chromium.
        # Без него Playwright запускает отдельный урезанный chrome-headless-shell,
        # который антиботы отличают от браузера влёт. На старых версиях
        # Playwright или без установленного полного Chromium — откат на дефолт.
        try:
            self._browser = self._pw.chromium.launch(channel="chromium", **launch_kwargs)
        except PWError as e:
            log.warning("Не удалось запустить полный Chromium (%s), беру headless-shell", e)
            self._browser = self._pw.chromium.launch(**launch_kwargs)

        # UA не задан в конфиге -> берём согласованный с версией браузера.
        user_agent = self.user_agent or _matching_user_agent(self._browser)
        log.debug("User-Agent: %s", user_agent)

        self._context = self._browser.new_context(
            user_agent=user_agent,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1366, "height": 900},
            extra_http_headers=dict(EXTRA_HEADERS),
        )
        self._context.add_init_script(_STEALTH_JS)
        self._context.set_default_timeout(self.timeout_ms)
        self._context.route("**/*", self._route)
        return self

    @staticmethod
    def _route(route) -> None:
        """Отсекает тяжёлые ресурсы: меньше запросов — меньше шансов на 429."""
        try:
            if route.request.resource_type in BLOCKED_RESOURCES:
                route.abort()
            else:
                route.continue_()
        except Exception:  # noqa: BLE001 - гонка при закрытии страницы
            pass

    @staticmethod
    def _route_text_only(route) -> None:
        """То же, но ещё и без картинок — для страниц, где нужен только текст.

        На странице объявления галерея не нужна: мы пришли за описанием. А это
        десятки лишних запросов за пару секунд, на которых Авито и показывает
        антибот. Ссылки на фото мы всё равно берём со страницы выдачи.
        """
        try:
            if route.request.resource_type in BLOCKED_RESOURCES | {"image"}:
                route.abort()
            else:
                route.continue_()
        except Exception:  # noqa: BLE001
            pass

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
        """Загружает страницу поиска, повторяя попытку при блокировке."""
        last: Optional[AntibotError] = None
        for attempt in range(1, FETCH_RETRIES + 1):
            try:
                return self._fetch_once(url)
            except AntibotError as e:
                last = e
                if attempt < FETCH_RETRIES:
                    # Пауза растёт вдвое: 429 снимается только временем, долбить
                    # тем же интервалом бессмысленно. Джиттер — чтобы циклы
                    # не били в сайт строго по расписанию.
                    delay = RETRY_DELAY_S * (2 ** (attempt - 1))
                    delay += random.uniform(0, delay * 0.25)
                    log.info("Блокировка (попытка %d из %d), повтор через %d с: %s",
                             attempt, FETCH_RETRIES, round(delay), e)
                    time.sleep(delay)
        raise last

    def _fetch_once(self, url: str) -> list[Listing]:
        """Одна попытка: загрузить страницу и разобрать объявления."""
        page = self._context.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            # HTTP-статус сильно помогает при разборе: 429 — это лимит по IP
            # (маскировка браузера не спасёт), 403 — блокировка, 200 — вёрстка.
            status = resp.status if resp else None

            # Проверка на антибот до ожидания выдачи.
            body_text = (page.inner_text("body")[:4000] if page.query_selector("body") else "").lower()
            if status in (403, 429) or any(marker in body_text for marker in ANTIBOT_MARKERS):
                raise AntibotError(
                    f"Похоже на антибот/капчу Авито (HTTP {status}). Нужен другой IP/прокси."
                )

            # Объявления у Авито есть уже в исходном HTML, поэтому ждём их недолго:
            # иначе пустая выдача стопорила бы цикл на весь request_timeout_ms.
            try:
                page.wait_for_selector('[data-marker="item"]',
                                       timeout=min(self.timeout_ms, ITEMS_WAIT_MS))
            except PWTimeout:
                # либо антибот, либо пустая выдача — различаем по тексту
                body_text = (page.inner_text("body")[:4000]).lower()
                if any(marker in body_text for marker in ANTIBOT_MARKERS):
                    raise AntibotError(f"Антибот/капча Авито (HTTP {status}). Нужен другой IP/прокси.")
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
                    age_minutes=parse_age_minutes(r.get("dateText")),
                )
            )
        return listings

    def fetch_details(self, url: str) -> Optional[str]:
        """Открывает страницу объявления, возвращает текст описания + параметров (или None)."""
        page = self._context.new_page()
        # Правило страницы имеет приоритет над правилом контекста: здесь режем
        # ещё и картинки, хотя на выдаче они грузятся.
        page.route("**/*", self._route_text_only)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)

            body_text = (page.inner_text("body")[:4000] if page.query_selector("body") else "").lower()
            if any(marker in body_text for marker in ANTIBOT_MARKERS):
                raise AntibotError("Антибот/капча Авито на странице объявления.")

            parts = []

            # Мета-описание: лежит в <head>, доступно сразу и не зависит от вёрстки.
            # Именно его показывает Telegram в превью ссылки, и в нём есть начало
            # описания продавца — то самое «не рабочая», ради которого мы и пришли.
            for sel in ('meta[property="og:description"]', 'meta[name="description"]'):
                meta = page.query_selector(sel)
                if meta:
                    content = (meta.get_attribute("content") or "").strip()
                    if content:
                        parts.append(content)
                        break

            # Полное описание и блок параметров. Может не успеть отрисоваться —
            # тогда обходимся мета-описанием, а не теряем проверку целиком.
            try:
                page.wait_for_selector(DETAILS_SELECTOR,
                                       timeout=min(self.timeout_ms, DETAILS_WAIT_MS))
                for el in page.query_selector_all(DETAILS_SELECTOR):
                    txt = (el.inner_text() or "").strip()
                    if txt:
                        parts.append(txt)
            except PWTimeout:
                log.info("Описание не отрисовалось, беру мета-описание: %s", url)

            return "\n".join(parts) or None
        finally:
            page.close()
