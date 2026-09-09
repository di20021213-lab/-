"""Отправка уведомлений в Telegram через Bot API."""

from __future__ import annotations

import html
import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.telegram.org"

# Ограничение Telegram на фото по URL/файлом.
MAX_PHOTO_BYTES = 10 * 1024 * 1024
# CDN Авито охотнее отдаёт картинку браузеру, чем безымянному клиенту.
IMAGE_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str,
        proxy: Optional[str] = None,
        api_base: Optional[str] = None,
        image_proxy: Optional[str] = None,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        # Базу API можно переопределить: Bot API-прокси / локальный сервер (актуально при блокировках).
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        # Отдельный маршрут для картинок: они лежат на CDN Авито, и тянуть их
        # через туннель для Telegram нельзя — туда ходит только Bot API.
        self.image_proxies = ({"http": image_proxy, "https": image_proxy}
                              if image_proxy else None)
        # Telegram умеет скачать фото по ссылке сам, но CDN Авито ему не отдаёт.
        # Убедившись в этом один раз, больше не пробуем: лишний запрос на каждое
        # объявление и тревожное WARNING в логе на ровном месте.
        self._photo_by_url = True

    def _call(self, method: str, payload: dict, files: Optional[dict] = None,
              quiet: bool = False) -> bool:
        url = f"{self.api_base}/bot{self.token}/{method}"
        try:
            # Загрузка файла идёт дольше обычного вызова, поэтому таймаут больше.
            resp = self.session.post(url, data=payload, files=files,
                                     timeout=90 if files else 30)
            data = resp.json()
            if not data.get("ok"):
                # quiet — для ожидаемых отказов, у которых есть запасной путь.
                (log.info if quiet else log.warning)(
                    "Telegram %s error: %s", method, data.get("description"))
                return False
            return True
        except (requests.RequestException, ValueError) as e:
            # ValueError — Telegram вернул не-JSON (например, HTML-страницу 502).
            log.warning("Telegram %s request failed: %s", method, e)
            return False

    def check(self) -> Optional[str]:
        """Проверяет токен через getMe. Возвращает @username бота или None."""
        try:
            resp = self.session.post(f"{self.api_base}/bot{self.token}/getMe", timeout=30)
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("Telegram getMe failed: %s", e)
            return None
        if not data.get("ok"):
            log.warning("Telegram getMe error: %s", data.get("description"))
            return None
        return (data.get("result") or {}).get("username") or "?"

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

    def send_listing(self, listing, search_label: str, warning: Optional[str] = None,
                     unchecked: bool = False) -> bool:
        """Шлёт карточку объявления. Пытается с фото, при неудаче — обычным текстом.

        warning — найденный признак неисправности; добавляется в карточку как пометка ⚠️.
        unchecked — описание прочитать не удалось, проверка на неисправность неполная.
        """
        caption = self._format_caption(listing, search_label, warning, unchecked)

        if listing.image_url:
            payload = {"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"}

            # Пока не доказано обратное — просто передаём ссылку: так дешевле,
            # картинку качает сам Telegram.
            if self._photo_by_url:
                if self._call("sendPhoto", {**payload, "photo": listing.image_url},
                              quiet=True):
                    return True
                self._photo_by_url = False
                log.info("Telegram не берёт фото по ссылке, дальше отправляю файлом")

            # Качаем сами — у нас-то доступ к Авито есть — и шлём файлом.
            content = self._download_image(listing.image_url)
            if content and self._call("sendPhoto", payload,
                                      files={"photo": ("photo.jpg", content)}):
                return True
            log.info("Фото не ушло, отправляю текстом: %s", listing.image_url)

        return self.send_message(caption)

    def _download_image(self, url: str) -> Optional[bytes]:
        """Скачивает картинку объявления. None — если не вышло."""
        try:
            resp = requests.get(url, timeout=30, proxies=self.image_proxies,
                                headers={"User-Agent": IMAGE_USER_AGENT})
        except requests.RequestException as e:
            log.info("Не смог скачать картинку (%s): %s", e, url)
            return None
        if not resp.ok:
            log.info("Картинка отдалась с HTTP %s: %s", resp.status_code, url)
            return None
        # Telegram принимает фото до 10 МБ; превью из выдачи заметно меньше,
        # так что превышение размера означает, что скачалось что-то не то.
        if not resp.content or len(resp.content) > MAX_PHOTO_BYTES:
            log.info("Картинка неподходящего размера (%d байт): %s", len(resp.content), url)
            return None
        return resp.content

    @staticmethod
    def _format_caption(listing, search_label: str, warning: Optional[str] = None,
                        unchecked: bool = False) -> str:
        title = html.escape(listing.title or "Без названия")
        parts = [f"🎮 <b>{html.escape(search_label)}</b>", "", f"<b>{title}</b>"]
        if warning:
            parts.append(f"⚠️ <b>Возможно неисправна:</b> «{html.escape(warning)}»")
        elif unchecked:
            # Молчать тут нельзя: иначе непрочитанное описание выглядит как чистое.
            parts.append("⚠️ <i>Описание прочитать не удалось — проверь сам</i>")
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
