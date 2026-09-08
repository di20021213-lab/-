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
import sys

import requests
from dotenv import load_dotenv

from avito_watcher.probe import TIMEOUT_S, probe, url_from_config
from avito_watcher.scraper import AntibotError, AvitoScraper

load_dotenv()


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
    result = probe(url, proxy)
    print(f"  {'✓' if result.ok else '✗'} {result.describe()}")
    if not result.ok and not result.markers and not result.error and result.status == 200:
        print("    Блокировки нет, но и объявлений нет: проверь сам URL в браузере.")
    return result.ok


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
