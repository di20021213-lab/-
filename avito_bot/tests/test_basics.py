"""Быстрые проверки чистой логики: python tests/test_basics.py"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import Config
from bot.links import extract_links, parse_avito_url
from bot.runner import Runner, in_quiet_hours
from bot.storage import Storage
from bot.templates import render


def test_links() -> None:
    text = (
        "https://www.avito.ru/moskva/telefony/iphone_13_1234567890?context=x "
        "https://m.avito.ru/i/9876543210 https://avito.ru/1234567890 "
        "https://www.avito.ru/moskva/telefony https://ya.ru/a_1234567890"
    )
    links = extract_links(text)
    assert [l.item_id for l in links] == ["1234567890", "9876543210"], links
    assert links[0].url == "https://www.avito.ru/moskva/telefony/iphone_13_1234567890"
    assert parse_avito_url("https://ya.ru/x_1234567890") is None
    assert extract_links("") == []
    # точка в конце предложения не должна попадать в ссылку
    assert extract_links("смотри https://avito.ru/1112223334.")[0].item_id == "1112223334"


def test_quiet_hours() -> None:
    at = lambda h: dt.datetime(2026, 1, 1, h)  # noqa: E731
    assert [in_quiet_hours([23, 8], at(h)) for h in (22, 23, 2, 7, 8)] == [
        False, True, True, True, False,
    ]
    assert in_quiet_hours([9, 18], at(12)) is True
    assert in_quiet_hours(None, at(3)) is False
    assert in_quiet_hours([0, 0], at(3)) is False


def test_templates() -> None:
    out = render(["Привет, «{title}» за {price}. {unknown}"], title="Стол", price="900 ₽")
    assert out == "Привет, «Стол» за 900 ₽."
    try:
        render([])
    except ValueError:
        pass
    else:
        raise AssertionError("пустой список шаблонов должен падать")


def test_storage_dedup_and_limits() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        st = Storage(str(Path(tmp) / "s.sqlite3"))
        assert st.add_queued("1", "u") is True
        assert st.add_queued("1", "u") is False
        st.record_send("1")
        assert st.sent_since(3600) == 1
        st.mark("1", "sent", title="T", message="m")
        assert st.stats()["sent"] == 1


class FakeBrowser:
    """Подменяет Playwright: ничего не открывает, просто запоминает вызовы."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bool]] = []

    async def open_card(self, url: str):
        from bot.avito import Card

        return Card(title="Диван", price="5 000 ₽", seller="Иван")

    async def send_message(self, url: str, text: str, *, dry_run: bool) -> str:
        self.sent.append((url, text, dry_run))
        return "dry_run" if dry_run else "sent"


def test_runner_flow() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config({
                "sending": {"dry_run": False, "max_per_hour": 1, "max_per_day": 10,
                            "delay_min_s": 0, "delay_max_s": 0, "skip_duplicates": True},
                "templates": ["Здравствуйте! «{title}» ещё актуально?"],
            })
            st = Storage(str(Path(tmp) / "s.sqlite3"))
            browser = FakeBrowser()
            notes: list[str] = []

            async def notify(text: str) -> None:
                notes.append(text)

            runner = Runner(cfg, st, browser, notify)
            worker = asyncio.create_task(runner.worker())

            links = extract_links("https://avito.ru/1111111111 https://avito.ru/2222222222")
            assert await runner.offer(links[0]) is True
            assert await runner.offer(links[0]) is False          # дубль
            await asyncio.sleep(0.4)

            assert len(browser.sent) == 1, browser.sent
            assert browser.sent[0][1] == "Здравствуйте! «Диван» ещё актуально?"
            assert st.stats().get("sent") == 1
            assert notes and notes[0].startswith("✅")

            # часовой лимит исчерпан -> второе объявление ждёт, а не уходит
            await runner.offer(links[1])
            await asyncio.sleep(0.4)
            assert len(browser.sent) == 1, "лимит max_per_hour не сработал"

            worker.cancel()
            st.close()

    asyncio.run(scenario())


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("\nвсе проверки прошли")
