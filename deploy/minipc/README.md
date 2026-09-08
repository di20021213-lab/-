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

## 2а. Доступ к мини-ПК с телефона

Тот же туннель заодно пробрасывает SSH мини-ПК на VDS (`-R 127.0.0.1:2222`).
Белый IP дома и проброс портов на роутере при этом не нужны: соединение
устанавливает сам мини-ПК изнутри домашней сети.

Порт на VDS слушает **только localhost**, наружу он не торчит. Поэтому с телефона
подключаемся в два прыжка: сначала на VDS, оттуда — на мини-ПК. Termius это умеет
штатно, отдельного приложения не надо.

Сначала убедись с самой VDS, что проброс живой:

```bash
ssh root@87.58.205.159
ss -lntp | grep 2222        # должен слушать 127.0.0.1:2222
ssh -p 2222 danila@localhost 'hostname'   # должно ответить: avito
```

Дальше в Termius на телефоне:

1. **Hosts → +** — заведи VDS: адрес `87.58.205.159`, порт `22`, юзер `root`.
2. **Hosts → +** — заведи мини-ПК: адрес `localhost`, порт `2222`, юзер `danila`,
   пароль от мини-ПК.
3. У второго хоста в поле **Jump host / Proxy** выбери первый (VDS) и сохрани.

Теперь тап по второму хосту — и ты в мини-ПК откуда угодно.

Из обычного терминала то же самое одной строкой:

```bash
ssh -J root@87.58.205.159 -p 2222 danila@localhost
```

Одна настройка на стороне VDS — чтобы после обрыва связи порт 2222 не оставался
занятым «мёртвым» соединением и туннель мог переподключиться:

```bash
# на ЗАРУБЕЖНОЙ VDS, от root
echo -e "ClientAliveInterval 30\nClientAliveCountMax 3" >> /etc/ssh/sshd_config
systemctl restart ssh
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

## 4а. Если IP под лимитом: сторож

Поймал `429` и ждёшь, когда отпустит? Не проверяй руками — каждая проверка
продлевает лимит. Поставь сторож: он делает **один** HTTP-запрос раз в час
(без браузера, без повторов), пишет результат в `ip_watch.log` и присылает в
Telegram сообщение в тот момент, когда Авито снова начнёт пускать. Повторно об
одном и том же не пишет.

```bash
cd ~/avito-watcher
sudo cp deploy/minipc/avito-ipwatch.service /etc/systemd/system/
sudo cp deploy/minipc/avito-ipwatch.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now avito-ipwatch.timer
```

Посмотреть накопленное и когда следующая проверка:

```bash
cat ip_watch.log
systemctl list-timers avito-ipwatch --no-pager
```

Когда IP отпустит и бот заработает — сторож больше не нужен:

```bash
sudo systemctl disable --now avito-ipwatch.timer
```

Чаще раза в час ставить нельзя: `429` снимается только временем без запросов.

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
