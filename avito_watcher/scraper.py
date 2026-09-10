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

# Авито дорисовывает карточки лениво: ниже первого экрана в разметке ещё нет ни
# даты публикации, ни ссылки на фото. Без прокрутки мы читаем только первые
# 8-10 объявлений полноценно, а у остальных возраст неизвестен — и фильтр
# свежести к ним просто не применяется. Поэтому прокручиваем до конца выдачи.
# Шаг прокрутки — доля высоты окна. Больше единицы брать НЕЛЬЗЯ: часть страницы
# пролетит мимо, ни разу не побывав в поле зрения, и её карточки не отрисуются.
#
# Про паузу. 350 мс не хватало: на одной и той же выдаче из 56 карточек ссылка
# на фото находилась то у 43, то у 13, то у 46. Такой разброс — признак гонки:
# ссылку Авито подставляет, когда карточка попала в поле зрения, а мы уезжали
# дальше раньше. Ставим 700 мс. Лишних запросов к Авито это не добавляет — а
# именно они упираются в лимит; страница просто читается на полминуты дольше,
# при интервале в 20 минут это ничего не значит.
MAX_SCROLLS = 40
SCROLL_STEP_RATIO = 0.8
SCROLL_PAUSE_MS = 700

# Сколько ждать в самом низу, прежде чем прочитать выдачу последний раз.
# Нижние карточки только что появились в поле зрения, и им нужно то же время
# на подстановку картинок, что и всем остальным.
SETTLE_MS = 1500

# Страница объявления: описание + блок параметров («Состояние: …»).
DETAILS_SELECTOR = (
    '[data-marker="item-view/item-description"], [itemprop="description"], '
    '[data-marker="item-view/item-params"]'
)
DETAILS_WAIT_MS = 8000

# Картинки НЕ качаем, хотя ссылки на них нам нужны. Ссылка появляется в <img>
# при отрисовке карточки (её вызывает прокрутка), а не при загрузке файла —
# так что адрес мы прочитаем, а полсотни лишних запросов на страницу не сделаем.
# Именно они и приводили к 429, когда областей стало четыре.
BLOCKED_RESOURCES = {"image", "media", "font"}

# Повторов внутри одной проверки НЕТ. По логам: после блокировки три быстрых
# повтора (через 25 и 50 секунд) глухие все три — они не помогают, а только
# дожигают маленький бюджет адреса и загоняют бота в долгую паузу. Что реально
# работает — тишина на 20-30 минут, и её обеспечивает пауза между циклами.
FETCH_RETRIES = 1
RETRY_DELAY_S = 20

# Хосты счётчиков и рекламы: тратят тот же лимит запросов с адреса, а на
# содержимое выдачи не влияют. Режем по суффиксу домена.
TRACKER_HOSTS = (
    "mc.yandex.ru", "an.yandex.ru", "yandex.ru/metrika", "ads.adfox.ru",
    "google-analytics.com", "googletagmanager.com", "doubleclick.net",
    "googlesyndication.com", "top-fwz1.mail.ru", "top-mail.ru", "vk.com",
    "criteo.com", "criteo.net", "adriver.ru", "rutarget.ru", "tns-counter.ru",
    "facebook.com", "facebook.net", "hotjar.com", "sentry.io",
)

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

    // Весь текст карточки: там же лежит кусок описания продавца. По нему можно
    // отсеять нерабочую карту, НЕ открывая страницу объявления — а это половина
    // всех наших запросов к Авито.
    let cardText = (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 600);

    return { id, url, title, price, priceValue, dateText, location, image, cardText };
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
    """Страница вернула антибот/капчу вместо выдачи.

    screenshot — снимок этой страницы (PNG), чтобы посмотреть, что именно
    показывает Авито: заглушку про лимит или капчу, которую можно решить.
    """

    def __init__(self, message: str, screenshot: Optional[bytes] = None) -> None:
        super().__init__(message)
        self.screenshot = screenshot


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
    # Нижняя оценка возраста по позиции в выдаче: объявление без даты, стоящее
    # ниже датированного, не моложе него (выдача отсортирована по дате).
    min_age_minutes: Optional[int] = None
    # Текст карточки целиком — в нём часто виден кусок описания продавца.
    card_text: Optional[str] = None


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
    """Приводит ссылку к абсолютной.

    Важно и для картинок: Авито часто отдаёт их протокол-независимыми
    (//img.avito.st/...), а Telegram такой адрес не принимает — sendPhoto
    молча проваливается, и уведомление уходит голым текстом.
    """
    if not url:
        return None
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return "https:" + url
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
        user_data_dir: Optional[str] = None,
    ) -> None:
        self.headless = headless
        self.proxy = proxy
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        # Путь к готовому браузеру (если Playwright не должен качать свой).
        self.executable_path = executable_path
        # Папка профиля браузера. С ней куки живут между запусками, и бот
        # выглядит как вернувшийся посетитель, а не как новый каждые десять
        # минут — для антибота разница существенная.
        self.user_data_dir = user_data_dir
        self._pw = None
        self._browser = None
        self._context = None

    def _launch_kwargs(self) -> dict:
        kw = {
            "headless": self.headless,
            "args": list(LAUNCH_ARGS),
            "ignore_default_args": list(IGNORE_DEFAULT_ARGS),
        }
        if self.proxy:
            kw["proxy"] = _proxy_config(self.proxy)
        if self.executable_path:
            kw["executable_path"] = self.executable_path
        return kw

    def _launch_browser(self):
        """Обычный запуск. channel=chromium — новый headless настоящего браузера,
        без него Playwright поднимает урезанный chrome-headless-shell."""
        kw = self._launch_kwargs()
        try:
            return self._pw.chromium.launch(channel="chromium", **kw)
        except PWError as e:
            log.warning("Не удалось запустить полный Chromium (%s), беру headless-shell", e)
            return self._pw.chromium.launch(**kw)

    def _resolve_user_agent(self) -> Optional[str]:
        """UA под версию браузера. Для профиля его нужно знать ДО запуска,
        поэтому версию считываем отдельным коротким запуском — один раз за
        всё время работы бота."""
        if self.user_agent:
            return self.user_agent
        try:
            browser = self._launch_browser()
        except Exception as e:  # noqa: BLE001
            log.warning("Не смог определить версию браузера: %s", e)
            return None
        try:
            return _matching_user_agent(browser)
        finally:
            browser.close()

    def __enter__(self) -> "AvitoScraper":
        self._pw = sync_playwright().start()
        context_kwargs = {
            "locale": "ru-RU",
            "timezone_id": "Europe/Moscow",
            "viewport": {"width": 1366, "height": 900},
            "extra_http_headers": dict(EXTRA_HEADERS),
        }

        if self.user_data_dir:
            self._context = self._open_persistent(context_kwargs)

        if self._context is None:
            self._browser = self._launch_browser()
            context_kwargs["user_agent"] = (self.user_agent
                                            or _matching_user_agent(self._browser))
            self._context = self._browser.new_context(**context_kwargs)

        self._context.add_init_script(_STEALTH_JS)
        self._context.set_default_timeout(self.timeout_ms)
        self._context.route("**/*", self._route)
        return self

    @staticmethod
    def _is_tracker(url: str) -> bool:
        host = urlparse(url).hostname or ""
        return any(host == t or host.endswith("." + t) or t in url for t in TRACKER_HOSTS)

    @classmethod
    def _route(cls, route) -> None:
        """Отсекает тяжёлые ресурсы и счётчики: меньше запросов — меньше 429."""
        try:
            req = route.request
            if req.resource_type in BLOCKED_RESOURCES or cls._is_tracker(req.url):
                route.abort()
            else:
                route.continue_()
        except Exception:  # noqa: BLE001 - гонка при закрытии страницы
            pass

    @classmethod
    def _route_text_only(cls, route) -> None:
        """То же, но ещё и без картинок — для страниц, где нужен только текст.

        На странице объявления галерея не нужна: мы пришли за описанием. А это
        десятки лишних запросов за пару секунд, на которых Авито и показывает
        антибот. Ссылки на фото мы всё равно берём со страницы выдачи.
        """
        try:
            req = route.request
            if req.resource_type in BLOCKED_RESOURCES | {"image"} or cls._is_tracker(req.url):
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

    def fetch(self, url: str, max_age_minutes: Optional[int] = None) -> list[Listing]:
        """Загружает страницу поиска, повторяя попытку при блокировке.

        max_age_minutes — до какого возраста читать выдачу. Дальше не идём:
        она отсортирована по дате, и всё нижнее заведомо старше.
        """
        last: Optional[AntibotError] = None
        for attempt in range(1, FETCH_RETRIES + 1):
            try:
                return self._fetch_once(url, max_age_minutes)
            except AntibotError as e:
                last = e
                # Страница блокировки может поставить куку-метку: с ней все
                # следующие запросы в этом же контексте обречены, даже когда
                # сам адрес давно чист. Свежий заход без куки проходит — это
                # мы видели диагностикой прямо посреди «заблокированного» часа.
                # Поэтому перед повтором сбрасываем куки; с постоянным профилем
                # это ещё важнее — иначе метка переживёт и перезапуск.
                self.forget_session()
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

    @staticmethod
    def _snapshot(page) -> Optional[bytes]:
        """Снимок страницы блокировки. Не критично: не вышло — и ладно."""
        try:
            return page.screenshot(full_page=False, type="png")
        except Exception:  # noqa: BLE001
            return None

    def forget_session(self) -> None:
        """Сбрасывает куки текущего контекста, чтобы начать как новый посетитель."""
        try:
            self._context.clear_cookies()
            log.info("Куки сброшены: следующий заход будет без метки антибота")
        except Exception as e:  # noqa: BLE001 - контекст мог уже закрыться
            log.info("Не смог сбросить куки: %s", e)

    def _open_persistent(self, context_kwargs: dict):
        """Браузер с постоянным профилем: куки переживают перезапуск.

        При любой беде с профилем (побился, нет прав) возвращаем None — бот
        продолжит на обычном одноразовом контексте, это лучше, чем не запуститься.
        """
        kwargs = {**self._launch_kwargs(), **context_kwargs,
                  "user_agent": self._resolve_user_agent()}
        for channel in ("chromium", None):
            try:
                if channel:
                    return self._pw.chromium.launch_persistent_context(
                        self.user_data_dir, channel=channel, **kwargs)
                return self._pw.chromium.launch_persistent_context(
                    self.user_data_dir, **kwargs)
            except Exception as e:  # noqa: BLE001
                last = e
        log.warning("Профиль браузера не открылся (%s), работаю без него", last)
        return None

    @staticmethod
    def _merge(into: dict, rows: list[dict]) -> None:
        """Добавляет прочитанное, не затирая уже найденные значения."""
        for row in rows:
            item = into.setdefault(row["id"], {})
            for key, value in row.items():
                if value not in (None, "") and not item.get(key):
                    item[key] = value

    def _collect_while_scrolling(self, page, max_age_minutes: Optional[int] = None) -> list[dict]:
        """Читает карточки НА КАЖДОМ шаге прокрутки и склеивает результат.

        Одного чтения в конце мало. Авито ведёт себя с полями по-разному:
        ссылка на фото, однажды подставленная, остаётся в разметке, а дата
        публикации живёт только пока карточка в поле зрения — уехала вниз, и
        дата из неё исчезла. Поэтому к моменту «прокрутили всё и прочитали»
        даты есть опять только у первого экрана.

        Собираем по кусочкам: что увидели на любом шаге — то и запомнили.
        """
        merged: dict[str, dict] = {}

        def past_cutoff() -> bool:
            """Дошли ли мы до объявлений старше max_age.

            Выдача идёт по дате, поэтому ниже первого такого объявления всё
            остальное ещё старше — читать и прокручивать дальше незачем. При
            max_age в час это экономит почти всю страницу, а вместе с ней и
            запросы, из-за которых прилетает 429.
            """
            if max_age_minutes is None:
                return False
            return any(
                (age := parse_age_minutes(row.get("dateText"))) is not None
                and age > max_age_minutes
                for row in merged.values()
            )

        try:
            self._merge(merged, page.evaluate(_EXTRACT_JS))
            for _ in range(MAX_SCROLLS):
                if past_cutoff():
                    break
                before = page.evaluate("() => window.scrollY")
                page.evaluate(
                    f"() => window.scrollBy(0, window.innerHeight * {SCROLL_STEP_RATIO})"
                )
                page.wait_for_timeout(SCROLL_PAUSE_MS)
                self._merge(merged, page.evaluate(_EXTRACT_JS))
                # Доскроллили до низа — позиция перестала меняться.
                if page.evaluate("() => window.scrollY") <= before:
                    break
            # Последний проход: даём странице досчитать и читаем ещё раз. Всё,
            # что подставилось с опозданием, попадёт сюда — merge не затирает
            # уже найденное, так что хуже от этого не станет.
            page.wait_for_timeout(SETTLE_MS)
            self._merge(merged, page.evaluate(_EXTRACT_JS))
        except Exception as e:  # noqa: BLE001 - читаем то, что успели собрать
            log.info("Прокрутка прервалась (%s), беру собранное", e)
        return list(merged.values())

    def _fetch_once(self, url: str, max_age_minutes: Optional[int] = None) -> list[Listing]:
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
                    f"Похоже на антибот/капчу Авито (HTTP {status}). Нужен другой IP/прокси.",
                    screenshot=self._snapshot(page),
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
                    raise AntibotError(f"Антибот/капча Авито (HTTP {status}). Нужен другой IP/прокси.",
                                       screenshot=self._snapshot(page))
                log.info("Выдача пуста или изменилась вёрстка: %s", url)
                return []

            raw = self._collect_while_scrolling(page, max_age_minutes)
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
                    image_url=_absolutize(r.get("image")),
                    age_minutes=parse_age_minutes(r.get("dateText")),
                    card_text=r.get("cardText"),
                )
            )

        # Оценка возраста для объявлений без даты. Авито показывает дату
        # примерно неделю, дальше её в карточке нет — но раз выдача идёт по
        # дате, всё, что ниже датированного, старше него. Это позволяет
        # отсеять старьё, не отбрасывая заодно свежее объявление, у которого
        # дату не удалось прочитать.
        seen: Optional[int] = None
        for lst in listings:
            if lst.age_minutes is not None:
                seen = lst.age_minutes if seen is None else max(seen, lst.age_minutes)
            else:
                lst.min_age_minutes = seen
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
