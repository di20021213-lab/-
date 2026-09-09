"""Диагностика доступа к Авито: заработает ли бот и что мешает.

  1. Простой HTTP-запрос — справочно.
  2. Тот же URL через Playwright/Chromium — РЕШАЮЩАЯ проверка.

Решает именно вторая: бот ходит браузером, и только её результат отвечает на
вопрос «заработает ли он». Простой запрос сам по себе выглядит подозрительно
для Авито (TLS-отпечаток, нет куков и JS), поэтому его отказ ничего не
доказывает — ни про IP, ни про что-либо ещё. А вот если он ПРОШЁЛ, значит
адрес точно чист, и тогда виноват отпечаток браузера.

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
    """Простой HTTP-запрос. Справочно: его отказ ничего не доказывает."""
    print("\n[1/2] Простой HTTP-запрос (справочно)")
    result = probe(url, proxy)
    print(f"  {'✓' if result.ok else '✗'} {result.describe()}")
    if not result.ok:
        print("    Это нормально: голый HTTP-запрос Авито отклоняет сам по себе,")
        print("    без куков и JS. Вывод делаем по следующей проверке.")
    if not result.ok and not result.markers and not result.error and result.status == 200:
        print("    Блокировки нет, но и объявлений нет: проверь сам URL в браузере.")
    return result.ok


def check_browser(url: str, proxy: str | None) -> bool:
    """Тот же URL через Chromium — то есть ровно так, как ходит бот."""
    print("\n[2/2] Через Chromium (решающая проверка — так ходит бот)")
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
    # Решает браузер: именно им ходит бот. Простой запрос — только уточнение.
    if browser_ok:
        print("Авито пускает браузер — бот заработает.")
        print("Запускай: sudo systemctl start avito-watcher")
        if not http_ok:
            print("(Отказ простого запроса выше — ожидаемо и ни на что не влияет.)")
        return 0
    if http_ok:
        print("Адрес точно чист: простой запрос прошёл, а Chromium не пускают.")
        print("Значит Авито узнаёт автоматизацию — пришли этот вывод, поменяю движок.")
        return 1
    print("Не проходит ни браузер, ни простой запрос.")
    print("Похоже на лимит по IP: подожди 20-30 минут БЕЗ запросов и проверь снова.")
    print("Не отпускает — смени адрес (перезагрузи роутер) или задай PROXY в .env.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
