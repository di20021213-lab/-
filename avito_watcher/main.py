"""Точка входа: цикл мониторинга Авито -> уведомления в Telegram."""

from __future__ import annotations

import argparse
import logging
import random
import signal
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

from . import filters, quality
from .config import ConfigError, SearchConfig, Settings, load_settings, match_model
from .dates import format_age
from .notifier import TelegramNotifier
from .paths import resolve, setup_bundled_browsers
from .scraper import AntibotError, AvitoScraper
from .storage import SeenStore

log = logging.getLogger("avito_watcher")

# Пока Авито нас блокирует, обычная пауза делает только хуже: 429 — это лимит по
# IP, он снимается временем БЕЗ запросов. Продолжать долбить каждые 2 минуты —
# значит держать бан бесконечно. Поэтому уходим в долгую паузу, которая
# удваивается с каждым подряд заблокированным циклом.
# 20 минут, а не 15: столько адресу нужно на восстановление по нашим же
# измерениям. Пятнадцать были обречены — первая попытка почти всегда упиралась
# в тот же лимит, пауза удваивалась до 30, и простой выходил 45 минут вместо 20.
BLOCKED_COOLDOWN_S = 1200
# Потолок паузы. Был час — и это оказалось ошибкой. В ночь на 14 сентября бот
# упёрся в него и трижды подряд ходил ровно через 60 минут, каждый раз получая
# 429: бан держался около пяти часов, а пересидеть его бот структурно не мог.
# Хуже того, каждая попытка из-под бана продлевала бан. Час имел смысл, пока
# были окна свежести (см. _cooldown_ceiling): ждать дольше окна — значит
# пропустить объявление, ради которого и ждём. Для старых видюх окна нет вовсе,
# защищать нечего, и отсидеться дольше выгоднее, чем стучаться чаще.
BLOCKED_COOLDOWN_MAX_S = 6 * 3600

# После скольких заблокированных циклов подряд написать об этом в Telegram:
# молча простаивать полчаса — хуже, чем одно сообщение.
BLOCKED_ALERT_AFTER = 3

# Когда закончился прошлый цикл. Живёт в базе, а не в памяти процесса, — иначе
# перезапуск службы стирает саму память о том, что запрос был только что.
LAST_CYCLE_KEY = "last_cycle_at"

# Когда последний раз слали сводку. Тоже в базе: перезапуск не должен
# оборачиваться внеочередным сообщением.
HEARTBEAT_KEY = "last_heartbeat_at"

# Пока человек сам сидит в браузере через удалённый экран (deploy/minipc/screen.sh),
# бот не должен лезть в тот же профиль: Chromium не открывает одну папку профиля
# дважды, и полез бы — уронил бы человеку окно посреди капчи.
PAUSE_FILE = "PAUSE.flag"
# Флаг с истечением, а не просто файл. Если его забудут снять — сел телефон,
# оборвался туннель, закрыли терминал не тем способом — бот через час вернётся
# к работе сам, а не будет молча стоять до следующего перезапуска. Час взят с
# запасом: живой сеанс с телефона столько не длится, а скрипт всё это время
# обновляет отметку файла, так что настоящую работу пауза не прервёт.
PAUSE_MAX_S = 3600

_stop = False


def _handle_signal(signum, frame):  # noqa: ARG001
    global _stop
    _stop = True
    log.info("Получен сигнал остановки, завершаюсь после текущего цикла...")


def _fetch_details_safe(scraper: AvitoScraper, url: str, label: str) -> tuple[Optional[str], bool]:
    """Описание объявления и флаг «проверка состоялась».

    Флаг важен: без него сбой сети выглядел бы так же, как чистое описание, и
    объявление уходило бы без пометки, будто его проверили и всё в порядке.
    """
    # Пауза перед второй страницей. На четырёх поисках объявлений-финалистов
    # больше, и короткая пауза приводила к антиботу на странице объявления —
    # тогда описание не читается и карта уходит без проверки на неисправность.
    time.sleep(random.uniform(3.0, 7.0))
    try:
        return scraper.fetch_details(url), True
    except AntibotError as e:
        log.warning("[%s] описание не проверено (антибот): %s", label, e)
    except Exception as e:  # noqa: BLE001
        log.warning("[%s] описание не проверено: %s", label, e)
    return None, False


def _freshness_rank(listing) -> tuple[int, int]:
    """Ключ сортировки «сначала свежее».

    Возраст известен — по нему. Известна только нижняя оценка по позиции в
    выдаче — по ней, но ПОЗЖЕ любого объявления с точной датой того же
    возраста: оценка говорит «не моложе», значит на деле может быть сильно
    старше. Совсем без возраста — в конец: такие висят месяцами.
    """
    if listing.age_minutes is not None:
        return (0, listing.age_minutes)
    if listing.min_age_minutes is not None:
        return (1, listing.min_age_minutes)
    return (2, 0)


# Пауза между заходами на страницы объявлений. Пятнадцать запросов подряд за
# несколько секунд — это подпись робота, даже если их всего пятнадцать. Ровно
# те же запросы, разнесённые во времени, выглядят как человек, листающий выдачу.
DETAIL_PAUSE_S = (4.0, 10.0)

# Сколько уведомлений за один цикл — уже не находка, а лента.
#
# Редкая игра появляется раз в недели: один-два за цикл это охота. Четыре
# разных продавца в одном заходе означают не удачу, а то, что потолок стоит
# ВЫШЕ рынка — под него подходит вообще всё, что продаётся. Так было с
# Pragmata (81 уведомление за сутки) и повторилось со Star Wars Dark Forces,
# где потолок 4000 накрыл весь рынок от 2814 до 3400.
#
# Молча это не отличить от «повезло», поэтому предупреждаем в журнале. Ничего
# не блокируем: решать, опускать потолок или нет, всё равно человеку.
FEED_WARN_PER_CYCLE = 4


def _priority_rule(listing, search: SearchConfig):
    """Правило приоритетной модели, если объявление под неё подходит.

    Приоритет решает два вопроса сразу: такие объявления уходят первыми (а
    значит попадают и в лимит уведомлений, и в бюджет чтения описаний, который
    у нас всего три захода), и с них снимается пометка «возможно неисправна»
    по extra_broken_markers. Для P106 эта пометка была развёрнута задом
    наперёд: она предупреждала об отсутствии видеовыходов у карты, которую
    берут именно такой.
    """
    rule = match_model(listing.title, search.models)
    return rule if rule is not None and rule.priority else None


def process_search(
    search: SearchConfig,
    scraper: AvitoScraper,
    store: SeenStore,
    notifier: TelegramNotifier,
    max_notifications: int,
    max_details: int = 3,
    stats: Optional["_Stats"] = None,
) -> int:
    """Проверяет один поиск. Возвращает число отправленных уведомлений."""
    listings = scraper.fetch(search.url, search.max_age_minutes)
    # Сколько карточек с фото — отдельным числом. Без него «фото не пришло»
    # неотличимо: то ли разбор не нашёл ссылку, то ли Telegram не взял файл.
    # Считается по уже полученным данным, лишних запросов к Авито не делает.
    with_photo = sum(1 for x in listings if x.image_url)
    log.info("[%s] получено объявлений: %d (с фото: %d)",
             search.label, len(listings), with_photo)
    if stats is not None:
        stats.looked += len(listings)
    if listings and not with_photo:
        log.warning("[%s] ни у одной карточки нет ссылки на фото — уведомления "
                    "уйдут текстом. Смотреть надо разбор выдачи, а не Telegram.",
                    search.label)
    if not listings:
        return 0

    # Всё, что сейчас в выдаче, ещё продаётся — продлеваем отметку. Делается
    # до любых фильтров: время жизни интересно и у тех, что нам не подошли.
    store.touch(search.label, (x.id for x in listings))

    first_run = not store.has_any(search.label)

    # Первичный посев БЕЗ фильтра свежести: молча запоминаем всё, чтобы не завалить
    # пользователя старьём на старте. Если задан max_age — наоборот, сразу шлём то,
    # что подходит по свежести (ради этого его и ставят), остальное просто запоминаем.
    if first_run and search.max_age_minutes is None and search.first_run == "seed":
        for lst in listings:
            store.mark_seen(search.label, lst.id, notified=True, title=lst.title, price=lst.price)
        log.info("[%s] первичный посев: запомнил %d объявлений (без уведомлений)",
                 search.label, len(listings))
        return 0
    if first_run and search.first_run == "send":
        log.info("[%s] первый запуск, first_run: send — пришлю всё подходящее, "
                 "что уже лежит", search.label)
    if first_run:
        log.info("[%s] первый запуск с max_age: пришлю то, что не старше %d мин",
                 search.label, search.max_age_minutes)

    # Новые = те, которых ещё нет в базе. Шлём СВЕЖИЕ ПЕРВЫМИ.
    #
    # Раньше порядок был хронологический — при окне в час это ничего не меняло,
    # все объявления были примерно одного возраста. Без окна в выдаче лежит
    # старьё за неделю, и хронология ставила его впереди только что вышедшего:
    # свежее уезжало в хвост очереди, а за лимитом в 15 — вообще в следующий
    # цикл, то есть на полчаса. Именно эти полчаса и решают, успеть или нет.
    new_listings = [lst for lst in listings if not store.is_seen(search.label, lst.id)]
    # Приоритетные модели — впереди всего, остальное по свежести.
    new_listings.sort(key=lambda x: (0 if _priority_rule(x, search) else 1,)
                      + _freshness_rank(x))

    if not new_listings:
        return 0

    sent = 0
    deferred = 0
    details_fetched = 0   # заходов на страницы объявлений за этот цикл
    details_skipped = 0
    for lst in new_listings:
        if not filters.passes(lst, search):
            # Не подошло — запоминаем, чтобы не переоценивать каждый цикл.
            store.mark_seen(search.label, lst.id, notified=False,
                            title=lst.title, price=lst.price)
            continue

        if sent >= max_notifications:
            # Лимит за цикл исчерпан. Виденным НЕ помечаем: объявление подходит,
            # и пометка сейчас означала бы, что оно не придёт уже никогда.
            # Останется новым и уйдёт следующим циклом.
            deferred += 1
            continue

        # Признаки неисправности: сначала заголовок (бесплатно), потом — если чисто —
        # само объявление: описание и параметры. Только для финалистов, их мало.
        warning = None
        unchecked = False
        prio = _priority_rule(lst, search)
        # У приоритетной модели свои приметы — не признаки поломки, а её
        # собственные свойства, ради которых её и ищут. Базовый список
        # («не работает», «артефакты») проверяется по-прежнему.
        broken_extra = () if prio else search.extra_broken_markers
        if search.on_broken != "ignore":
            # Сначала бесплатное: заголовок и текст самой карточки. Открывать
            # страницу объявления — дорого, каждый такой заход приближает 429.
            reason = quality.broken_reason(lst.title, lst.card_text,
                                           extra=broken_extra)
            if reason is None and search.check_description and lst.url:
                if details_fetched >= max_details:
                    # Бюджет заходов исчерпан. Объявление всё равно отправляем —
                    # просто с честной пометкой, что описание не читали. Молчать
                    # о нём нельзя: оно подходит, а следующего цикла может и не
                    # быть, если адрес к тому времени заблокируют.
                    details_skipped += 1
                    unchecked = True
                else:
                    # Разносим заходы во времени, а не бьём очередью.
                    if details_fetched:
                        time.sleep(random.uniform(*DETAIL_PAUSE_S))
                    details, ok = _fetch_details_safe(scraper, lst.url, search.label)
                    details_fetched += 1
                    reason = quality.broken_reason(details, extra=broken_extra)
                    unchecked = not ok
            if reason and search.on_broken == "skip":
                log.info("[%s] пропуск, похоже нерабочая («%s»): %s | %s",
                         search.label, reason, lst.title, lst.price)
                store.mark_seen(search.label, lst.id, notified=False,
                                title=lst.title, price=lst.price)
                continue
            warning = reason  # режим flag: покажем с пометкой ⚠️
        ok = notifier.send_listing(lst, search.label, warning=warning, unchecked=unchecked,
                                   message_template=search.message_template,
                                   priority_name=prio.name if prio else None)
        if ok:
            store.mark_seen(search.label, lst.id, notified=True,
                            title=lst.title, price=lst.price)
            sent += 1
            log.info("[%s] уведомление: %s | %s", search.label, lst.title, lst.price)
        else:
            # НЕ помечаем виденным: Telegram мог быть временно недоступен
            # (моргнул туннель/сеть). Иначе объявление потеряется навсегда.
            # Останется «новым» и уйдёт в следующем цикле.
            log.warning("[%s] не отправилось, повторю в следующем цикле: %s | %s",
                        search.label, lst.title, lst.price)
        time.sleep(0.5)  # мягкий троттлинг Telegram

    if deferred:
        log.info("[%s] лимит %d уведомлений за цикл исчерпан; ещё %d подходящих "
                 "отложены до следующего цикла", search.label, max_notifications, deferred)
    if details_fetched or details_skipped:
        log.info("[%s] заходов на страницы объявлений: %d из %d разрешённых"
                 "%s", search.label, details_fetched, max_details,
                 f"; ещё {details_skipped} ушли без чтения описания" if details_skipped else "")
    # Первый запуск не в счёт: при first_run: send он и должен выгрести всё,
    # что уже лежало. Тревожно, когда столько набегает в обычном цикле.
    if sent >= FEED_WARN_PER_CYCLE and not first_run:
        log.warning("[%s] за один цикл ушло %d уведомлений — это уже лента, а не "
                    "охота. Похоже, потолок %s стоит выше рынка: под него "
                    "подходит всё подряд. Посмотри цены в пришедшем и опусти "
                    "max_price ниже самого дешёвого.",
                    search.label, sent, search.max_price)
    return sent


def check_search(search: SearchConfig, scraper: AvitoScraper, settings: Settings,
                 show_cards: bool = False) -> int:
    """Разовая проверка: показать, что бот видит и как отработали фильтры.

    Ничего не шлёт и не пишет в базу — безопасно гонять сколько угодно.
    Возвращает число подходящих объявлений.
    """
    listings = scraper.fetch(search.url, search.max_age_minutes)
    print(f"\n=== [{search.label}] найдено на странице: {len(listings)} ===")
    if not listings:
        print("  Ничего не найдено. Проверь URL (открой его в браузере) — "
              "или Авито отдал антибот-страницу.")
        return 0

    good = 0
    for lst in listings[:25]:
        price = f"{lst.price_value} ₽" if lst.price_value is not None else "цена не указана"
        age = format_age(lst.age_minutes)
        if lst.age_minutes is None:
            if lst.min_age_minutes is not None:
                age = f"старше {format_age(lst.min_age_minutes)}"
            elif lst.date_text:
                # Дата есть, но мы её не разобрали — вот это уже наша проблема.
                age += f" (дата: {lst.date_text!r})"
            else:
                age += " (даты в карточке нет)"
        head = f"{lst.title} | {price} | {age}"
        if show_cards:
            # Заголовок в тексте карточки и так есть — печатаем то, что вокруг
            # него: имя продавца и кусок описания. Ради этого флаг и заведён.
            head += f"\n      карточка: {(lst.card_text or 'пусто')[:300]}"

        reason = filters.explain(lst, search)
        if reason:
            print(f"  ✗ {head}\n      — {reason}")
            continue

        broken = None
        checked = True
        prio = _priority_rule(lst, search)
        broken_extra = () if prio else search.extra_broken_markers
        if search.on_broken != "ignore":
            broken = quality.broken_reason(lst.title, lst.card_text, extra=broken_extra)
            if broken is None and search.check_description and lst.url:
                details, checked = _fetch_details_safe(scraper, lst.url, search.label)
                broken = quality.broken_reason(details, extra=broken_extra)
        if broken and search.on_broken == "skip":
            print(f"  ✗ {head}\n      — похоже нерабочая («{broken}»)")
            continue

        good += 1
        if prio:
            head = f"🎯 {head}"
        if broken:
            print(f"  ⚠ {head}\n      — прошло, но похоже нерабочая («{broken}»)")
        elif not checked:
            print(f"  ⚠ {head}\n      — прошло, но описание прочитать не удалось")
        else:
            print(f"  ✓ {head}")
        print(f"      {'📷 ' if lst.image_url else ''}{lst.url}")

    if len(listings) > 25:
        print(f"  … и ещё {len(listings) - 25} (показаны первые 25)")

    # Считаем по ВСЕЙ выдаче, а не только по прошедшим фильтр: иначе при строгом
    # max_age проверить, извлекаются ли фото, было бы попросту не на чем.
    with_photo = [lst.image_url for lst in listings if lst.image_url]
    print(f"  ИТОГО подходящих: {good}")
    print(f"  📷 картинка найдена у {len(with_photo)} из {len(listings)}")
    if with_photo:
        # Показываем саму ссылку: именно её мы отдаём Telegram, и если фото не
        # уходит, по ней сразу видно почему (например, адрес без протокола).
        print(f"     пример ссылки: {with_photo[0]}")
    else:
        print("     Фото не извлекаются — уведомления придут текстом. Пришли этот вывод.")

    # Неразобранная дата не отсеивается по max_age — значит фильтр свежести
    # для таких объявлений просто не работает, и молчать об этом нельзя.
    no_age = [lst for lst in listings if lst.age_minutes is None]
    dated = [lst for lst in listings if lst.age_minutes is not None]
    if no_age and search.max_age_minutes is not None:
        oldest = max((lst.age_minutes for lst in dated), default=None)
        if oldest is not None:
            # Норма, а не поломка: Авито показывает относительную дату примерно
            # неделю, дальше её в карточке просто нет. Раз выдача по дате,
            # всё недатированное лежит ниже датированного — значит оно старше.
            print(f"  · без даты: {len(no_age)} из {len(listings)} — все они идут ниже "
                  f"датированных, то есть старше {format_age(oldest)}")
            if search.require_age:
                print("    и отсеяны как заведомо не подходящие по свежести")
        elif search.require_age:
            print(f"  ⚠ даты нет НИ У ОДНОГО из {len(listings)} — все отсеяны "
                  "из-за require_age: true. Поставь require_age: false "
                  "и пришли этот вывод.")
        else:
            print(f"  ⚠ даты нет ни у одного из {len(listings)} — "
                  "фильтр свежести не работает. Пришли этот вывод.")
    # Дата в карточке есть, но мы её не поняли — вот это уже наша поломка.
    unparsed = sum(1 for lst in no_age if lst.date_text)
    if unparsed:
        print(f"  ⚠ дата есть, но не разобрана у {unparsed} — пришли этот вывод")

    # Самое свежее в выдаче: сразу видно, дело в фильтрах или объявлений просто нет.
    ages = [lst.age_minutes for lst in listings if lst.age_minutes is not None]
    if ages:
        print(f"  🕒 самое свежее объявление: {format_age(min(ages))}")
        if search.max_age_minutes is not None and min(ages) > search.max_age_minutes:
            print(f"     Это старше твоего max_age ({format_age(search.max_age_minutes)}) — "
                  "поэтому присылать сейчас нечего. Бот исправен, объявлений нет.")
    return good


def run_check(settings: Settings, show_cards: bool = False) -> int:
    """Режим --check: проверить конфиг, Telegram и каждый поиск. Ничего не отправляя."""
    print("\n### Проверка настройки ###")

    notifier = TelegramNotifier(settings.telegram_token, settings.telegram_chat_id,
                                proxy=settings.telegram_proxy, api_base=settings.telegram_api_base,
                                image_proxy=settings.proxy)
    bot = notifier.check()
    if bot:
        print(f"  ✓ Telegram: токен рабочий, бот @{bot}")
    else:
        print("  ✗ Telegram: токен не принят. Проверь TELEGRAM_BOT_TOKEN в .env "
              "(и доступность api.telegram.org — при блокировках задай TELEGRAM_API_BASE).")

    print(f"  · Поисков в конфиге: {len(settings.searches)}")
    print(f"  · База виденных: {settings.db_path}")
    print(f"  · Прокси для Авито: {settings.proxy or 'нет (напрямую)'}")
    print(f"  · Прокси для Telegram: {settings.telegram_proxy or 'нет (напрямую)'}")

    total = 0
    try:
        with AvitoScraper(headless=settings.headless, proxy=settings.proxy,
                          user_agent=settings.user_agent, timeout_ms=settings.request_timeout_ms,
                          executable_path=settings.executable_path,
                          user_data_dir=settings.user_data_dir) as scraper:
            for search in settings.searches:
                try:
                    total += check_search(search, scraper, settings, show_cards=show_cards)
                except AntibotError as e:
                    print(f"\n=== [{search.label}] ===\n  ✗ {e}\n"
                          "     Нужен российский IP или PROXY в .env.")
                except Exception as e:  # noqa: BLE001
                    print(f"\n=== [{search.label}] ===\n  ✗ ошибка: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"\n✗ Не удалось запустить браузер: {e}\n"
              "  Скорее всего не установлен Chromium: выполни `playwright install chromium`.")
        return 1

    # --check ходит на Авито тем же браузером, и адрес не различает, кто именно
    # запросил. Отмечаемся (если база уже есть), чтобы запуск бота следом не
    # ушёл сразу в 429. Самих объявлений это не касается.
    _record_cycle(settings)

    print(f"\nГотово. Подходящих объявлений сейчас: {total}.")
    print("Если всё выглядит правильно — запускай без флагов: .venv/bin/python -m avito_watcher.main\n")
    return 0


def _cooldown_ceiling(settings: Settings) -> int:
    """Предел паузы при блокировках.

    Пауза нужна, чтобы лимит по IP успел спасть. Но она не должна съедать окно
    свежести: если ждать час при max_age в час, объявление состарится, пока мы
    отсиживаемся, и мы его не увидим вовсе. Поэтому берём половину самого
    короткого окна — так у объявления остаётся хотя бы одна попытка попасться.
    """
    windows = [s.max_age_minutes for s in settings.searches if s.max_age_minutes]
    if not windows:
        return BLOCKED_COOLDOWN_MAX_S
    return max(60, min(BLOCKED_COOLDOWN_MAX_S, min(windows) * 60 // 2))


def _record_cycle(settings: Settings) -> None:
    """Отмечает в базе, что запрос к Авито только что был.

    Базы ещё нет — значит бота тут не запускали, и защищать нечего. Создавать
    её ради одной отметки нельзя: --check обещает не оставлять следов, и на
    этом обещании держится право гонять его сколько угодно.
    """
    if not Path(settings.db_path).exists():
        return
    try:
        store = SeenStore(settings.db_path)
        store.set_float(LAST_CYCLE_KEY, time.time())
        store.close()
    except sqlite3.Error as e:
        # База занята работающим ботом — не повод падать: отметка нужна лишь
        # для вежливой паузы, без неё всё работает как раньше.
        log.info("Не смог отметить время захода: %s", e)


def _wait_out_previous_run(settings: Settings, store: SeenStore) -> None:
    """Не начинать сразу после перезапуска, если прошлый заход был только что.

    Лимит Авито считается по адресу, а не по процессу: для него перезапуск
    службы — просто ещё один запрос подряд. Обычный `systemctl restart` через
    минуту после проверки съедал бюджет и сразу ловил 429, а перезапускают
    как раз тогда, когда что-то чинят, — то есть чаще обычного.
    """
    last = store.get_float(LAST_CYCLE_KEY)
    if last is None:
        return
    left = settings.poll_interval_min - (time.time() - last)
    if left <= 0:
        return
    log.info("Прошлый заход был %.0f мин назад. Жду ещё %.0f мин, иначе запрос "
             "уйдёт в лимит адреса и вернётся 429.",
             (time.time() - last) / 60, left / 60)
    _sleep_interruptibly(left)


def _sleep_interruptibly(delay: float) -> None:
    """Спит короткими кусками, чтобы быстро реагировать на сигнал остановки."""
    slept = 0.0
    while slept < delay and not _stop:
        time.sleep(min(1.0, delay - slept))
        slept += 1.0


class _Stats:
    """Счётчики между сводками."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.cycles = 0
        self.blocked = 0
        self.notified = 0
        # Сколько карточек бот вообще разобрал и по каким поискам. Без этого
        # «новых подходящих: 0» читается двусмысленно: то ли выдача пустая, то
        # ли она полна, но всё уже виденное или дороже потолка. Снаружи это
        # ровно то, что человек и хочет знать, глядя на ноль.
        self.looked = 0
        self.labels: set[str] = set()


def _heartbeat_text(stats: "_Stats", store: SeenStore, minutes: int) -> str:
    """Короткий отчёт: жив ли бот и почему молчит.

    Нужен потому, что «ничего не приходит» неотличимо снаружи от «бот упал».
    Без такой сводки единственный способ это выяснить — лезть в журнал по SSH,
    а под рукой не всегда даже компьютер.
    """
    lines = [f"🤖 Бот жив. За последние {format_age(minutes)}:",
             f"· проверок: {stats.cycles}, из них заблокировано: {stats.blocked}",
             f"· просмотрено карточек: {stats.looked}",
             f"· новых подходящих: {stats.notified}"]
    if stats.labels:
        lines.append(f"· поиски: {', '.join(sorted(stats.labels))}")

    last = store.get_float(LAST_CYCLE_KEY)
    if last:
        lines.append(f"· последняя проверка: {format_age(int((time.time() - last) / 60))} назад")

    if stats.cycles and stats.blocked >= stats.cycles:
        lines.append("")
        lines.append("⚠️ Авито не пускает совсем — объявления не приходят поэтому, "
                     "а не потому, что их нет.")
    elif not stats.notified:
        lines.append("")
        if stats.looked:
            lines.append(f"Выдачу бот видит — разобрал {stats.looked} карточек. "
                         "Просто среди них нет новых, которые прошли бы фильтры "
                         "и потолок цены.")
        else:
            lines.append("Тишина здесь означает «новых объявлений не было». "
                         "Проверки идут, бот работает.")
    return "\n".join(lines)


def _maybe_heartbeat(settings: Settings, store: SeenStore,
                     notifier: TelegramNotifier, stats: "_Stats") -> None:
    minutes = settings.heartbeat_minutes
    if not minutes:
        return
    now = time.time()
    last = store.get_float(HEARTBEAT_KEY)
    if last is None:
        # Первый запуск: отсчитываем от текущего момента, а не шлём сразу.
        store.set_float(HEARTBEAT_KEY, now)
        return
    if now - last < minutes * 60:
        return
    if notifier.send_message(_heartbeat_text(stats, store, minutes)):
        store.set_float(HEARTBEAT_KEY, now)
        stats.reset()


def _pause_active() -> bool:
    """Стоит ли сейчас флаг «браузером управляют руками»."""
    flag = Path(resolve(PAUSE_FILE))
    try:
        age = time.time() - flag.stat().st_mtime
    except OSError:
        return False
    if age > PAUSE_MAX_S:
        log.warning("Флаг паузы %s не обновлялся %.0f мин — считаю забытым "
                    "и продолжаю работу.", flag, age / 60)
        return False
    return True


def _loop(scraper, settings: Settings, store: SeenStore,
          notifier: TelegramNotifier, once: bool = False) -> None:
    """Основной цикл: проверить все поиски, поспать, повторить.

    Отдельно от run(), чтобы цикл можно было прогнать в тестах с подменённым
    скрапером — иначе логика пауз при блокировке ничем не проверяется.
    """
    blocked_streak = 0   # сколько циклов подряд Авито нас не пустил
    alerted = False      # уже писали в Telegram про блокировку?
    cooldown_max = _cooldown_ceiling(settings)

    _wait_out_previous_run(settings, store)

    stats = _Stats()
    cycle = 0
    while not _stop:
        # Проверяем до всего остального: заход на Авито стоит бюджета адреса,
        # а профиль браузера сейчас занят человеком.
        if _pause_active():
            if once:
                log.warning("Стоит флаг паузы (%s): браузером управляют руками. "
                            "Убери файл, если это не так.", PAUSE_FILE)
                return
            log.info("Пауза: экран отдан человеку, к Авито не хожу.")
            _sleep_interruptibly(30)
            continue

        ok_count = 0
        blocked_count = 0
        block_shot = None   # снимок последней страницы блокировки за цикл

        # В режиме очереди за цикл проверяется один поиск. Число запросов к
        # Авито тогда не растёт с числом категорий — а именно оно упирается
        # в лимит адреса, а не количество поисков само по себе.
        if settings.rotate_searches and settings.searches:
            due = [settings.searches[cycle % len(settings.searches)]]
            log.info("Очередь: проверяю [%s] (%d из %d)", due[0].label,
                     cycle % len(settings.searches) + 1, len(settings.searches))
        else:
            due = settings.searches
        cycle += 1

        for search in due:
            if _stop:
                break
            try:
                stats.notified += process_search(
                    search, scraper, store, notifier,
                    settings.max_notifications_per_cycle,
                    settings.max_detail_fetches_per_cycle,
                    stats=stats,
                )
                stats.labels.add(search.label)
                ok_count += 1
            except AntibotError as e:
                blocked_count += 1
                log.warning("[%s] %s", search.label, e)
                if e.screenshot:
                    block_shot = e.screenshot
            except Exception as e:  # noqa: BLE001 - один сбойный поиск не должен ронять цикл
                log.exception("[%s] ошибка при обработке: %s", search.label, e)
            time.sleep(random.uniform(2, 5))  # пауза между разными поисками

        store.set_float(LAST_CYCLE_KEY, time.time())
        stats.cycles += 1
        if blocked_count and blocked_count >= ok_count:
            stats.blocked += 1
        _maybe_heartbeat(settings, store, notifier, stats)

        if _stop or once:
            break

        # Цикл считаем заблокированным, если блокировок не меньше, чем удачных
        # поисков. Условие «не прошёл ни один» было слишком мягким: при трёх
        # блокировках из четырёх счётчик сбрасывался, бот молчал о проблеме и
        # не сбавлял темп — то есть продолжал долбить уже лимитированный IP.
        if blocked_count and blocked_count >= ok_count:
            blocked_streak += 1
            log.warning("Заблокировано поисков: %d из %d", blocked_count,
                        blocked_count + ok_count)
        else:
            if alerted:
                notifier.send_message("✅ Авито снова открывается, продолжаю следить.")
                alerted = False
            blocked_streak = 0

        if blocked_streak:
            delay = BLOCKED_COOLDOWN_S * 2 ** (blocked_streak - 1)
            # Джиттер добавляем ДО ограничения, иначе потолок превращается
            # в потолок с довеском: сначала разброс, потом жёсткий предел.
            delay = min(delay + random.uniform(0, delay * 0.2), cooldown_max)
            log.warning(
                "Авито блокирует наш IP (циклов подряд: %d). Пауза %.0f мин: "
                "лимит снимается только временем без запросов.",
                blocked_streak, delay / 60,
            )
            if blocked_streak == BLOCKED_ALERT_AFTER and not alerted:
                alerted = True
                text = ("⚠️ Авито блокирует запросы с этого IP. Жду, пока лимит спадёт — "
                        "объявления пока не приходят. Напишу, когда восстановится.\n\n"
                        "Посмотри на снимок: если там кнопка или пазл — это капча, её "
                        "можно решить руками с телефона (screen.sh на мини-ПК). Если "
                        "«Доступ ограничен» или «проблема с IP» — нажимать нечего, "
                        "лимит снимается только временем.")
                # Со снимком страницы: видно, заглушка это про лимит или капча,
                # которую в принципе можно решить.
                if not (block_shot and notifier.send_photo(block_shot, text)):
                    notifier.send_message(text)
        else:
            delay = random.uniform(settings.poll_interval_min, settings.poll_interval_max)
            log.info("Пауза %.0f сек до следующей проверки...", delay)

        _sleep_interruptibly(delay)


def run(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="avito_watcher",
        description="Мониторинг новых объявлений на Авито с уведомлениями в Telegram.",
    )
    parser.add_argument("--check", action="store_true",
                        help="разовая проверка настройки: что бот видит и как отработали "
                             "фильтры. Ничего не шлёт и не пишет в базу")
    parser.add_argument("--cards", action="store_true",
                        help="вместе с --check: печатать текст карточки целиком. "
                             "По нему видно, кто продавец (магазин, скупка), и по "
                             "чему настраивать exclude_card_keywords")
    parser.add_argument("--once", action="store_true",
                        help="один проход по всем поискам и выход (удобно для cron)")
    parser.add_argument("--config", default="config.yaml",
                        help="путь к config.yaml (по умолчанию ./config.yaml)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Если рядом лежит папка browsers (так собирается сборка под Windows) —
    # берём браузер оттуда, чтобы её можно было просто скопировать на другую
    # машину и запустить.
    if (bundled := setup_bundled_browsers()):
        log.info("Использую браузер из %s", bundled)

    try:
        settings: Settings = load_settings(args.config)
    except ConfigError as e:
        log.error("Ошибка конфигурации: %s", e)
        return 2

    if args.check:
        return run_check(settings, show_cards=args.cards)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    store = SeenStore(settings.db_path)
    notifier = TelegramNotifier(
        settings.telegram_token,
        settings.telegram_chat_id,
        proxy=settings.telegram_proxy,
        api_base=settings.telegram_api_base,
        # Картинки лежат на CDN Авито — качаем их тем же маршрутом, что и выдачу.
        image_proxy=settings.proxy,
    )

    labels = ", ".join(s.label for s in settings.searches)
    if args.once:
        log.info("Разовый проход. Поисков: %d (%s).", len(settings.searches), labels)
    else:
        log.info("Старт мониторинга. Поисков: %d (%s). Интервал: %d-%d сек.",
                 len(settings.searches), labels,
                 settings.poll_interval_min, settings.poll_interval_max)
        notifier.send_message(
            f"✅ Бот запущен. Слежу за {len(settings.searches)} поиском(ами): {labels}"
        )

    try:
        with AvitoScraper(
            headless=settings.headless,
            proxy=settings.proxy,
            user_agent=settings.user_agent,
            timeout_ms=settings.request_timeout_ms,
            executable_path=settings.executable_path,
            user_data_dir=settings.user_data_dir,
        ) as scraper:
            _loop(scraper, settings, store, notifier, once=args.once)
    finally:
        store.close()
        log.info("Остановлен.")

    return 0


if __name__ == "__main__":
    sys.exit(run())
