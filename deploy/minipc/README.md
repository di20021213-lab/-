# Развёртывание на домашнем мини-ПК

Схема проще, чем на VDS: Авито открывается прямо с домашнего IP — для антибота
это лучший вариант, который вообще бывает. Через зарубежную VDS ходит **только**
Telegram, потому что `api.telegram.org` из России не открывается.

```
  Домашний мини-ПК                        Зарубежная VDS
  ┌────────────────────────┐              ┌──────────────┐
  │ avito-watcher (бот)    │              │              │
  │      │                 │              │  sshd        │
  │      ├─ Авито ─────────┼──────────────┼──► напрямую, с домашнего IP
  │      │                 │              │              │
  │      └─ Telegram ──────┼──ssh-туннель─┼──► api.telegram.org
  │         socks5h://     │              │              │
  │         127.0.0.1:1080 │              │              │
  └────────────────────────┘              └──────────────┘
```

Дальше всё от пользователя `danila`, код — в `~/avito-watcher`.
Если у тебя другое имя или папка — поправь их в командах и в юнитах.

---

## 1. Туннель до зарубежной VDS

Telegram без него не заработает: `--check` покажет
`Network is unreachable` — это не про токен, это про то, что до Telegram
просто нет маршрута.

```bash
sudo apt update && sudo apt install -y autossh

# Ключ (если ещё нет). -N "" — без парольной фразы, иначе туннель
# при старте будет ждать ввода, которого в systemd некому сделать.
ls ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519

# Кладём ключ на VDS. Пароль от VDS спросит РОВНО ОДИН РАЗ — это нормально,
# ровно затем и копируем ключ, чтобы больше не спрашивал.
ssh-copy-id root@87.58.205.159

# Проверка: должно напечатать ok и не спросить пароль.
ssh -i ~/.ssh/id_ed25519 root@87.58.205.159 echo ok
```

Пока последняя команда просит пароль — дальше идти нет смысла.

## 2. Сервис туннеля

```bash
cd ~/avito-watcher
sudo cp deploy/minipc/avito-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now avito-tunnel

systemctl status avito-tunnel --no-pager
ss -lntp | grep 1080          # должен слушать 127.0.0.1:1080
```

## 3. `.env`

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Авито — НАПРЯМУЮ с домашнего IP. PROXY оставляем пустым.
# Telegram — через туннель. socks5h (с буквой h) = DNS резолвится
# на зарубежной VDS, это критично при блокировках.
TELEGRAM_PROXY=socks5h://127.0.0.1:1080
```

`PLAYWRIGHT_BROWSERS_PATH` здесь **не нужен**: браузер лежит в
`~/.cache/ms-playwright`, куда Playwright ставит его по умолчанию.

## 4. Проверка

```bash
cd ~/avito-watcher
.venv/bin/python -m avito_watcher.main --check
```

Ждём две зелёные строки:

```
  ✓ Telegram: токен рабочий, бот @...
=== [...] найдено на странице: N ===
```

Ругается на антибот — запусти диагностику, она скажет, в IP дело или в браузере:

```bash
.venv/bin/python diag.py
```

## 5. Сервис бота

```bash
sudo cp deploy/minipc/avito-watcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now avito-watcher

journalctl -u avito-watcher -f      # выйти из просмотра логов: Ctrl+C
```

`enable` — чтобы бот поднимался сам после перезагрузки мини-ПК.
С этого момента можно закрывать SSH-сессию: бот работает как системная служба,
а не как процесс твоего терминала.

---

## Если что-то не так

| Симптом | Причина / решение |
|---|---|
| `status=1/FAILURE`, в логе «Не найден файл конфигурации» | Юнит смотрит не в ту папку. Проверь `WorkingDirectory` в `/etc/systemd/system/avito-watcher.service` — он должен совпадать с тем, куда ты клонировал код |
| `Telegram ... Network is unreachable` | Туннель не поднят: `systemctl status avito-tunnel`. Или в `.env` нет `TELEGRAM_PROXY` |
| `✗ Telegram: токен не принят` при живом туннеле | Неверный токен в `.env` |
| `Антибот/капча Авито` | `.venv/bin/python diag.py` — он разделит «забанен IP» и «спалили браузер» |
| Бот пишет «не отправилось, повторю» | Туннель моргнул. Объявление не потеряно: оно не помечено виденным и уйдёт следующим циклом |
