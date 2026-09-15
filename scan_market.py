#!/usr/bin/env python3
"""Разведка рынка: что из списка игр вообще водится на Авито и почём.

Зачем. Выбирать, за чем следить, по памяти — способ, которым мы уже дважды
промахнулись: потолки для видеокарт были выставлены из головы, все оказались
ниже рынка, и из сотни объявлений прошло три. Этот скрипт заменяет догадку
измерением: обходит названия, собирает всё, что по ним есть, и показывает, где
есть смысл сидеть в засаде.

    .venv/bin/python scan_market.py games.example.txt     — прочесать (долго, см. ниже)
    .venv/bin/python scan_market.py --report              — отчёт, к Авито не ходит

Именно .venv/bin/python, а не python3: зависимости стоят в окружении проекта,
системный питон о них не знает. Ошибёшься — скрипт скажет об этом по-русски,
а не трассировкой.

ПРО ВРЕМЯ. Быстро не получится, и это не лень скрипта. Домашний адрес за CGNAT
терпит примерно один заход в 10-18 минут — измерено по журналу бота. Двадцать
пять названий это 4-7 часов. Поэтому обход идёт неспешно, пишет результат после
каждого названия и умеет продолжать с места обрыва: прервать можно в любой
момент, потом запустить снова.

ПРО БОТА. На время обхода скрипт ставит PAUSE.flag, и бот перестаёт ходить к
Авито: иначе они делят один и тот же бюджет адреса и мешают друг другу. Флаг
снимается на выходе, а если скрипт убьют — протухает сам через час.

ЧЕГО ЭТОТ ОТЧЁТ НЕ ЗНАЕТ. Цены здесь — то, что ПРОСЯТ, а не то, за сколько
уходит. Объявление может висеть полгода с ценой втрое выше рынка и попасть в
статистику наравне с настоящей сделкой. Поэтому «медиана» тут — ориентир, а не
истина, и решение всё равно за тобой.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

try:
    import yaml
    from dotenv import load_dotenv

    from avito_watcher.paths import app_dir, resolve, setup_bundled_browsers
    from avito_watcher.scraper import AntibotError, AvitoScraper
    from make_searches import QUERY_SUFFIX, URL_TEMPLATE, read_titles
except ImportError as _e:  # запущено не тем питоном
    from avito_watcher.paths import venv_hint
    raise SystemExit(venv_hint(_e))

load_dotenv(app_dir() / ".env")

DB_PATH = "market.sqlite3"
PAUSE_FILE = "PAUSE.flag"

# Пауза между названиями. По умолчанию как у бота: реже — дольше ждать,
# чаще — упрёмся в 429 и станет только дольше.
DELAY_MIN_S = 600
DELAY_MAX_S = 1080

# Блокировка снимается только временем без запросов. Ждём столько же, сколько
# ждёт бот, и удваиваем при повторе.
BLOCKED_PAUSE_S = 1200
BLOCKED_PAUSE_MAX_S = 6 * 3600

# Название, прочёсанное меньше этого времени назад, пропускаем — чтобы
# повторный запуск продолжал обход, а не начинал его заново.
FRESH_ENOUGH_S = 20 * 3600

# Сколько раз повторить название, упёршееся в блокировку, прежде чем отложить
# его до следующего запуска. Пауза всё равно отсижена — разумнее потратить её
# на то же название, чем идти дальше и получить отказ снова.
BLOCKED_RETRIES = 3

# Бот пишет сюда время последнего захода к Авито. Мы читаем то же самое:
# если он ходил только что, бюджет адреса уже занят, и первый же наш запрос
# схватит 429 — ровно это и случилось на первом живом запуске.
LAST_CYCLE_KEY = "last_cycle_at"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listing (
    game       TEXT NOT NULL,
    item_id    TEXT NOT NULL,
    title      TEXT,
    price      INTEGER,
    location   TEXT,
    age_min    INTEGER,
    seen_at    REAL NOT NULL,
    PRIMARY KEY (game, item_id)
);
CREATE TABLE IF NOT EXISTS scan (
    game       TEXT PRIMARY KEY,
    done_at    REAL NOT NULL,
    found      INTEGER NOT NULL,
    note       TEXT
);
"""


def plural(n: int, one: str, few: str, many: str) -> str:
    """«1 объявление, 2 объявления, 5 объявлений». Отчёт читают глазами."""
    if n % 100 // 10 == 1:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(n % 10, many)


def ads(n: int) -> str:
    return f"{n} {plural(n, 'объявление', 'объявления', 'объявлений')}"


def open_db(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def url_for(title: str, region: str) -> str:
    from urllib.parse import quote
    return URL_TEMPLATE.format(region=region,
                               query=quote(f"{title} {QUERY_SUFFIX}".lower(), safe=""))


def browser_settings() -> dict:
    """Настройки браузера из config.yaml, если он есть.

    Читаем сырым yaml, а не load_settings: тот требует непустую секцию
    searches, а на момент разведки её как раз ещё нет — мы её и собираемся
    наполнить по результатам.
    """
    cfg = Path(resolve("config.yaml"))
    raw = {}
    if cfg.is_file():
        with cfg.open(encoding="utf-8") as f:
            raw = (yaml.safe_load(f) or {}).get("settings") or {}
    return {
        "headless": bool(raw.get("headless", True)),
        "proxy": os.getenv("PROXY") or raw.get("proxy") or None,
        "user_agent": raw.get("user_agent") or None,
        "timeout_ms": int(raw.get("request_timeout_ms", 45000)),
        # Тот же профиль, что у бота: те же куки, тот же отпечаток. Запускать
        # одновременно с ботом всё равно нельзя — не даст PAUSE.flag.
        "user_data_dir": resolve(raw.get("user_data_dir") or "browser-profile"),
    }


def wait_out_bot(delay_min: int) -> None:
    """Переждать, если бот ходил к Авито совсем недавно.

    Флаг паузы останавливает бота, но не отменяет уже сделанного им запроса.
    Стартовать сразу после его цикла — значит гарантированно получить 429 на
    первом же названии.
    """
    db_path = Path(resolve("seen.sqlite3"))
    if not db_path.is_file():
        return
    try:
        con = sqlite3.connect(db_path)
        row = con.execute("SELECT value FROM meta WHERE key = ?",
                          (LAST_CYCLE_KEY,)).fetchone()
        con.close()
    except sqlite3.Error:
        return
    if not row:
        return
    try:
        last = float(row[0])
    except (TypeError, ValueError):
        return
    left = delay_min - (time.time() - last)
    if left > 0:
        print(f"Бот ходил к Авито {(time.time() - last) / 60:.0f} мин назад. "
              f"Жду {left / 60:.0f} мин, иначе первый же заход поймает 429.")
        time.sleep(left)


def scan(titles, db: sqlite3.Connection, region: str, delay: tuple[int, int],
         force: bool) -> int:
    import random

    pause = Path(resolve(PAUSE_FILE))
    setup_bundled_browsers()
    done = 0
    blocked_pause = BLOCKED_PAUSE_S

    todo = []
    for title, _top, _bottom in titles:
        row = db.execute("SELECT done_at FROM scan WHERE game = ?", (title,)).fetchone()
        if row and not force and time.time() - row[0] < FRESH_ENOUGH_S:
            print(f"· {title}: прочёсано недавно, пропускаю")
            continue
        todo.append(title)

    if not todo:
        print("\nВсё уже прочёсано. Отчёт: .venv/bin/python scan_market.py --report")
        return 0

    est_lo = len(todo) * delay[0] / 3600
    est_hi = len(todo) * delay[1] / 3600
    word = plural(len(todo), "название", "названия", "названий")
    print(f"\nК обходу: {len(todo)} {word}. Это примерно {est_lo:.1f}-{est_hi:.1f} ч.")
    print("Прервать можно в любой момент — продолжит с того же места.\n")

    try:
        pause.touch()
        wait_out_bot(delay[0])
        with AvitoScraper(**browser_settings()) as scraper:
            for i, title in enumerate(todo, 1):
                pause.touch()   # держим бота в стороне, пока идём
                url = url_for(title, region)
                listings = None
                for attempt in range(1, BLOCKED_RETRIES + 1):
                    try:
                        listings = scraper.fetch(url)
                        blocked_pause = BLOCKED_PAUSE_S
                        break
                    except AntibotError as e:
                        print(f"  ✗ {title}: {e}")
                        if attempt == BLOCKED_RETRIES:
                            print("    Три попытки подряд в отказ. Откладываю: "
                                  "прочёсанным не отмечено, следующий запуск "
                                  "подхватит.")
                            break
                        print(f"    Пауза {blocked_pause / 60:.0f} мин — лимит снимается "
                              f"только временем без запросов. Потом повторю это же "
                              f"название (попытка {attempt + 1} из {BLOCKED_RETRIES}).")
                        pause.touch()
                        time.sleep(blocked_pause)
                        blocked_pause = min(blocked_pause * 2, BLOCKED_PAUSE_MAX_S)
                    except Exception as e:  # noqa: BLE001 - одно сбойное название не должно ронять обход
                        print(f"  ✗ {title}: не получилось ({e})")
                        break
                if listings is None:
                    continue

                now = time.time()
                rows = [(title, l.id, l.title, l.price_value, l.location,
                         l.age_minutes, now) for l in listings]
                db.executemany(
                    "INSERT OR REPLACE INTO listing "
                    "(game, item_id, title, price, location, age_min, seen_at) "
                    "VALUES (?,?,?,?,?,?,?)", rows)
                db.execute("INSERT OR REPLACE INTO scan (game, done_at, found, note) "
                           "VALUES (?,?,?,?)", (title, now, len(rows), None))
                db.commit()
                done += 1

                prices = sorted(x.price_value for x in listings if x.price_value)
                money = (f", цены {prices[0]}-{prices[-1]} ₽" if prices else ", цен нет")
                print(f"  ✓ {title}: {ads(len(listings))}{money}   [{i}/{len(todo)}]")

                if i < len(todo):
                    wait = random.uniform(*delay)
                    print(f"    пауза {wait / 60:.0f} мин…")
                    time.sleep(wait)
    finally:
        pause.unlink(missing_ok=True)

    return done


def median(values: list[int]) -> int:
    if not values:
        return 0
    n = len(values)
    return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) // 2


def verdict(count: int, prices: list[int]) -> str:
    """Стоит ли за этим следить. Это эвристика, а не приговор.

    Ищем сочетание «появляется, но редко» + «цены разнятся». Разброс важнее
    самой цены: если все просят одинаково, купить дешевле рынка не выйдет, а
    вот там, где минимум заметно ниже середины, кто-то не знает цену — и это
    ровно то, что бот должен ловить.
    """
    if count == 0:
        return "не встречается — следить не за чем"
    if not prices:
        return "цены не указаны, судить не по чему"
    lo, mid = prices[0], median(prices)
    spread = (mid - lo) / mid if mid else 0
    if count > 30:
        return f"ходовая ({count} шт.) — маржи, скорее всего, нет"
    if count <= 3:
        base = "редкая"
    else:
        base = "встречается изредка"
    if spread >= 0.3:
        return f"{base}, разброс {spread:.0%} — СТОИТ СЛЕДИТЬ"
    if spread >= 0.15:
        return f"{base}, разброс {spread:.0%} — можно попробовать"
    return f"{base}, но цены ровные ({spread:.0%}) — ловить нечего"


def report(db: sqlite3.Connection) -> None:
    games = [r[0] for r in db.execute(
        "SELECT game FROM scan ORDER BY game").fetchall()]
    if not games:
        print("База пуста. Сначала прочеши рынок: .venv/bin/python scan_market.py games.example.txt")
        return

    print(f"\n{'игра':<28} {'шт.':>4} {'мин':>7} {'медиана':>8} {'макс':>7}  вердикт")
    print("-" * 100)
    worth = []
    for game in games:
        rows = db.execute("SELECT price, age_min FROM listing WHERE game = ?",
                          (game,)).fetchall()
        prices = sorted(p for p, _ in rows if p)
        count = len(rows)
        v = verdict(count, prices)
        lo = prices[0] if prices else 0
        hi = prices[-1] if prices else 0
        print(f"{game[:27]:<28} {count:>4} {lo:>7} {median(prices):>8} {hi:>7}  {v}")
        if "СТОИТ СЛЕДИТЬ" in v:
            worth.append((game, median(prices)))

    print("-" * 100)
    if worth:
        print("\nЧто я бы взял в работу (и с каким потолком — ниже медианы,")
        print("чтобы проходило только заметно дешёвое):\n")
        for game, mid in worth:
            print(f"  {game} | {int(mid * 0.7) // 100 * 100}")
        print("\nЭти строки можно прямо вставить в свой games.txt.")
    else:
        print("\nНичего с широким разбросом не нашлось. Либо список не тот,")
        print("либо рынок ровный — тогда ловить нечего, и это тоже ответ.")

    print("\nВажно: это цены, которые ПРОСЯТ, а не за сколько уходит. Объявление")
    print("может висеть полгода втрое выше рынка и попасть сюда наравне со сделкой.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Разведка рынка Авито по списку игр.")
    parser.add_argument("titles", nargs="*",
                        help="файл со списком названий либо сами названия")
    parser.add_argument("--report", action="store_true",
                        help="только отчёт по накопленному, к Авито не ходить")
    parser.add_argument("--db", default=DB_PATH, help=f"файл базы (по умолчанию {DB_PATH})")
    parser.add_argument("--region", default="orel", help="регион в ссылке")
    parser.add_argument("--delay", type=int, nargs=2, metavar=("МИН", "МАКС"),
                        default=[DELAY_MIN_S, DELAY_MAX_S],
                        help="пауза между названиями в секундах")
    parser.add_argument("--force", action="store_true",
                        help="прочесать заново даже то, что смотрели недавно")
    args = parser.parse_args(argv)

    db = open_db(resolve(args.db))
    try:
        if args.report:
            report(db)
            return 0
        if not args.titles:
            parser.error("нужен список названий (файл или аргументы), либо --report")
        titles = list(read_titles(args.titles, 0, 0))
        n = scan(titles, db, args.region, tuple(args.delay), args.force)
        if n:
            print(f"\nГотово, прочёсано названий: {n}.")
        print("Отчёт: .venv/bin/python scan_market.py --report")
        return 0
    except KeyboardInterrupt:
        print("\n\nОстановлено. Собранное сохранено — запусти снова, продолжит "
              "с того же места.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
