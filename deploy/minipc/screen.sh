#!/usr/bin/env bash
# Удалённый экран для мини-ПК: показать браузер бота на телефоне, чтобы решить
# капчу руками.
#
# ЗАЧЕМ. На Ubuntu Server графики нет вовсе, а SSH — это текстовый канал: в нём
# нельзя ни увидеть картинку капчи, ни ткнуть в неё. Поэтому здесь поднимается
# виртуальный экран (Xvfb), к нему цепляется VNC, и в нём открывается тот же
# самый Chromium с тем же профилем, которым ходит бот. Решённая капча ложится
# в общий профиль — бот подхватит её на следующем цикле.
#
# ЧТО ЭТО НЕ ЛЕЧИТ. Если Авито отвечает «Доступ ограничен» или HTTP 429 — это
# лимит по адресу, а не капча. Там нечего нажимать: он снимается только
# временем без запросов. Смотри, что именно бот прислал тебе в Telegram
# снимком: кнопка/пазл — сюда, «доступ ограничен» — просто ждать.
#
# ЗАПУСК на мини-ПК:   ./deploy/minipc/screen.sh
# Разово поставить:    sudo apt install -y xvfb x11vnc
#
# Всё поднимается только на время сеанса и гасится на выходе: постоянной
# памяти это не ест — ради этого мы с винды и уходили.

set -euo pipefail

DISPLAY_NUM="${DISPLAY_NUM:-:99}"
VNC_PORT="${VNC_PORT:-5900}"
GEOMETRY="${GEOMETRY:-1280x800x24}"
SESSION_MAX_MIN="${SESSION_MAX_MIN:-30}"

BOT_DIR="${BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PROFILE="${BROWSER_PROFILE_DIR:-$BOT_DIR/browser-profile}"
PAUSE_FLAG="$BOT_DIR/PAUSE.flag"
VNC_PASSWD="$HOME/.vnc/passwd"

die() { echo "ОШИБКА: $*" >&2; exit 1; }

for bin in Xvfb x11vnc; do
  command -v "$bin" >/dev/null 2>&1 || die "нет $bin. Поставь: sudo apt install -y xvfb x11vnc"
done

# Берём тот же браузер, которым ходит бот, а не системный: у него тот же
# отпечаток, и Авито не увидит смены браузера на ровном месте.
# chrome-headless-shell пропускаем намеренно — он не умеет показывать окно.
CHROME="${CHROME:-}"
if [ -z "$CHROME" ]; then
  CHROME=$(ls -d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | sort -V | tail -1 || true)
fi
[ -n "$CHROME" ] && [ -x "$CHROME" ] || die "не нашёл Chromium от Playwright. Задай путь: CHROME=/путь/к/chrome $0"

[ -d "$PROFILE" ] || die "нет профиля браузера: $PROFILE (бот хоть раз запускался?)"

# Адрес открываем тот же, на котором бота и заворачивают.
URL="${1:-}"
if [ -z "$URL" ]; then
  URL=$(grep -m1 -oE 'https://[^"'"'"' ]*avito\.ru[^"'"'"' ]*' "$BOT_DIR/config.yaml" 2>/dev/null || true)
fi
URL="${URL:-https://www.avito.ru/}"

# Пароль на VNC обязателен даже на localhost: без него любой процесс на машине
# получает твой экран и профиль с куками одной командой.
if [ ! -f "$VNC_PASSWD" ]; then
  echo "Первый запуск: придумай пароль для VNC (он спросит дважды)."
  mkdir -p "$(dirname "$VNC_PASSWD")"
  x11vnc -storepasswd "$VNC_PASSWD"
fi

XVFB_PID=""; VNC_PID=""; CHROME_PID=""; TOUCH_PID=""

# Убить процесс вместе с детьми. Просто kill по фоновой подоболочке не годится:
# она умрёт, а её `sleep` останется жить сиротой и будет держать терминал.
kill_tree() {
  local pid="$1"
  [ -n "$pid" ] || return 0
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  set +e
  for pid in "$CHROME_PID" "$VNC_PID" "$XVFB_PID" "$TOUCH_PID"; do
    kill_tree "$pid"
  done
  wait 2>/dev/null
  rm -f "$PAUSE_FLAG"
  echo
  echo "Экран погашен, пауза снята — бот продолжает сам."
}
trap cleanup EXIT INT TERM

# 1. Просим бота не трогать профиль. Флаг с истечением: если этот скрипт
#    умрёт вместе с терминалом, бот через час вернётся к работе сам.
touch "$PAUSE_FLAG"
( while sleep 60; do touch "$PAUSE_FLAG"; done ) & TOUCH_PID=$!

# 2. Ждём, пока бот закроет свой браузер. Один профиль двумя Chromium не
#    открыть: полезем раньше — уроним либо ему цикл, либо себе окно.
echo -n "Жду, пока бот освободит профиль"
for _ in $(seq 1 120); do
  pgrep -f -- "--user-data-dir=$PROFILE" >/dev/null 2>&1 || break
  echo -n "."
  sleep 2
done
echo
if pgrep -f -- "--user-data-dir=$PROFILE" >/dev/null 2>&1; then
  die "бот держит профиль больше 4 минут. Останови его: sudo systemctl stop avito-watcher"
fi

# 3. Виртуальный экран и VNC поверх него.
Xvfb "$DISPLAY_NUM" -screen 0 "$GEOMETRY" -nolisten tcp & XVFB_PID=$!
sleep 2
# -localhost: порт виден только с самой машины. Наружу он не выставляется —
# с телефона заходим через тот же SSH-туннель, что уже есть.
x11vnc -display "$DISPLAY_NUM" -rfbport "$VNC_PORT" -rfbauth "$VNC_PASSWD" \
       -localhost -forever -shared -quiet -bg >/dev/null
VNC_PID=$(pgrep -n x11vnc || true)

# 4. Тот же браузер, тот же профиль. Никаких автокликов: капчу решает человек.
#    timeout вместо фонового будильника: он сам закончится вместе с браузером,
#    когда ты закроешь окно, и не останется досыпать свои полчаса после сеанса.
DISPLAY="$DISPLAY_NUM" timeout "${SESSION_MAX_MIN}m" "$CHROME" \
  --user-data-dir="$PROFILE" \
  --window-size="${GEOMETRY%x*}" \
  --window-position=0,0 \
  --no-first-run --no-default-browser-check \
  --password-store=basic \
  "$URL" >/dev/null 2>&1 & CHROME_PID=$!

cat <<INFO

Экран готов. С телефона:

  1. Termius -> хост мини-ПК -> Port Forwarding -> Local
       Local port  $VNC_PORT
       Host        127.0.0.1
       Remote port $VNC_PORT
     Подключись, чтобы проброс поднялся.

  2. bVNC (или RealVNC Viewer) -> 127.0.0.1:$VNC_PORT -> пароль от VNC.

Реши капчу пальцем, потом закрой окно браузера — или просто нажми здесь Ctrl+C.
Сеанс сам закроется через $SESSION_MAX_MIN мин, чтобы ничего не осталось висеть.

INFO

# Ждём, пока ты закроешь окно (или пока не выйдет время сеанса).
wait "$CHROME_PID" 2>/dev/null || true
