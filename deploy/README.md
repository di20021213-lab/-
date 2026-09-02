# Развёртывание: бот на российской VDS, Telegram через зарубежную VDS

Схема:

```
  Российская VDS                          Зарубежная VDS
  ┌────────────────────────┐              ┌──────────────┐
  │ avito-watcher (бот)    │              │              │
  │      │                 │  SSH -D      │  sshd        │
  │      ├─ Авито ─────────┼──────────────┼──► напрямую, с российского IP
  │      │                 │              │              │
  │      └─ Telegram ──────┼──ssh-туннель─┼──► api.telegram.org
  │         socks5h://     │              │              │
  │         127.0.0.1:1080 │              │              │
  └────────────────────────┘              └──────────────┘
```

Авито ходит напрямую (нужен российский IP), Telegram — через туннель.

---

## 1. Зарубежная VDS: ничего не ставим

Нужен только рабочий SSH. Никаких прокси-серверов ставить не надо — SOCKS5
поднимает сам `ssh -D`. Открытый 3proxy/dante ставить **не нужно и опасно**:
сканеры находят открытые прокси за часы и начинают слать через них спам.

## 2. Российская VDS: подготовка

От root:

```bash
apt update
apt install -y python3-venv python3-pip git autossh

# отдельный непривилегированный пользователь для бота
adduser --disabled-password --gecos "" avito
```

## 3. Ключ для туннеля

От пользователя `avito` на РОССИЙСКОЙ VDS:

```bash
sudo -u avito -H ssh-keygen -t ed25519 -N "" -f /home/avito/.ssh/id_ed25519
sudo -u avito -H ssh-copy-id -i /home/avito/.ssh/id_ed25519.pub ВАШ_ЮЗЕР@ЗАРУБЕЖНАЯ_VDS
# проверить, что вход без пароля работает:
sudo -u avito -H ssh -i /home/avito/.ssh/id_ed25519 ВАШ_ЮЗЕР@ЗАРУБЕЖНАЯ_VDS echo ok
```

Без беспарольного входа туннель встанет на запросе пароля.

## 4. Код и зависимости

```bash
git clone -b claude/avito-gpu-parser-mmp6rr https://github.com/di20021213-lab/-.git /opt/avito-watcher
chown -R avito:avito /opt/avito-watcher
cd /opt/avito-watcher

sudo -u avito python3 -m venv .venv
sudo -u avito .venv/bin/pip install -r requirements.txt

# Браузер + системные библиотеки. --with-deps требует root, поэтому от root,
# в общую папку, которую потом читает сервис бота.
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers .venv/bin/playwright install --with-deps chromium
chmod -R a+rX /opt/pw-browsers
```

`--with-deps` важен: на голой VDS у Chromium нет системных библиотек, и без
них он молча не стартует.

## 5. Конфиг

```bash
sudo -u avito cp .env.example .env
sudo -u avito cp config.example.yaml config.yaml
sudo -u avito nano .env
```

Ключевое в `.env`:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Авито — НАПРЯМУЮ с российского IP: переменную оставляем пустой/закомментированной
# PROXY=

# Telegram — через локальный SOCKS5, который держит туннель.
# socks5h (с буквой h) = DNS резолвится на зарубежной VDS. Критично при блокировках.
TELEGRAM_PROXY=socks5h://127.0.0.1:1080
```

В `config.yaml` вставь свой URL с Авито (свой город, `pmin`/`pmax`, сортировка `s=104`).

## 6. Сервисы

```bash
# подставь свои юзера и хост в юните туннеля
cp deploy/avito-tunnel.service  /etc/systemd/system/
cp deploy/avito-watcher.service /etc/systemd/system/
nano /etc/systemd/system/avito-tunnel.service   # ВАШ_ЮЗЕР@ВАША_ЗАРУБЕЖНАЯ_VDS

systemctl daemon-reload
systemctl enable --now avito-tunnel
```

Проверь, что туннель поднялся, и прогони проверку настройки:

```bash
systemctl status avito-tunnel
ss -lntp | grep 1080          # должен слушать 127.0.0.1:1080

cd /opt/avito-watcher
sudo -u avito .venv/bin/python -m avito_watcher.main --check
```

Ждём в выводе:

```
  ✓ Telegram: токен рабочий, бот @...
  · Прокси для Авито: нет (напрямую)
  · Прокси для Telegram: socks5h://127.0.0.1:1080
=== [...] найдено на странице: N ===
```

Только когда обе строки зелёные — запускай бота:

```bash
systemctl enable --now avito-watcher
journalctl -u avito-watcher -f
```

---

## Если что-то не так

| Симптом | Причина / решение |
|---|---|
| `✗ Telegram: токен не принят` | Туннель не поднят (`systemctl status avito-tunnel`) или неверный токен |
| `найдено на странице: 0`, антибот | Российская VDS — это **датацентровый** IP, Авито их проверяет строже. См. ниже |
| `Не удалось запустить браузер` | Не выполнен `playwright install --with-deps chromium` от root |
| Бот пишет «не отправилось, повторю» | Туннель моргнул. Это нормально: объявление не потеряно, уйдёт следующим циклом |

### Про антибот на датацентровом IP

Домашний или мобильный IP для Авито выглядит естественнее, чем адрес хостинга.
С VDS выше шанс поймать капчу — особенно у крупных хостеров, чьи подсети давно
известны. Что делать, если ловишь:

1. Увеличь `poll_interval_min`/`poll_interval_max` (например, 180–360 сек).
2. Проверь, действительно ли блокирует: `--check` покажет `Антибот/капча`.
3. Если не помогает — понадобится **резидентный** российский прокси в `PROXY`
   (обычный датацентровый IPv4 тут не поможет: он такой же датацентровый,
   как и сам VDS).

Заранее покупать прокси не нужно: сначала проверь `--check` с самой VDS.
