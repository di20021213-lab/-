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
import re
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

# Ниже этого — цифровые копии, а не диски. «Directive 8020 PS5 На Русском» за
# 349 ₽ в пяти городах сразу это ровно они: их публикуют пачками по всей
# стране, и в анализе рынка они только мешают. Порог тот же, что у бота.
MIN_REAL_PRICE = 1000
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
CREATE TABLE IF NOT EXISTS meta (
    key        TEXT PRIMARY KEY,
    value      REAL NOT NULL
);
"""

# Ключ в нашей собственной базе: когда МЫ последний раз дёрнули Авито. Отметка
# бота этого не покрывает — если предыдущий обход прервали и тут же запустили
# заново, бюджет адреса занят нами самими, и первый же заход ловит 429. Ровно
# это и случилось дважды за вечер.
LAST_REQUEST_KEY = "last_request_at"


def plural(n: int, one: str, few: str, many: str) -> str:
    """«1 объявление, 2 объявления, 5 объявлений». Отчёт читают глазами."""
    if n % 100 // 10 == 1:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(n % 10, many)


def ads(n: int) -> str:
    return f"{n} {plural(n, 'объявление', 'объявления', 'объявлений')}"


# Бот считает флаг паузы протухшим через час — так задумано, чтобы забытый
# файл не оставил его стоять навсегда. Но наши паузы при блокировке удваиваются
# и легко переваливают за час: флаг тихо протухал прямо во время сна, бот
# просыпался, шёл к Авито и держал адрес занятым — ровно то, от чего мы и
# пытались уйти. Поэтому длинные паузы спим кусками, обновляя отметку.
PAUSE_REFRESH_S = 300


def sleep_holding_pause(seconds: float, pause: Path) -> None:
    """Проспать, не дав флагу паузы протухнуть."""
    left = seconds
    while left > 0:
        pause.touch()
        chunk = min(PAUSE_REFRESH_S, left)
        time.sleep(chunk)
        left -= chunk
    pause.touch()


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


def _bot_last_cycle() -> float | None:
    """Когда бот последний раз ходил к Авито (по его собственной отметке)."""
    db_path = Path(resolve("seen.sqlite3"))
    if not db_path.is_file():
        return None
    try:
        con = sqlite3.connect(db_path)
        row = con.execute("SELECT value FROM meta WHERE key = ?",
                          (LAST_CYCLE_KEY,)).fetchone()
        con.close()
        return float(row[0]) if row else None
    except (sqlite3.Error, TypeError, ValueError):
        return None


def _our_last_request(db: sqlite3.Connection) -> float | None:
    row = db.execute("SELECT value FROM meta WHERE key = ?",
                     (LAST_REQUEST_KEY,)).fetchone()
    return float(row[0]) if row else None


def note_request(db: sqlite3.Connection) -> None:
    """Отметить, что мы только что дёрнули Авито — удачно или нет."""
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
               (LAST_REQUEST_KEY, time.time()))
    db.commit()


def wait_out_previous(db: sqlite3.Connection, delay_min: int) -> None:
    """Переждать, если к Авито недавно ходил бот ИЛИ прошлый запуск обхода.

    Флаг паузы останавливает бота, но не отменяет уже сделанного запроса. А
    прерванный обход и вовсе не оставляет следов в чужой базе — поэтому свою
    отметку ведём сами. Берём более позднюю из двух.
    """
    stamps = [t for t in (_bot_last_cycle(), _our_last_request(db)) if t]
    if not stamps:
        return
    last = max(stamps)
    ago = time.time() - last
    left = delay_min - ago
    if left > 0:
        who = "Бот" if last == _bot_last_cycle() else "Прошлый обход"
        print(f"{who} ходил к Авито {ago / 60:.0f} мин назад. "
              f"Жду {left / 60:.0f} мин, иначе первый же заход поймает 429.")
        sleep_holding_pause(left, Path(resolve(PAUSE_FILE)))


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
        wait_out_previous(db, delay[0])
        with AvitoScraper(**browser_settings()) as scraper:
            for i, title in enumerate(todo, 1):
                pause.touch()   # держим бота в стороне, пока идём
                url = url_for(title, region)
                listings = None
                for attempt in range(1, BLOCKED_RETRIES + 1):
                    try:
                        note_request(db)   # отметку ставим ДО запроса: если нас
                        listings = scraper.fetch(url)   # убьют, она уже сохранена
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
                        sleep_holding_pause(blocked_pause, pause)
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
                    sleep_holding_pause(wait, pause)
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

    Решает РАЗБРОС, а не количество. Если все просят примерно одинаково,
    купить дешевле рынка неоткуда, сколько бы объявлений ни было. А где
    минимум заметно ниже середины — там кто-то не знает цену, и это ровно то,
    что бот должен ловить.

    Прежняя версия сначала смотрела на количество и при 30+ объявлениях сразу
    выносила «маржи нет». На первом же живом запуске это оказалось враньём:
    у «Limited Run» 55 объявлений с разбросом от 777 до 40500 — то есть в
    пятьдесят раз, — и это самый интересный случай, а не самый скучный.
    Количество говорит лишь о том, КАК ЧАСТО будет шанс, а не о том, есть ли
    он вообще.
    """
    if count == 0:
        return "не встречается — следить не за чем"
    if not prices:
        return "цены не указаны, судить не по чему"
    lo, mid = prices[0], median(prices)
    spread = (mid - lo) / mid if mid else 0

    how_often = ("шансы часто" if count > 30
                 else "шансы изредка" if count > 3
                 else "редкость")
    if spread >= 0.3:
        return f"разброс {spread:.0%}, {how_often} — СТОИТ СЛЕДИТЬ"
    if spread >= 0.15:
        return f"разброс {spread:.0%}, {how_often} — можно попробовать"
    return f"цены ровные ({spread:.0%}) — ловить нечего"


def details(db: sqlite3.Connection, needle: str,
            min_price: int = MIN_REAL_PRICE) -> None:
    """Все объявления по одному запросу, от дешёвых к дорогим.

    Для широких сетей вроде «Limited Run» это и есть главный результат: под
    одним запросом лежат десятки РАЗНЫХ игр, и сводная медиана по ним
    бессмысленна. А вот список с ценами показывает, что именно сейчас лежит
    дёшево — из него и набирается настоящий список для охоты.
    """
    # Сопоставляем в питоне, а не в SQL: встроенный lower() у SQLite работает
    # только с латиницей, и «Коллекционное издание» ему не по зубам — запрос
    # молча не нашёл бы ничего.
    names = [r[0] for r in db.execute("SELECT DISTINCT game FROM listing")]
    want = needle.casefold()
    matched = [n for n in names if want in n.casefold()]
    seen_ids: set[str] = set()
    rows = []
    for name in matched:
        for game, item_id, title, price, location, age in db.execute(
                "SELECT game, item_id, title, price, location, age_min "
                "FROM listing WHERE game = ?", (name,)):
            if item_id in seen_ids:
                continue          # то же объявление под другим запросом
            if price is not None and price < min_price:
                continue          # цифровая копия, а не диск
            seen_ids.add(item_id)
            rows.append((game, title, price, location, age))
    rows.sort(key=lambda r: (r[2] is None, r[2] or 0))
    if not rows:
        have = [r[0] for r in db.execute("SELECT game FROM scan ORDER BY game")]
        print(f"По запросу «{needle}» ничего не собрано.")
        if have:
            print("Есть данные по:", ", ".join(have))
        return
    print(f"\n{ads(len(rows))} по запросу «{needle}», от дешёвых к дорогим:\n")
    for game, title, price, location, age in rows:
        money = f"{price:>7} ₽" if price else "     без цены"
        where = f" — {location}" if location else ""
        days = f" ({age // 1440} д)" if age and age >= 1440 else ""
        print(f"  {money}  {(title or '?')[:60]}{where}{days}")
    print(f"\nЗапрос{'ы' if len(matched) > 1 else ''}: {', '.join(matched)}")
    print("Что тут дёшево против остальных — то и стоит добавить в games.txt\n"
          "отдельной строкой со своим потолком.")


# Слова, которые есть почти в каждом заголовке и потому ничего не различают:
# платформа, состояние, издатель, служебное. Их выкидываем, чтобы осталось
# собственно название игры.
_NOISE = {
    "ps5", "ps4", "ps3", "ps2", "psv", "xbox", "series", "one", "switch",
    "nintendo", "sony", "playstation", "lrg", "srg", "limited", "run", "games",
    "игра", "игры", "игру", "диск", "диски", "дисков", "новая", "новый",
    "новое", "новые", "издание", "издания", "edition", "sealed", "новый/sealed",
    "русские", "русская", "русский", "субтитры", "версия", "озвучка", "для",
    "прошитая", "запечатан", "запечатана", "коллекционное", "collector",
    "collectors", "deluxe", "standard", "exclusive", "американка", "америка",
}

_CITY_TAIL = re.compile(r"\s+в\s+[^\s]+\s*$")
_ISSUE_NO = re.compile(r"#\s*\d+")          # номер выпуска LRG — не отличает игру
_PLATFORMS = {
    "ps5": "ps5", "playstation5": "ps5",
    "ps4": "ps4", "playstation4": "ps4",
    "ps3": "ps3", "ps2": "ps2",
    "xbox": "xbox", "switch": "switch", "nintendo": "switch",
}


class Sig:
    """Разобранный заголовок: слова, числа и платформа — по отдельности.

    Числа и платформа вынесены не для красоты. На живой выдаче «Yakuza 0» и
    «Yakuza 7 частей игры» сливались в одну игру с разницей 35 500 ₽, а
    «Volume 1» и «Volume 2» — в одну с разницей 1140. Это была бы выдуманная
    маржа, то есть худший вид ошибки: по ней человек пойдёт покупать.
    """

    __slots__ = ("words", "numbers", "platform")

    def __init__(self, words, numbers, platform):
        self.words = words
        self.numbers = numbers
        self.platform = platform

    def merged(self, other: "Sig") -> "Sig":
        return Sig(self.words | other.words, self.numbers | other.numbers,
                   self.platform or other.platform)


def signature(title: str) -> Sig:
    """Значимые слова заголовка — то, чем одна игра отличается от другой.

    Заголовки на Авито пишут как попало: «Star wars: Dark Forces Remaster LRG
    #107 Новая в Москве» и «Игра star wars: Dark Forces Remaster в Жуковском» —
    это одна и та же игра. Чтобы их свести, выкидываем город, номер выпуска,
    платформу и слова-пустышки, а сравниваем по тому, что осталось.
    """
    raw = (title or "").lower().replace("ё", "е")
    platform = ""
    for token, name in _PLATFORMS.items():
        if token in raw.replace(" ", ""):
            platform = name
            break
    t = _CITY_TAIL.sub("", raw)
    t = _ISSUE_NO.sub(" ", t)
    t = re.sub(r"[^a-zа-я0-9\s]", " ", t)
    words, numbers = set(), set()
    for w in t.split():
        if w.isdigit():
            numbers.add(w)
        elif len(w) >= 3 and w not in _NOISE:
            words.add(w)
    return Sig(frozenset(words), frozenset(numbers), platform)


def same_game(a: Sig, b: Sig) -> bool:
    """Одна ли это игра.

    Три условия, и каждое появилось из настоящего промаха на живой выдаче:
      · числа не должны противоречить — «Volume 1» и «Volume 2» разные;
      · платформа не должна противоречить — диск для Xbox не перепродать
        владельцу PS5;
      · меньшее название должно почти целиком входить в большее. Двух общих
        слов мало: «Sam & Max Beyond Time and Space» и «Sam & Max Save The
        World» — совершенно разные игры.
    """
    if a.numbers and b.numbers and not (a.numbers & b.numbers):
        return False
    if a.platform and b.platform and a.platform != b.platform:
        return False
    common = a.words & b.words
    if not common:
        return False
    smaller = min(len(a.words), len(b.words))
    if smaller == 1:
        return True                     # односложные названия: Quake, Humanity
    return len(common) >= 2 and len(common) / smaller >= 0.7


def dupes(db: sqlite3.Connection, needle: str | None = None,
          min_price: int = MIN_REAL_PRICE) -> None:
    """Одна и та же игра у разных продавцов — и на сколько цены разошлись.

    Вот здесь и живёт заработок. Сводная медиана по широкому запросу вроде
    «Limited Run» ни о чём не говорит: под ним десятки разных игр, и разброс
    от 777 до 40500 — это не возможность, а просто разные товары. А вот когда
    ОДНА игра лежит у одного за 3990, а у другого за 4800 — это уже цифра,
    с которой можно работать.
    """
    rows = db.execute(
        "SELECT game, item_id, title, price, location FROM listing "
        "WHERE price IS NOT NULL AND price >= ?", (min_price,)).fetchall()
    if needle:
        want = needle.casefold()
        rows = [r for r in rows if want in r[0].casefold()]

    # Одно и то же объявление приходит под разными запросами: и по «Limited
    # Run», и по «Коллекционное издание». Ключ в таблице — (запрос, id), так
    # что в базе это две строки, и без чистки объявление сравнивалось само с
    # собой — отсюда и вереница «разница 0 ₽».
    by_item: dict[str, tuple] = {}
    for game, item_id, title, price, location in rows:
        by_item.setdefault(item_id, (game, title, price, location))
    rows = list(by_item.values())

    if not rows:
        print(f"Нет собранных объявлений дороже {min_price} ₽.")
        return

    groups: list[dict] = []
    for game, title, price, location in rows:
        sig = signature(title)
        if not sig.words:
            continue
        for g in groups:
            if same_game(sig, g["sig"]):
                g["items"].append((price, title, location))
                g["sig"] = g["sig"].merged(sig)
                break
        else:
            groups.append({"sig": sig, "items": [(price, title, location)],
                           "game": game})

    interesting = []
    for g in groups:
        if len(g["items"]) < 2:
            continue
        prices = sorted(p for p, _, _ in g["items"])
        lo, hi = prices[0], prices[-1]
        # Нулевая разница — не находка, а просто одинаковая цена у двоих.
        # Показывать её значит топить настоящие пары в шуме.
        if not lo or hi == lo:
            continue
        interesting.append((hi - lo, lo, hi, g))
    # Ключ только по числам. Без него при одинаковых (разница, мин, макс)
    # питон доходил до сравнения словарей и падал с TypeError — на живых
    # данных такие совпадения встречаются сразу же.
    interesting.sort(key=lambda x: x[:3], reverse=True)

    if not interesting:
        print("\nНи одной игры не нашлось у двух продавцов по РАЗНОЙ цене.\n"
              "Либо выборка мала, либо у каждого своя игра — тогда сравнивать\n"
              "не с чем, и это тоже ответ: перепродавать нечего.")
        return

    print(f"\nИгры, встретившиеся больше одного раза "
          f"({len(interesting)} из {len(groups)}):\n")
    for gap, lo, hi, g in interesting:
        pct = gap / hi if hi else 0
        print(f"  разница {gap} ₽ ({pct:.0%}):")
        for price, title, location in sorted(g["items"]):
            where = f" — {location}" if location else ""
            print(f"      {price:>7} ₽  {title[:64]}{where}")
        print()

    print("Разница — это ВЕРХНЯЯ граница возможного заработка, до вычета\n"
          "доставки, времени и риска. И это цены, которые просят: то, что\n"
          "висит дороже, может не продаваться вовсе.")


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
        print("\nЭти строки можно вставить в свой games.txt — но только для\n"
              "конкретных игр. Для широких сетей («Limited Run» и подобных)\n"
              "средняя цена ни о чём не говорит: под одним запросом лежат\n"
              "десятки разных игр. Там смотри --details.")
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
    parser.add_argument("--details", metavar="ЗАПРОС",
                        help="показать все объявления по одному запросу, от "
                             "дешёвых к дорогим. К Авито не ходит")
    parser.add_argument("--dupes", nargs="?", const="", metavar="ЗАПРОС",
                        help="найти одну и ту же игру у разных продавцов и "
                             "показать, насколько разошлись цены. К Авито не ходит")
    parser.add_argument("--db", default=DB_PATH, help=f"файл базы (по умолчанию {DB_PATH})")
    parser.add_argument("--region", default="orel", help="регион в ссылке")
    parser.add_argument("--delay", type=int, nargs=2, metavar=("МИН", "МАКС"),
                        default=[DELAY_MIN_S, DELAY_MAX_S],
                        help="пауза между названиями в секундах")
    parser.add_argument("--min-price", type=int, default=MIN_REAL_PRICE,
                        dest="min_price",
                        help=f"в отчётах не учитывать дешевле этого (сейчас "
                             f"{MIN_REAL_PRICE} — ниже идут цифровые копии). "
                             f"0 — показывать всё")
    parser.add_argument("--force", action="store_true",
                        help="прочесать заново даже то, что смотрели недавно")
    args = parser.parse_args(argv)

    # Питон буферизует вывод, когда он идёт не в терминал, а в файл. Обход
    # длится часами, и с буфером в лог по дороге не попадает НИЧЕГО: снаружи
    # это неотличимо от зависшего скрипта. Переключаем на построчный вывод,
    # чтобы `tail -f scan.log` показывал происходящее сразу, как бы скрипт ни
    # запустили — через nohup, через systemd или вручную.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)

    db = open_db(resolve(args.db))
    try:
        if args.dupes is not None:
            dupes(db, args.dupes or None, args.min_price)
            return 0
        if args.details:
            details(db, args.details, args.min_price)
            return 0
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
