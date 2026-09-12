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
import sys
import time

from dotenv import load_dotenv

from avito_watcher.scraper import AvitoScraper
from ozon_check import CAPTCHA_MARKERS, EXTRACT_JS, money

load_dotenv()

PROFILE = os.getenv("OZON_PROFILE_DIR", "ozon-profile")
WAIT_LIMIT_S = int(os.getenv("OZON_SOLVE_TIMEOUT", "900"))
POLL_S = 3


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.ozon.ru/"
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
        page.goto(url, wait_until="domcontentloaded", timeout=scraper.timeout_ms)

        deadline = time.time() + WAIT_LIMIT_S
        while time.time() < deadline:
            try:
                data = page.evaluate(EXTRACT_JS)
            except Exception as e:  # noqa: BLE001 - страница могла перезагрузиться
                time.sleep(POLL_S)
                continue
            body = (data.get("bodySample") or "").lower()
            if any(m in body for m in CAPTCHA_MARKERS):
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
