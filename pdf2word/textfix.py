"""Мелкая чистка распознанного текста."""

from __future__ import annotations

import re

CYR = re.compile(r"[А-Яа-яЁё]")
LAT = re.compile(r"[A-Za-z]")

# латинские буквы, которые выглядят как русские, и наоборот
LAT2CYR = str.maketrans("ABCEHKMOPTXaceopxykb", "АВСЕНКМОРТХасеорхукь")
CYR2LAT = str.maketrans("АВСЕНКМОРТХасеорхук", "ABCEHKMOPTXaceopxyk")

DASHES = set("-–—_|=~")
SYMBOLS = {"№", "§", "%", "«", "»", "(", ")", "–", "—", "+", "=", "/", "*", "$", "€", "₽", "°",
           "\"", "№№", "%,", "%.", "),", ").", "»,", "».", "»;", "):"}
SHORT_WORDS = set("в и с к о у я а В И С К О У Я А".split()) | set(
    "на по до за из от не же ли бы то во со ко об но да их ее её он мы вы им ей ни "
    "На По До За Из От Не Но Да Он Мы Вы".split())


def fix_word(text: str) -> str:
    """Исправляет слова, в которых перемешаны русские и латинские буквы."""
    cyr = len(CYR.findall(text))
    lat = len(LAT.findall(text))
    if cyr and lat:
        if cyr >= lat:
            text = text.translate(LAT2CYR)
        else:
            text = text.translate(CYR2LAT)
    # «!0» → «10»: единицу рядом с буквами Tesseract иногда читает как «!»
    text = re.sub(r"!(?=\d)", "1", text)
    # «0» вместо «О» внутри русского слова и наоборот
    if cyr >= 2:
        text = re.sub(r"(?<=[А-Яа-яЁё])0(?=[А-Яа-яЁё])", "о", text)
    return text


_HOMOGLYPH_CODE = re.compile(r"[АВЕКМНОРСТХ0-9./\-–]+")


def latin_code(text: str, neighbours: list[str]) -> str:
    """«КВ-300» рядом с «A4Tech» — это артикул латиницей: русские буквы,
    похожие на латинские, вместе с цифрами меняем на латинские."""
    if not (_HOMOGLYPH_CODE.fullmatch(text) and CYR.search(text) and
            any(ch.isdigit() for ch in text)):
        return text
    if any(LAT.search(n) and not CYR.search(n) for n in neighbours):
        return text.translate(CYR2LAT)
    return text


def is_dash_only(text: str) -> bool:
    return bool(text) and all(ch in DASHES for ch in text)


def is_noise(text: str, conf: float) -> bool:
    """Мусор от пятен, печатей, подписей."""
    letters = sum(ch.isalnum() for ch in text)
    if conf < 15 and letters <= 2:
        return True
    if not letters and conf < 45 and text not in SYMBOLS and text not in ("-",):
        return True
    core = text.strip(".,;:!?()«»\"'")
    if core in SHORT_WORDS:
        return conf < 12          # частые короткие слова не выбрасываем
    if letters and len(text) <= 2 and conf < 40:
        return True
    if letters and len(text) <= 3 and conf < 30:
        return True
    return False


# заглавные, которые по начертанию отличаются от строчных только размером
SAME_SHAPE = set("ВЖЗИКЛМНОПСТХЦЧШЩЪЫЬЭЮЯ")


def fix_case(text: str, height: float, xh: float, ref_xh: float = 0.0) -> str:
    """«Шт.» → «шт.»: заглавная буква высотой со строчную — на самом деле строчная.

    ref_xh — высота строчных у соседнего текста (той же таблицы или
    страницы): по ней узнаётся и слово целиком из «заглавных» («ШТ.»), у
    которого собственная высота строчных измерена как у заглавных."""
    if not text or not xh:
        return text
    first = text[0]
    rest = text[1:]
    letters_rest = [ch for ch in rest if ch.isalpha()]
    tall = set("бдруфйёцщ")    # у этих строчных есть выносные элементы
    if first in SAME_SHAPE and (not letters_rest or all(ch.islower() for ch in letters_rest)):
        if height < 1.18 * xh and not any(ch in tall for ch in rest.lower()):
            return first.lower() + rest
    letters = [ch for ch in text if ch.isalpha()]
    if ref_xh and 2 <= len(letters) <= 4 and all(ch in SAME_SHAPE for ch in letters) and \
            height < 1.15 * ref_xh:
        return text.lower()
    return text


# как выглядят русские буквы, если читать их английской моделью
_LOOK = str.maketrans({
    "а": "a", "б": "6", "в": "b", "г": "r", "д": "a", "е": "e", "ё": "e", "ж": "x", "з": "3",
    "и": "u", "й": "u", "к": "k", "л": "n", "м": "m", "н": "h", "о": "o", "п": "n", "р": "p",
    "с": "c", "т": "t", "у": "y", "ф": "o", "х": "x", "ц": "u", "ч": "4", "ш": "w", "щ": "w",
    "ъ": "b", "ы": "bi", "ь": "b", "э": "3", "ю": "io", "я": "r", "№": "no",
})


def looks_same(rus: str, eng: str) -> float:
    """Насколько английское прочтение — это те же буквы «в латинице»
    (тогда исходный текст русский и менять его не нужно)."""
    import difflib
    a = rus.lower().translate(_LOOK)
    b = eng.lower()
    return difflib.SequenceMatcher(None, a, b).ratio()
