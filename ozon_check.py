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

# Профиль общий с ozon_login.py: сессия, добытая человеком, лежит именно там.
PROFILE = os.getenv("OZON_PROFILE_DIR", "ozon-profile")
# Если капчу проходил человек, проверки надо гонять тем же видимым браузером:
# в headless отпечаток другой, и сессия не признаётся.
HEADLESS = (os.getenv("OZON_HEADLESS", "1").strip().lower()
            not in {"0", "false", "no", "нет"})

# Признаки того, что вместо товара нам отдали заглушку.
# «Ой, что-то пошло не так. Обновите страницу» — это и есть антибот Озона.
# Выглядит как случайный сбой, поэтому его легко принять за проблему разбора:
# первая версия так и сделала и отчиталась невнятным «цену не нашёл».
BLOCK_MARKERS = (
    "что-то пошло не так", "обновите страницу",
    # Капча-ползунок. Список знал «не робот», а Озон пишет «не бот» — из-за
    # одного слова отчёт вышел невнятным там, где всё было предельно ясно.
    "сопоставьте пазл", "подтвердите, что вы не бот",
    "подтвердите, что вы не робот",
    "доступ ограничен", "captcha", "challenge", "access denied",
)

# Капчу отличаем от обычной заглушки: перезагружать её бессмысленно, а вывод
# должен называть вещи своими именами.
CAPTCHA_MARKERS = ("сопоставьте пазл", "не бот", "не робот", "captcha")

# Сколько раз перезагрузить страницу, наткнувшись на заглушку. Настоящий
# человек в такой ситуации жмёт «Обновить», и иногда этого достаточно.
RELOAD_TRIES = 3
RELOAD_PAUSE_S = 6

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


def check(scraper: AvitoScraper, url: str, full_resources: bool = True) -> dict:
    page = scraper._context.new_page()
    if full_resources:
        # Правило страницы перекрывает правило контекста, где картинки, шрифты
        # и счётчики режутся ради экономии запросов к Авито. Озону это может
        # выйти боком: свои проверки он грузит как раз такими файлами, и,
        # обрезая их, мы сами напрашиваемся на заглушку.
        page.route("**/*", lambda route: route.continue_())
    try:
        for attempt in range(1, RELOAD_TRIES + 1):
            if attempt == 1:
                page.goto(url, wait_until="domcontentloaded", timeout=scraper.timeout_ms)
            else:
                time.sleep(RELOAD_PAUSE_S)
                page.reload(wait_until="domcontentloaded", timeout=scraper.timeout_ms)
            # Цену рисует скрипт уже после каркаса — ждём, но не падаем.
            try:
                page.wait_for_selector(
                    '[data-widget="webPrice"], script[type="application/ld+json"]',
                    timeout=PRICE_WAIT_MS)
            except Exception:  # noqa: BLE001
                pass
            data = page.evaluate(EXTRACT_JS)
            data["url"] = page.url
            data["attempts"] = attempt
            body = (data.get("bodySample") or "").lower()
            data["blocked"] = any(m in body for m in BLOCK_MARKERS)
            data["captcha"] = any(m in body for m in CAPTCHA_MARKERS)
            if not data["blocked"] or data["captcha"]:
                # Капчу перезагрузкой не проймёшь — незачем ходить лишний раз.
                return data
            if attempt < RELOAD_TRIES:
                print(f"     заглушка, обновляю страницу ({attempt}/{RELOAD_TRIES - 1})")
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
    print(f"Профиль: {PROFILE}  ·  браузер: {'скрытый' if HEADLESS else 'видимый'}")
    with AvitoScraper(headless=HEADLESS, proxy=proxy,
                      executable_path=os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or None,
                      user_data_dir=PROFILE) as scraper:
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
                if d.get("captcha"):
                    print("  ✗ КАПЧА: Озон просит доказать, что ты не бот")
                else:
                    print(f"  ✗ Озон показал заглушку (попыток: {d.get('attempts', 1)})")
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
        print("Не пустил ни разу, даже с перезагрузками и всеми ресурсами.")
        print("Это осознанная защита Озона от автоматики, а не наша ошибка.")
        print("Разгадывать капчу за тебя — ни кодом, ни платным сервисом — я не буду.")
        print()
        print("Что работает вместо этого: у Озона есть своё отслеживание цены.")
        print("Добавь товар в избранное и включи уведомление о снижении цены —")
        print("пуш придёт от самого Озона, без парсинга и без капчи.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
