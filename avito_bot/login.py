"""Разовый вход на Авито руками. Пароль вводите вы, бот его не видит."""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from bot.avito import AvitoBrowser
from bot.config import load_config


async def amain() -> None:
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
    cfg.setdefault("avito", {})["headless"] = False        # логин только с окном
    browser = AvitoBrowser(cfg)
    await browser.start()

    page = await browser._page()
    await page.goto("https://www.avito.ru/profile/login")
    print(
        "\nОткрылось окно браузера.\n"
        "1) Войдите в свой аккаунт Авито (включая код из SMS, если спросят).\n"
        "2) Дождитесь, пока откроется профиль.\n"
        "3) Вернитесь сюда и нажмите Enter.\n"
    )
    await asyncio.get_running_loop().run_in_executor(None, input, "Готово? Enter: ")

    ok = await browser.check_logged_in()
    print("✅ Сессия сохранена, можно запускать main.py" if ok
          else "❌ Войти не удалось — попробуйте ещё раз")
    await browser.close()


if __name__ == "__main__":
    asyncio.run(amain())
