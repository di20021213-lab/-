#!/usr/bin/env python3
"""Сравнивает несколько вариантов ссылки на поиск Авито: какая что отдаёт.

Нужен, когда выдача пуста и непонятно, какой параметр её убивает — раздел,
цена, сортировка. Открывает каждый URL по очереди тем же браузером, что и бот,
и печатает, сколько объявлений вернулось и по каким ценам.

Между вариантами делает паузу: несколько загрузок подряд с одного адреса —
верный способ получить 429 и померить вместо выдачи собственную блокировку.

Запуск:  python try_urls.py "url1" "url2" ...
"""

from __future__ import annotations

import os
import sys
import time

from dotenv import load_dotenv

from avito_watcher.scraper import AntibotError, AvitoScraper

load_dotenv()

PAUSE_S = 25


def main() -> int:
    urls = sys.argv[1:]
    if not urls:
        print(__doc__)
        return 2

    proxy = (os.getenv("PROXY") or "").strip() or None
    with AvitoScraper(headless=True, proxy=proxy,
                      executable_path=os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or None,
                      user_data_dir=os.getenv("BROWSER_PROFILE_DIR") or None) as scraper:
        for i, url in enumerate(urls, 1):
            if i > 1:
                time.sleep(PAUSE_S)
            print(f"\n[{i}/{len(urls)}] {url}")
            try:
                listings = scraper._fetch_once(url)
            except AntibotError as e:
                print(f"  ✗ {e}")
                continue
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ не открылось: {e}")
                continue

            prices = [x.price_value for x in listings if x.price_value is not None]
            print(f"  объявлений: {len(listings)}", end="")
            if prices:
                print(f", цены от {min(prices)} до {max(prices)} ₽")
            else:
                print()
            for lst in listings[:5]:
                price = f"{lst.price_value} ₽" if lst.price_value is not None else "—"
                print(f"      {price:>9}  {(lst.title or '')[:58]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
