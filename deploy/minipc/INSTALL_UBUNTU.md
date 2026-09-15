# Ubuntu Server на мини-ПК

Возврат с Windows. Почему серверная, а не обычная: без графики система ест
~400 МБ вместо ~2 ГБ, а рабочий стол на коробке без монитора не нужен.

## 1. Скачать образ

**Ubuntu Server 24.04 LTS, 64-бит.** Официально:

```
https://ubuntu.com/download/server
```

Если сайт не открывается из России — зеркало Яндекса, тот же самый файл:

```
https://mirror.yandex.ru/ubuntu-releases/24.04/
```

Нужен файл вида `ubuntu-24.04.x-live-server-amd64.iso` (около 3 ГБ).
Вариант `desktop` не бери — это как раз то, от чего мы уходим.

## 2. Записать флешку

Rufus: схема разделов **GPT**, целевая система **UEFI**.

## 3. Установка: четыре места, где легко промахнуться

**Сеть.** Мастер покажет найденные интерфейсы. Убедись, что кабельный
(`enp*`, не `wlp*`) получил адрес. Не получил — проверь кабель до того, как
идти дальше: без сети установщик не докачает пакеты.

**«Install OpenSSH server» — ОБЯЗАТЕЛЬНО отметь галочку.** Это единственный
шаг, который нельзя пропустить: без него после перезагрузки к машине не
подключиться, а монитор ты уберёшь. Если пропустил — не беда, ставится потом
командой `sudo apt install openssh-server`, но с клавиатурой у машины.

**Диск.** «Use an entire disk» — сотрёт Windows целиком, это и нужно. LVM
можно оставить включённым, он ничему не мешает.

**Пользователь.** Заведи `danila` — так совпадёт с путями в наших файлах
служб (`/home/danila/avito-watcher`).

Дополнительные пакеты (snap-и на последнем экране) не отмечай — ни один не
нужен, а память они займут.

## 4. Сразу после установки, не отходя от машины

```bash
ip -br addr        # запиши адрес в домашней сети
sudo apt update && sudo apt upgrade -y
```

И **проверь заход с телефона, пока стоишь рядом.** Потом монитор можно убрать.

## 5. Поставить бота

```bash
sudo apt install -y git python3-venv python3-pip
git clone https://github.com/di20021213-lab/- ~/avito-watcher
cd ~/avito-watcher
git checkout claude/avito-gpu-parser-mmp6rr
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install --with-deps chromium
```

`--with-deps` тут важен: на сервере без графики нет библиотек, которые нужны
Chromium, и эта команда доставит их сама.

## 6. Вернуть данные

```bash
cd ~
scp root@87.58.205.159:~/avito-backup.tgz .
tar -xzf avito-backup.tgz
chmod 600 ~/.ssh/id_ed25519
```

Из архива нужны `.env` и `seen.sqlite3` — положи их в `~/avito-watcher/`.
`config.yaml` бери свежий: `cp config.games.example.yaml config.yaml`, а список
игр собери генератором — см. `make_searches.py`.

## 7. Туннель и автозапуск

Файлы служб лежат рядом, в `deploy/minipc/`. Порядок — в [README.md](README.md):
`avito-tunnel.service` для Telegram и `avito-watcher.service` для бота.

## Про память

После установки проверь:

```bash
free -h
```

Ожидаемо: занято 300-500 МБ. Если сильно больше — скажи, разберёмся, но на
чистой серверной Ubuntu столько и должно быть.
