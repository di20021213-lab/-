"""Диагностика доступа к Авито: где именно нас блокируют.

Отвечает на один вопрос: дело в IP или в браузере?

  1. Простой HTTP-запрос (как curl) — проверяет сам IP.
  2. Тот же URL через Playwright/Chromium — проверяет отпечаток браузера.

Расклад результатов:
  оба ОК            — всё работает, можно запускать бота;
  оба заблокированы — забанен/лимитирован IP, браузер ни при чём;
  HTTP ОК, браузер нет — Авито узнаёт автоматизацию, чиним отпечаток.

Запуск:  python diag.py            (URL берётся из config.yaml)
         python diag.py <url>      (проверить конкретный URL)
"""

from __future__ import annotations

import os
import re
import sys

import requests
import yaml
from dotenv import load_dotenv

from avito_watcher.scraper import ANTIBOT_MARKERS, AntibotError, AvitoScraper

load_dotenv()

TIMEOUT_S = 30

# Тот же набор заголовков, что шлёт обычный десктопный Chrome.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
}


def _decode(resp: requests.Response) -> str:
    """Текст ответа в правильной кодировке.

    requests, не найдя charset в заголовке Content-Type, берёт ISO-8859-1 —
    и русский текст превращается в мусор. Тогда проверка на «Доступ ограничен»
    молча промахивается и диагностика врёт. Поэтому без charset — utf-8.
    """
    if "charset" not in (resp.headers.get("Content-Type") or "").lower():
        resp.encoding = "utf-8"
    return resp.text


def url_from_config(path: str = "config.yaml") -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except OSError:
        return None
    searches = raw.get("searches") or []
    return (searches[0].get("url") or "").strip() or None if searches else None


def show_ip(proxy: str | None) -> None:
    """С какого IP нас видит интернет. Ради этого и покупали домашний адрес."""
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        ip = requests.get("https://api.ipify.org", timeout=TIMEOUT_S, proxies=proxies).text
        print(f"  Внешний IP: {ip}")
    except requests.RequestException as e:
        print(f"  Внешний IP: не смог определить ({e})")


def check_http(url: str, proxy: str | None) -> bool:
    """Простой HTTP-запрос. Проверяет IP, отпечаток браузера тут ни при чём."""
    print("\n[1/2] Простой HTTP-запрос (проверяем IP)")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S, proxies=proxies)
    except requests.RequestException as e:
        print(f"  ✗ Запрос не прошёл: {e}")
        return False

    body = _decode(resp)
    items = len(re.findall(r'data-marker="item"', body))
    lowered = body[:20000].lower()
    hits = [m for m in ANTIBOT_MARKERS if m in lowered]

    print(f"  HTTP {resp.status_code}, страница {len(body)} байт, объявлений в HTML: {items}")
    if hits:
        # Страницу «Доступ ограничен» Авито отдаёт с кодом 200, так что
        # ориентироваться только на статус нельзя.
        print(f"  ✗ Это страница блокировки (нашёл: {', '.join(hits)})")
        return False
    if resp.status_code == 429:
        print("  ✗ HTTP 429: лимит запросов с этого IP. Снимается только паузой.")
        return False
    if resp.status_code >= 400:
        print(f"  ✗ HTTP {resp.status_code}")
        return False
    if items == 0:
        print("  ? Блокировки нет, но и объявлений нет: проверь сам URL в браузере.")
        return False
    print("  ✓ IP проходит, выдача отдаётся")
    return True


def check_browser(url: str, proxy: str | None) -> bool:
    """Тот же URL через Chromium. Если HTTP прошёл, а это нет — дело в отпечатке."""
    print("\n[2/2] Через Chromium (проверяем отпечаток браузера)")
    headless = (os.getenv("HEADLESS") or "true").strip().lower() not in {"0", "false", "no"}
    try:
        with AvitoScraper(
            headless=headless,
            proxy=proxy,
            executable_path=os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or None,
        ) as scraper:
            listings = scraper._fetch_once(url)  # без повторов: нужен честный первый ответ
    except AntibotError as e:
        print(f"  ✗ {e}")
        return False
    except Exception as e:  # noqa: BLE001 - показать пользователю любую поломку
        print(f"  ✗ Не смог открыть страницу: {e}")
        return False

    print(f"  ✓ Страница открылась, объявлений: {len(listings)}")
    for lst in listings[:3]:
        print(f"      · {lst.price or '—':>12}  {(lst.title or '')[:60]}")
    return len(listings) > 0


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else url_from_config()
    if not url:
        print("Не найден URL: укажи его аргументом или заполни searches в config.yaml")
        return 2

    proxy = (os.getenv("PROXY") or "").strip() or None
    print(f"URL: {url}")
    print(f"  Прокси для Авито: {proxy or 'нет (напрямую)'}")
    show_ip(proxy)

    http_ok = check_http(url, proxy)
    browser_ok = check_browser(url, proxy)

    print("\n" + "=" * 60)
    if http_ok and browser_ok:
        print("Всё проходит. Можно запускать бота: sudo systemctl start avito-watcher")
        return 0
    if not http_ok and not browser_ok:
        print("Заблокирован сам IP — браузер ни при чём.")
        print("Подожди 15-30 минут без запросов и проверь снова.")
        print("Если не отпускает — этот адрес попал под лимит надолго, нужен другой IP.")
        return 1
    if http_ok and not browser_ok:
        print("IP чистый, но Chromium не пускают: Авито узнаёт автоматизацию.")
        print("Пришли этот вывод — поменяю движок браузера в коде.")
        return 1
    print("Странный расклад: браузер прошёл, а простой запрос нет. Пришли вывод целиком.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
