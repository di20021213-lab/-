#!/usr/bin/env python3
"""Проверяет, пускает ли Озон наш браузер, и что удаётся прочитать со страницы.

Сначала замер, потом код. Голому клиенту Озон отдаёт 403 с проверкой — как и
Авито, — поэтому единственный честный тест: открыть страницы тем же браузером,
что и бот, со своего адреса. Отсюда вывод и решение, строить ли слежение.

Запуск:  python ozon_check.py "ссылка" ["ссылка" ...]
         python ozon_check.py --file links.txt

Пауза между ссылками небольшая: у Озона нет частников, разбирающих товар за
10 минут, но и долбить его незачем.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from typing import Optional

from dotenv import load_dotenv

from avito_watcher.scraper import AvitoScraper

load_dotenv()

PAUSE_S = int(os.getenv("OZON_PAUSE_S", "20"))

# Признаки того, что вместо товара нам отдали проверку.
BLOCK_MARKERS = (
    "доступ ограничен", "проверка", "captcha", "challenge",
    "подтвердите, что вы не робот", "access denied",
)

# Сколько ждать цену: страница отдаёт каркас сразу, а цену дорисовывает скриптом.
PRICE_WAIT_MS = 8000

EXTRACT_JS = r"""
() => {
  const out = {title: null, price: null, oldPrice: null, available: null, source: null};

  // 1. JSON-LD. Самый надёжный источник: структурированные данные не зависят
  //    от вёрстки, которую Озон меняет чаще, чем мы успеваем подстраиваться.
  for (const el of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const data = JSON.parse(el.textContent);
      const items = Array.isArray(data) ? data : [data];
      for (const it of items) {
        if (!it || it['@type'] !== 'Product') continue;
        out.title = it.name || out.title;
        const offer = Array.isArray(it.offers) ? it.offers[0] : it.offers;
        if (offer) {
          if (offer.price) { out.price = String(offer.price); out.source = 'json-ld'; }
          if (offer.availability) out.available = /InStock/i.test(offer.availability);
        }
      }
    } catch (e) { /* битый JSON — не повод падать */ }
  }

  if (!out.title) {
    const h1 = document.querySelector('h1');
    const og = document.querySelector('meta[property="og:title"]');
    out.title = (h1 && h1.innerText.trim()) || (og && og.content) || null;
  }

  // 2. Запасной путь — видимая цена в блоке цены.
  if (!out.price) {
    const w = document.querySelector('[data-widget="webPrice"]')
          || document.querySelector('[data-widget="webSale"]');
    const text = w ? w.innerText : document.body.innerText.slice(0, 3000);
    const m = text && text.match(/(\d[\d\s ]{2,})\s*₽/);
    if (m) { out.price = m[1].replace(/[\s ]/g, ''); out.source = 'вёрстка'; }
  }

  out.bodySample = (document.body ? document.body.innerText : '').slice(0, 400);
  return out;
}
"""


def money(value) -> Optional[int]:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value).split(".")[0])
    return int(digits) if digits else None


def check(scraper: AvitoScraper, url: str) -> dict:
    page = scraper._context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=scraper.timeout_ms)
        # Цену рисует скрипт уже после загрузки каркаса — ждём её появления,
        # но не падаем, если не дождались: разберём то, что есть.
        try:
            page.wait_for_selector('[data-widget="webPrice"], script[type="application/ld+json"]',
                                   timeout=PRICE_WAIT_MS)
        except Exception:  # noqa: BLE001
            pass
        data = page.evaluate(EXTRACT_JS)
        data["url"] = page.url
        body = (data.get("bodySample") or "").lower()
        data["blocked"] = any(m in body for m in BLOCK_MARKERS)
        return data
    finally:
        page.close()


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--file":
        urls = [l.strip() for l in open(args[1], encoding="utf-8")
                if l.strip() and not l.lstrip().startswith("#")]
    else:
        urls = args
    if not urls:
        print(__doc__)
        return 2

    proxy = (os.getenv("PROXY") or "").strip() or None
    ok = blocked = 0
    with AvitoScraper(headless=True, proxy=proxy,
                      executable_path=os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or None,
                      user_data_dir=os.getenv("BROWSER_PROFILE_DIR") or None) as scraper:
        for i, url in enumerate(urls, 1):
            if i > 1:
                time.sleep(PAUSE_S + random.uniform(0, 5))
            print(f"\n[{i}/{len(urls)}] {url}")
            try:
                d = check(scraper, url)
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ не открылось: {type(e).__name__}: {e}")
                continue

            if d["blocked"]:
                blocked += 1
                print("  ✗ Озон показал проверку, а не товар")
                print(f"     начало страницы: {(d.get('bodySample') or '')[:160]!r}")
                continue

            price = money(d.get("price"))
            if price:
                ok += 1
                print(f"  ✓ {(d.get('title') or '?')[:70]}")
                print(f"     цена: {price} ₽  (источник: {d.get('source')})"
                      + (f"  · в наличии: {'да' if d['available'] else 'нет'}"
                         if d.get("available") is not None else ""))
            else:
                print(f"  ? страница открылась, но цену не нашёл")
                print(f"     заголовок: {(d.get('title') or '—')[:70]}")
                print(f"     начало страницы: {(d.get('bodySample') or '')[:160]!r}")

    print(f"\n=== ИТОГ: прочитано {ok} из {len(urls)}"
          + (f", заблокировано {blocked}" if blocked else ""))
    if ok == len(urls):
        print("Озон пускает — слежение строить можно.")
    elif ok:
        print("Пускает через раз: либо вёрстка разная, либо лимит. Покажи вывод мне.")
    else:
        print("Не пустил ни разу. Возможно, нужен другой подход — покажи вывод.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
