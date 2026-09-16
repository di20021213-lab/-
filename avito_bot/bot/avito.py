"""Работа с Авито через реальный браузер (Playwright, постоянный профиль).

Логин делается руками один раз (`python login.py`) — пароль бот не знает и
никуда не сохраняет. Дальше используется та же сессия браузера.

Капчу бот не решает и не обходит: увидев её, он останавливается и просит
человека разобраться вручную.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PWTimeout,
    async_playwright,
)


class NeedsLogin(Exception):
    """Сессия протухла — нужен повторный вход руками."""


class NeedsHuman(Exception):
    """Капча или иная проверка. Бот останавливается, дальше — человек."""


@dataclass
class Card:
    title: str = ""
    price: str = ""
    seller: str = ""


CAPTCHA_MARKERS = (
    "[data-marker='captcha']",
    "text=Подтвердите, что вы не робот",
    "text=Доступ ограничен",
    "#h-captcha",
    "iframe[src*='captcha']",
)


class AvitoBrowser:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._pw = None
        self._ctx: BrowserContext | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            self.cfg.get_path("avito.profile_dir", "data/chrome-profile"),
            headless=bool(self.cfg.get_path("avito.headless", False)),
            slow_mo=int(self.cfg.get_path("avito.slow_mo_ms", 0)),
            viewport={"width": 1440, "height": 900},
            locale="ru-RU",
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._ctx.set_default_navigation_timeout(
            int(self.cfg.get_path("avito.nav_timeout_ms", 45000))
        )

    async def close(self) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()

    # -- вспомогательное ---------------------------------------------------
    async def _page(self) -> Page:
        assert self._ctx is not None, "start() не вызван"
        pages = self._ctx.pages
        return pages[0] if pages else await self._ctx.new_page()

    async def _first(self, page: Page, names: list[str], timeout: int = 4000):
        """Первый селектор из списка, который реально есть на странице."""
        for sel in names:
            try:
                loc = page.locator(sel).first
                await loc.wait_for(state="visible", timeout=timeout)
                return loc
            except PWTimeout:
                continue
        return None

    async def _text(self, page: Page, names: list[str]) -> str:
        loc = await self._first(page, names, timeout=2500)
        if not loc:
            return ""
        try:
            return (await loc.inner_text()).strip()
        except Exception:
            return ""

    async def _guard(self, page: Page) -> None:
        for marker in CAPTCHA_MARKERS:
            try:
                if await page.locator(marker).first.is_visible(timeout=600):
                    raise NeedsHuman(f"Похоже на проверку/капчу: {marker}")
            except PWTimeout:
                continue
            except NeedsHuman:
                raise
            except Exception:
                continue

    async def check_logged_in(self) -> bool:
        page = await self._page()
        await page.goto("https://www.avito.ru/profile", wait_until="domcontentloaded")
        await self._guard(page)
        login_btn = await self._first(
            page, self.cfg.selectors("login_marker"), timeout=2500
        )
        return login_btn is None

    # -- основное ----------------------------------------------------------
    async def open_card(self, url: str) -> Card:
        page = await self._page()
        await page.goto(url, wait_until="domcontentloaded")
        await self._guard(page)
        return Card(
            title=await self._text(page, self.cfg.selectors("title")),
            price=await self._text(page, self.cfg.selectors("price")),
            seller=await self._text(page, self.cfg.selectors("seller")),
        )

    async def send_message(self, url: str, text: str, *, dry_run: bool) -> str:
        """Пишет продавцу. Возвращает 'sent' | 'dry_run' | 'no_chat'."""
        page = await self._page()
        if page.url.split("?")[0] != url:
            await page.goto(url, wait_until="domcontentloaded")
        await self._guard(page)

        btn = await self._first(page, self.cfg.selectors("message_button"), timeout=6000)
        if btn is None:
            # у части объявлений чат выключен — только звонок
            return "no_chat"

        await btn.click()
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1.5)
        await self._guard(page)

        if await self._first(page, self.cfg.selectors("login_marker"), timeout=1500):
            raise NeedsLogin("Авито просит войти — сессия истекла")

        field = await self._first(page, self.cfg.selectors("chat_input"), timeout=8000)
        if field is None:
            raise RuntimeError(
                "Не найдено поле ввода чата — вероятно, поменялась вёрстка. "
                "Обновите selectors.chat_input в config.yaml"
            )

        await field.click()
        # печатаем с задержкой, как человек, а не вставляем разом
        await field.type(text, delay=45)

        if dry_run:
            return "dry_run"

        send = await self._first(page, self.cfg.selectors("send_button"), timeout=3000)
        if send is not None:
            await send.click()
        else:
            await field.press("Enter")

        await asyncio.sleep(2.0)
        await self._guard(page)
        return "sent"
