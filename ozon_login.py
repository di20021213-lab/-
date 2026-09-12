#!/usr/bin/env python3
"""Открывает Озон в видимом браузере, чтобы капчу разгадал человек.

Смысл: автоматика капчу не проходит и проходить не должна. Но если ползунок
двигаешь ты сам, дальше сессия живёт в профиле браузера, и проверки идут молча.

ВАЖНО про профиль. Капчу и последующие проверки должен делать ОДИН браузер с
ОДНИМ профилем: сессия привязана не только к кукам, но и к отпечатку. Поэтому
профиль здесь и в ozon_check.py один и тот же (OZON_PROFILE_DIR), и запускать
оба лучше на одном и том же экране.

Запуск (на виртуальном экране, см. deploy/ozon_captcha.sh):
    DISPLAY=:99 python ozon_login.py "https://ozon.ru/t/XXXX"
"""

from __future__ import annotations

import os
import re
import sys
import time

from dotenv import load_dotenv

from avito_watcher.scraper import AvitoScraper
from ozon_check import CAPTCHA_MARKERS, EXTRACT_JS, money

load_dotenv()

PROFILE = os.getenv("OZON_PROFILE_DIR", "ozon-profile")
WAIT_LIMIT_S = int(os.getenv("OZON_SOLVE_TIMEOUT", "900"))
POLL_S = 3


def normalize_url(url: str) -> str | None:
    """Приводит адрес к рабочему виду. None — если это вообще не адрес.

    Ловим самую частую опечатку — потерянное двоеточие («https//ozon.ru»).
    Без проверки Playwright вываливает сорок строк traceback вместо одной
    внятной фразы, и причина тонет.
    """
    url = (url or "").strip().strip('"').strip("'")
    if not url:
        return None
    if url.startswith(("https//", "http//")):
        url = url.replace("//", "://", 1)
    if not url.startswith(("http://", "https://")):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", url, re.I):
            url = "https://" + url
        else:
            return None
    return url


def main() -> int:
    raw = sys.argv[1] if len(sys.argv) > 1 else "https://www.ozon.ru/"
    url = normalize_url(raw)
    if not url:
        print(f"Это не похоже на адрес: {raw!r}\n"
              "Пример: ozon_captcha.bat \"https://ozon.ru/t/l1ZC6Ti\"", file=sys.stderr)
        return 2
    if url != raw.strip():
        print(f"Поправил адрес: {raw}  ->  {url}")
    # На Windows экран есть всегда, проверять нечего. На Linux без DISPLAY
    # видимый браузер показать негде — там нужен виртуальный экран.
    if os.name != "nt" and not os.getenv("DISPLAY"):
        print("Нет DISPLAY — браузер показать негде.\n"
              "Запускай через deploy/ozon_captcha.sh, он поднимет виртуальный экран.",
              file=sys.stderr)
        return 2

    print(f"Профиль: {PROFILE}")
    print(f"Открываю: {url}")
    print("Подключись к экрану и реши капчу руками. Я жду и проверяю каждые "
          f"{POLL_S} с, максимум {WAIT_LIMIT_S // 60} мин.\n")

    with AvitoScraper(headless=False, user_data_dir=PROFILE,
                      executable_path=os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or None,
                      proxy=(os.getenv("PROXY") or "").strip() or None) as scraper:
        page = scraper._context.new_page()
        # Ничего не режем: капча грузит собственные скрипты и картинки.
        page.route("**/*", lambda route: route.continue_())
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=scraper.timeout_ms)
        except Exception as e:  # noqa: BLE001 - показываем суть, а не стек
            print(f"Не смог открыть страницу: {type(e).__name__}", file=sys.stderr)
            print(f"  {str(e).splitlines()[0]}", file=sys.stderr)
            print("  Проверь адрес и что интернет на месте.", file=sys.stderr)
            return 1

        deadline = time.time() + WAIT_LIMIT_S
        while time.time() < deadline:
            try:
                data = page.evaluate(EXTRACT_JS)
            except Exception as e:  # noqa: BLE001 - страница могла перезагрузиться
                time.sleep(POLL_S)
                continue
            body = (data.get("bodySample") or "")
            title = (data.get("title") or "")

            # Пустое тело — это НЕ «капчи нет», а «страница ещё не отрисовалась».
            # Первая версия считала такое успехом и рапортовала о пройденной
            # капче, когда в заголовке ещё стояло «Сопоставьте пазл».
            if not body.strip():
                time.sleep(POLL_S)
                continue

            # Ищем маркеры и в заголовке тоже: у страницы капчи он говорящий,
            # а тело может не успеть наполниться.
            haystack = f"{title} {body}".lower()
            if any(m in haystack for m in CAPTCHA_MARKERS):
                time.sleep(POLL_S)
                continue

            price = money(data.get("price"))
            print("✅ Капча пройдена.")
            if price:
                print(f"   Вижу товар: {(data.get('title') or '?')[:60]} — {price} ₽")
            else:
                print(f"   Заголовок: {(data.get('title') or '?')[:60]}")
            # Персистентный контекст сбрасывает куки на диск при закрытии —
            # именно поэтому важно выйти штатно, а не убить процесс.
            print(f"   Сессия сохранена в {PROFILE}. Закрываю браузер аккуратно.")
            return 0

        print("⏳ Не дождался: капча всё ещё на экране.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
