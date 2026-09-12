#!/usr/bin/env bash
# Виртуальный экран на мини-ПК + доступ к нему глазами, чтобы разгадать капчу.
#
# Мини-ПК стоит без монитора, а капчу надо двигать мышкой. Поднимаем невидимый
# экран (Xvfb), показываем его по VNC только на localhost и пробрасываем к тебе
# через тот же SSH, которым ты и так ходишь. Наружу ничего не открывается.
#
#   bash deploy/ozon_captcha.sh "https://ozon.ru/t/XXXX"
set -u

URL=${1:-https://www.ozon.ru/}
DISPLAY_NUM=${DISPLAY_NUM:-99}
VNC_PORT=${VNC_PORT:-5900}
HERE=$(cd "$(dirname "$0")/.." && pwd)

need=()
command -v Xvfb   >/dev/null || need+=(xvfb)
command -v x11vnc >/dev/null || need+=(x11vnc)
if [ ${#need[@]} -gt 0 ]; then
    echo "Не хватает пакетов: ${need[*]}"
    echo "Поставь одной командой:"
    echo "    sudo apt-get update && sudo apt-get install -y ${need[*]}"
    exit 1
fi

cleanup() {
    echo
    echo "Убираю за собой..."
    [ -n "${VNC_PID:-}" ] && kill "$VNC_PID" 2>/dev/null
    [ -n "${XVFB_PID:-}" ] && kill "$XVFB_PID" 2>/dev/null
    rm -f "$PASSFILE"
}
trap cleanup EXIT

echo "Поднимаю экран :$DISPLAY_NUM"
Xvfb ":$DISPLAY_NUM" -screen 0 1280x900x24 >/dev/null 2>&1 &
XVFB_PID=$!
sleep 2

# Пароль одноразовый: живёт только пока работает скрипт.
PASS=$(tr -dc 'a-zA-Z0-9' </dev/urandom | head -c 10)
PASSFILE=$(mktemp)
x11vnc -storepasswd "$PASS" "$PASSFILE" >/dev/null 2>&1

# -localhost: снаружи не подключиться никак, только через твой SSH-туннель.
x11vnc -display ":$DISPLAY_NUM" -rfbport "$VNC_PORT" -rfbauth "$PASSFILE" \
       -localhost -forever -shared -nopw >/dev/null 2>&1 &
VNC_PID=$!
sleep 1

cat <<TXT

=== Подключись к экрану ===

1) На своём компьютере или телефоне открой НОВОЕ окно и пробрось порт:

     ssh -L $VNC_PORT:127.0.0.1:$VNC_PORT danila@МИНИ-ПК

   (через сервер: ssh -J root@87.58.205.159 danila@МИНИ-ПК ...)

2) Открой любой VNC-клиент и подключись к   127.0.0.1:$VNC_PORT
   пароль:  $PASS

3) Увидишь браузер с Озоном. Двигай ползунок, собери пазл.

Я жду. Как пройдёшь — скрипт скажет сам и закроется.

TXT

cd "$HERE"
DISPLAY=":$DISPLAY_NUM" .venv/bin/python ozon_login.py "$URL"
rc=$?

if [ $rc -eq 0 ]; then
    cat <<'TXT'

Готово. Сессия лежит в профиле ozon-profile.
Проверить, что она работает:

    OZON_HEADLESS=0 DISPLAY=:99 .venv/bin/python ozon_check.py --file ozon-links.example.txt

Важно: проверки запускай ТЕМ ЖЕ браузером на ТОМ ЖЕ экране. Сессия привязана
не только к кукам, но и к отпечатку; в headless он другой, и Озон переспросит.
TXT
fi
exit $rc
