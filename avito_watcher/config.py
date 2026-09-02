"""Загрузка конфигурации: поиски из config.yaml, секреты из .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ConfigError(Exception):
    """Ошибка конфигурации, понятная пользователю."""


@dataclass
class SearchConfig:
    label: str
    url: str
    max_price: Optional[int] = None
    min_price: Optional[int] = None
    keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)


@dataclass
class Settings:
    telegram_token: str
    telegram_chat_id: str
    searches: list[SearchConfig]
    poll_interval_min: int = 90
    poll_interval_max: int = 180
    headless: bool = True
    proxy: Optional[str] = None
    db_path: str = "seen.sqlite3"
    max_notifications_per_cycle: int = 15
    request_timeout_ms: int = 45000
    user_agent: str = DEFAULT_USER_AGENT
    executable_path: Optional[str] = None
    telegram_api_base: Optional[str] = None


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value, default: int, name: str = "значение") -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"'{name}' должно быть целым числом, получено: {value!r}") from None


def _as_opt_int(value, name: str) -> Optional[int]:
    """Необязательное целое (цена): None/пусто -> None, иначе int или ConfigError."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"'{name}' должно быть целым числом, получено: {value!r}") from None


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Читает config.yaml + переменные окружения и валидирует их."""
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(
            f"Не найден файл конфигурации '{config_path}'. "
            "Скопируй config.example.yaml -> config.yaml и заполни свои поиски."
        )

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    raw_searches = raw.get("searches") or []
    if not raw_searches:
        raise ConfigError("В config.yaml не задан ни один поиск (секция 'searches').")

    searches: list[SearchConfig] = []
    for i, item in enumerate(raw_searches):
        url = (item.get("url") or "").strip()
        if not url:
            raise ConfigError(f"У поиска #{i + 1} не указан 'url'.")
        label = (item.get("label") or f"search-{i + 1}").strip()
        searches.append(
            SearchConfig(
                label=label,
                url=url,
                max_price=_as_opt_int(item.get("max_price"), f"{label}.max_price"),
                min_price=_as_opt_int(item.get("min_price"), f"{label}.min_price"),
                keywords=[str(k).lower() for k in (item.get("keywords") or [])],
                exclude_keywords=[str(k).lower() for k in (item.get("exclude_keywords") or [])],
            )
        )

    s = raw.get("settings") or {}

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token:
        raise ConfigError(
            "Не задан TELEGRAM_BOT_TOKEN. Скопируй .env.example -> .env и вставь токен от @BotFather."
        )
    if not chat_id:
        raise ConfigError(
            "Не задан TELEGRAM_CHAT_ID. Запусти `python get_chat_id.py`, напиши боту, "
            "и вставь полученный chat_id в .env."
        )

    interval_min = _as_int(os.getenv("POLL_INTERVAL_MIN"),
                           _as_int(s.get("poll_interval_min"), 90, "poll_interval_min"),
                           "POLL_INTERVAL_MIN")
    interval_max = _as_int(os.getenv("POLL_INTERVAL_MAX"),
                           _as_int(s.get("poll_interval_max"), 180, "poll_interval_max"),
                           "POLL_INTERVAL_MAX")
    if interval_max < interval_min:
        interval_max = interval_min

    return Settings(
        telegram_token=token,
        telegram_chat_id=chat_id,
        searches=searches,
        poll_interval_min=interval_min,
        poll_interval_max=interval_max,
        headless=_as_bool(os.getenv("HEADLESS"), _as_bool(s.get("headless"), True)),
        proxy=(os.getenv("PROXY") or s.get("proxy") or None) or None,
        db_path=os.getenv("DB_PATH") or s.get("db_path") or "seen.sqlite3",
        max_notifications_per_cycle=_as_int(s.get("max_notifications_per_cycle"), 15,
                                            "max_notifications_per_cycle"),
        request_timeout_ms=_as_int(s.get("request_timeout_ms"), 45000, "request_timeout_ms"),
        user_agent=(s.get("user_agent") or DEFAULT_USER_AGENT),
        executable_path=(os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or s.get("executable_path") or None) or None,
        telegram_api_base=(os.getenv("TELEGRAM_API_BASE") or "").strip() or None,
    )
