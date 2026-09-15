#!/usr/bin/env python3
"""Генератор блоков поиска для config.yaml по списку названий игр.

Зачем. Охота за редкими играми — это по отдельному поиску на каждое название
(почему именно так, написано в шапке config.games.example.yaml). Блок на игру —
десяток строк YAML плюс URL с закодированным русским запросом. Руками это
пишется ровно до третьей игры, дальше начинаются опечатки в кодировке, которые
молча превращаются в пустую выдачу.

Использование:

    .venv/bin/python make_searches.py games.txt              — напечатать блоки
    .venv/bin/python make_searches.py games.txt >> config.yaml
    .venv/bin/python make_searches.py "Hollow Knight" "Celeste"

Формат файла со списком — по названию в строке. Пустые строки и строки,
начинающиеся с #, пропускаются. Цену можно задать прямо в строке:

    Hollow Knight
    Sekiro | 4500              — свой потолок
    Persona 5 Royal | 6000 | 2000   — свой потолок и своя нижняя граница

ПРО ССЫЛКУ. Шаблон собран из ОДНОГО проверенного адреса — того, что работает
на Pragmata. Хеш раздела (ASgBAgICAUSSAsYJ) кодирует подкатегорию «игры для
приставок», и составить такой по догадкам нельзя: на этом уже потерян день.
Поэтому мы его не сочиняем, а переиспользуем, меняя только сам запрос.

Но проверить первый сгенерированный поиск всё равно нужно — выдача Авито по
чужому названию может повести себя иначе:

    .venv/bin/python -m avito_watcher.main --check

--check ничего не шлёт и не пишет в базу, так что гонять его безопасно.

ПРО НАЗВАНИЯ ПОИСКОВ (label). Label — это ключ, по которому бот помнит, что
он уже показывал. Переименуешь игру в конфиге — для бота это новый поиск: он
молча запомнит всё, что сейчас в выдаче, и пришлёт только то, что появится
после. Ничего страшного, но знать полезно.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

# Проверенный на Pragmata раздел. Всё, что меняется от игры к игре, — запрос.
URL_TEMPLATE = ("https://www.avito.ru/{region}/igry_pristavki_i_programmy/"
                "igry_dlya_pristavok-ASgBAgICAUSSAsYJ?q={query}&s=104")

# Слово «диск» в запросе — половина фильтрации: у цифровой копии в заголовке
# «Русская Озвучка» и «аккаунт», а не «диск». Отсеивает ещё на стороне Авито.
QUERY_SUFFIX = "диск"

# Цифровые копии и аккаунты продают одинаковым текстом по всей стране за
# 300-700 ₽ и забивают ими выдачу. Список выверен на живой выдаче Pragmata.
# «на русском» сюда НЕ добавляем: этой фразой помечают цифру, но её же может
# написать и продавец диска — потерять нужное хуже, чем получить лишнее.
# «п3»/«п2» — принятое на Авито обозначение типа аккаунта; как подстрока в
# русском тексте не встречается, ложных срабатываний не даёт.
EXCLUDE = ["аккаунт", "цифров", "ключ", "активац", "подписк",
           "steam", "оффлайн", "offline", "п3", "п2"]

# Встроенный словарь признаков поломки заточен под технику; для диска важно
# другое — состояние поверхности и комплектность.
BROKEN_MARKERS = ["царапин", "не читается", "нечитаем", "без диска", "только коробка"]

MESSAGE = "Здравствуйте! Диск ещё продаётся? Готов забрать сегодня?"

# Дешевле тысячи дисковой игры не бывает — это верный признак цифры.
DEFAULT_MIN = 1000
DEFAULT_MAX = 4200


def parse_line(line: str, default_max: int, default_min: int):
    """Разбирает строку «Название | потолок | нижняя граница»."""
    parts = [p.strip() for p in line.split("|")]
    title = parts[0]
    top = int(parts[1]) if len(parts) > 1 and parts[1] else default_max
    bottom = int(parts[2]) if len(parts) > 2 and parts[2] else default_min
    return title, top, bottom


def read_titles(source: list[str], default_max: int, default_min: int):
    """Названия из файла или прямо из аргументов командной строки."""
    if len(source) == 1 and Path(source[0]).is_file():
        raw = Path(source[0]).read_text(encoding="utf-8").splitlines()
    else:
        raw = source
    for line in raw:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        yield parse_line(line, default_max, default_min)


def yaml_list(items) -> str:
    return "[" + ", ".join(f'"{x}"' for x in items) + "]"


def block(title: str, top: int, bottom: int, region: str) -> str:
    query = quote(f"{title} {QUERY_SUFFIX}".lower(), safe="")
    url = URL_TEMPLATE.format(region=region, query=query)
    # keywords — страховка от того, что Авито подмешает постороннее: в
    # заголовке должно встретиться само название. Проверяется как подстрока,
    # поэтому «Hollow Knight PS4» подойдёт, а «Hollow  Knight» с двойным
    # пробелом — уже нет. Если игра известна и под сокращением, допиши его
    # сюда вторым элементом: достаточно совпадения ЛЮБОГО.
    return f'''  - label: "{title} (диск)"
    url: "{url}"
    min_price: {bottom}
    max_price: {top}
    # Окна свежести нет: редкая игра появляется раз в недели, и объявление
    # трёхдневной давности живо. Задача не успеть первым, а не пропустить.
    on_broken: flag
    # Страницу объявления не открываем: это главный расход бюджета адреса.
    check_description: false
    keywords: ["{title.lower()}"]
    exclude_keywords: {yaml_list(EXCLUDE)}
    extra_broken_markers: {yaml_list(BROKEN_MARKERS)}
    message_template: "{MESSAGE}"
'''


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Собирает блоки searches: для config.yaml по списку игр.")
    parser.add_argument("titles", nargs="+",
                        help="файл со списком названий либо сами названия")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX, dest="top",
                        help=f"потолок цены по умолчанию (сейчас {DEFAULT_MAX})")
    parser.add_argument("--min", type=int, default=DEFAULT_MIN, dest="bottom",
                        help=f"нижняя граница по умолчанию (сейчас {DEFAULT_MIN})")
    parser.add_argument("--region", default="orel",
                        help="регион в ссылке (по умолчанию orel). Объявления из "
                             "других городов всё равно попадают — по доставке")
    args = parser.parse_args(argv)

    games = list(read_titles(args.titles, args.top, args.bottom))
    if not games:
        print("Ни одного названия не нашёл. Пустой файл?", file=sys.stderr)
        return 1

    for title, top, bottom in games:
        print(block(title, top, bottom, args.region))

    print(f"# Готово: {len(games)} поисков. Проверь первый запуском "
          f".venv/bin/python -m avito_watcher.main --check", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
