"""Отправка уведомлений в Telegram через Bot API."""

from __future__ import annotations

import html
import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, proxy: Optional[str] = None) -> None:
        self.token = token
        self.chat_id = chat_id
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

    def _call(self, method: str, payload: dict) -> bool:
        url = API.format(token=self.token, method=method)
        try:
            resp = self.session.post(url, data=payload, timeout=30)
            data = resp.json()
            if not data.get("ok"):
                log.warning("Telegram %s error: %s", method, data.get("description"))
                return False
            return True
        except requests.RequestException as e:
            log.warning("Telegram %s request failed: %s", method, e)
            return False

    def send_message(self, text: str, disable_preview: bool = False) -> bool:
        return self._call(
            "sendMessage",
            {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            },
        )

    def send_listing(self, listing, search_label: str) -> bool:
        """Шлёт карточку объявления. Пытается с фото, при неудаче — обычным текстом."""
        caption = self._format_caption(listing, search_label)

        if listing.image_url:
            ok = self._call(
                "sendPhoto",
                {
                    "chat_id": self.chat_id,
                    "photo": listing.image_url,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
            )
            if ok:
                return True
            # фото не ушло (битая ссылка/лимиты) — падаем в текст

        return self.send_message(caption)

    @staticmethod
    def _format_caption(listing, search_label: str) -> str:
        title = html.escape(listing.title or "Без названия")
        parts = [f"🎮 <b>{html.escape(search_label)}</b>", "", f"<b>{title}</b>"]
        if listing.price:
            parts.append(f"💰 {html.escape(str(listing.price))}")
        if listing.location:
            parts.append(f"📍 {html.escape(listing.location)}")
        if listing.date_text:
            parts.append(f"🕒 {html.escape(listing.date_text)}")
        if listing.url:
            parts.append("")
            parts.append(f'🔗 <a href="{html.escape(listing.url)}">Открыть на Авито</a>')
        return "\n".join(parts)
