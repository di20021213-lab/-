"""Разовая диагностика вёрстки выдачи Авито: почему не находятся дата и фото.

Открывает твой поиск, прокручивает его и замеряет, что реально есть в разметке
до и после прокрутки. Печатает короткую сводку и кусок разметки одной карточки
без даты — по нему видно, за что цепляться парсеру.

Полный HTML страницы сохраняется рядом (page_dump.html), чтобы можно было
посмотреть глазами, ничего никуда не отправляя.

Запуск:  python dump_page.py            (URL из config.yaml)
         python dump_page.py <url>
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from avito_watcher.probe import url_from_config
from avito_watcher.scraper import AvitoScraper

load_dotenv()

DUMP_PATH = "page_dump.html"

# Что есть в карточках прямо сейчас — считаем одним заходом в браузер.
_STATS_JS = r"""
() => {
  const cards = Array.from(document.querySelectorAll('[data-marker="item"]'));
  const withDateMarker = cards.filter(c => c.querySelector('[data-marker="item-date"]')).length;
  const withTime = cards.filter(c => c.querySelector('time')).length;
  const dateLike = /(только что|сегодня|вчера|назад)/i;
  const withDateText = cards.filter(c => dateLike.test(c.innerText || '')).length;
  const withImgSrc = cards.filter(c => {
    const i = c.querySelector('img');
    if (!i) return false;
    const s = i.getAttribute('src') || '';
    return s && !s.startsWith('data:');
  }).length;
  return {
    cards: cards.length,
    withDateMarker, withTime, withDateText, withImgSrc,
    scrollY: Math.round(window.scrollY),
    innerHeight: window.innerHeight,
    scrollHeight: document.documentElement.scrollHeight,
  };
}
"""

# Разметка первой карточки, в которой нет даты, — по ней и чиним селекторы.
_SAMPLE_JS = r"""
() => {
  const dateLike = /(только что|сегодня|вчера|назад)/i;
  for (const c of document.querySelectorAll('[data-marker="item"]')) {
    if (!dateLike.test(c.innerText || '')) {
      return { html: c.outerHTML, text: (c.innerText || '').replace(/\s+/g, ' ') };
    }
  }
  return null;
}
"""

# Встроенные в страницу данные: если Авито кладёт объявления в JSON, брать их
# оттуда надёжнее любой вёрстки — она меняется, JSON меняется реже.
_JSON_JS = r"""
() => {
  const out = {};
  for (const key of ['__initialData__', '__NEXT_DATA__', '__APP_STATE__']) {
    const v = window[key];
    if (v) out[key] = typeof v === 'string' ? v.length : JSON.stringify(v).length;
  }
  const scripts = Array.from(document.querySelectorAll('script'));
  out.scriptsWithSortTime = scripts.filter(s => (s.textContent || '').includes('sortTimeStamp')).length;
  out.scriptsWithTimeField = scripts.filter(s => /"time"\s*:\s*\d{10}/.test(s.textContent || '')).length;
  return out;
}
"""


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else url_from_config()
    if not url:
        print("Не найден URL: укажи аргументом или заполни searches в config.yaml")
        return 2

    proxy = (os.getenv("PROXY") or "").strip() or None
    print(f"URL: {url}\n")

    with AvitoScraper(headless=True, proxy=proxy,
                      executable_path=os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or None) as s:
        page = s._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=s.timeout_ms)
            page.wait_for_selector('[data-marker="item"]', timeout=15000)

            before = page.evaluate(_STATS_JS)
            s._scroll_through(page)
            after = page.evaluate(_STATS_JS)

            print("                     до прокрутки   после")
            for key, label in (
                ("cards", "карточек на странице"),
                ("withDateMarker", 'с [data-marker=item-date]'),
                ("withTime", "с тегом <time>"),
                ("withDateText", "с текстом даты в карточке"),
                ("withImgSrc", "с реальной картинкой"),
            ):
                print(f"  {label:26} {before[key]:>6}   {after[key]:>6}")

            print(f"\n  высота окна: {after['innerHeight']}, "
                  f"высота страницы: {after['scrollHeight']}")
            # Если после прокрутки страница не выросла и не сдвинулась — значит
            # window.scrollBy её не двигает (сайт скроллит внутренний контейнер).
            print(f"  прокрутка сдвинула страницу: "
                  f"{'да' if after['scrollHeight'] >= before['scrollHeight'] else 'нет'}")

            print(f"\n  встроенные данные: {page.evaluate(_JSON_JS)}")

            sample = page.evaluate(_SAMPLE_JS)
            if sample:
                print("\n=== карточка БЕЗ даты, текст ===")
                print("  " + sample["text"][:400])
                print("\n=== её разметка (первые 1200 символов) ===")
                print(sample["html"][:1200])
            else:
                print("\n  Карточек без даты не нашлось — дата есть везде.")

            with open(DUMP_PATH, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"\nПолный HTML сохранён в {DUMP_PATH}")
        finally:
            page.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
