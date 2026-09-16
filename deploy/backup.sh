#!/usr/bin/env bash
# Забрать с мини-ПК всё, чего нет в git, — одним архивом.
#
#     bash ~/avito-watcher/deploy/backup.sh
#     bash ~/avito-watcher/deploy/backup.sh /media/usb/avito.tgz
#     bash ~/avito-watcher/deploy/backup.sh --no-profile
#
# Зачем отдельный скрипт, когда есть одна строчка с tar. Ровно эта строчка и
# лежала в CHECKLIST.md, и она забывала browser-profile и market.sqlite3, а
# seen.sqlite3 копировала обычным cp — на живой базе так можно получить
# рваный файл, и выяснится это уже после того, как диск стёрли.
#
# Скрипт ничего не останавливает и не меняет: бот может работать.

set -uo pipefail

BOT_DIR="${BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
OUT=""
WITH_PROFILE=1

for arg in "$@"; do
    case "$arg" in
        --no-profile) WITH_PROFILE=0 ;;
        -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
        *) OUT="$arg" ;;
    esac
done
OUT="${OUT:-$HOME/avito-backup-$(date +%Y%m%d-%H%M).tgz}"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/avito-backup"
mkdir -p "$ROOT/bot" "$ROOT/ssh" "$ROOT/systemd"

took=()
missed=()

note_took() { took+=("$1"); }
note_missed() { missed+=("$1"); }

copy_plain() {
    # $1 — путь относительно BOT_DIR, $2 — человеческое имя
    if [ -e "$BOT_DIR/$1" ]; then
        cp -a "$BOT_DIR/$1" "$ROOT/bot/" && note_took "$2"
    else
        note_missed "$2"
    fi
}

copy_sqlite() {
    # Живую базу нельзя копировать как файл: бот может писать в неё прямо
    # сейчас, и в копию попадёт половина транзакции. Штатный способ —
    # sqlite3 .backup; консольного sqlite3 на мини-ПК нет, поэтому питоном,
    # он делает ровно то же самое.
    local src="$BOT_DIR/$1"
    [ -f "$src" ] || { note_missed "$2"; return; }
    if python3 - "$src" "$ROOT/bot/$1" <<'PY'
import sqlite3
import sys

src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close()
src.close()
PY
    then
        note_took "$2"
    else
        # База не читается — но остальное забрать всё равно надо.
        note_missed "$2 (не открылась, см. вывод выше)"
    fi
}

echo "Собираю копию из $BOT_DIR"

copy_plain ".env"            ".env (токен бота, chat_id, прокси)"
copy_plain "config.yaml"     "config.yaml (поиски, цены, стоп-слова)"
copy_plain ".ip_watch_state" "отметка слежения за адресом"
copy_sqlite "seen.sqlite3"   "seen.sqlite3 (что уже присылали)"
copy_sqlite "market.sqlite3" "market.sqlite3 (разведка рынка)"

# Список игр под своим именем: games.example.txt лежит в git, а вот games.txt
# человек правит руками, и он нигде больше не хранится.
for f in "$BOT_DIR"/*.txt; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in
        *.example.txt) continue ;;
    esac
    cp -a "$f" "$ROOT/bot/" && note_took "$(basename "$f")"
done

if [ "$WITH_PROFILE" = 1 ] && [ -d "$BOT_DIR/browser-profile" ]; then
    # Куки Авито. Без них бот на новой машине — посетитель с улицы, и первые
    # заходы чаще упираются в антибота. Это самая тяжёлая часть архива,
    # отключается --no-profile.
    cp -a "$BOT_DIR/browser-profile" "$ROOT/bot/" \
        && note_took "browser-profile ($(du -sh "$BOT_DIR/browser-profile" 2>/dev/null | cut -f1))"
elif [ "$WITH_PROFILE" = 0 ]; then
    note_missed "browser-profile (пропущен по --no-profile)"
else
    note_missed "browser-profile"
fi

# Ключ туннеля. Без него туннель на зарубежный сервер не поднимется, а завести
# новый — значит идти на сервер и прописывать его в authorized_keys.
for key in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_rsa" "$HOME/.ssh/id_rsa.pub"; do
    [ -f "$key" ] && cp -a "$key" "$ROOT/ssh/" && note_took "ssh/$(basename "$key")"
done

# Юниты systemd берём установленные, а не те, что в git: в них подставлены
# твои пути и адрес сервера.
for unit in /etc/systemd/system/avito-*.service /etc/systemd/system/avito-*.timer; do
    [ -e "$unit" ] && cp -a "$unit" "$ROOT/systemd/" && note_took "systemd/$(basename "$unit")"
done

commit=$(git -C "$BOT_DIR" rev-parse --short HEAD 2>/dev/null || echo "неизвестен")
branch=$(git -C "$BOT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "неизвестна")

# Через полгода будет непонятно, что это за архив и что с ним делать.
cat > "$ROOT/README-BACKUP.txt" <<EOF
Копия рабочих данных бота Авито.

Снята: $(date '+%Y-%m-%d %H:%M %Z')
Машина: $(hostname)
Код: ветка $branch, коммит $commit

ЗДЕСЬ ЛЕЖАТ СЕКРЕТЫ: .env с токеном Telegram и закрытый ключ SSH. Не
выкладывай архив никуда и не пересылай в переписке. Кому попадёт .env — тот
пишет от имени твоего бота; кому попадёт ключ — тот заходит на сервер.

ЧТО ВНУТРИ
  bot/       — класть в папку с ботом рядом с avito_watcher/
  ssh/       — в ~/.ssh (Linux) или C:\\Users\\<ты>\\.ssh (Windows)
  systemd/   — в /etc/systemd/system/ (только Linux)

ВОССТАНОВЛЕНИЕ НА WINDOWS
  1. git clone нужной ветки, см. коммит выше
  2. содержимое bot\\ скопировать в папку с ботом
  3. deploy\\windows\\setup.bat, затем check.bat
  Подробно: deploy/windows/AFTER_INSTALL.md

ВОССТАНОВЛЕНИЕ НА LINUX
  bash deploy/restore.sh путь/к/этому/архиву

ПРО browser-profile
  Это профиль Chromium с куками Авито. На другой системе он может не
  подойти — если бот сразу упирается в антибота, удали папку целиком, она
  создастся заново. Ничего, кроме куков, в ней не хранится.
EOF

tar czf "$OUT" -C "$STAGE" avito-backup || { echo "✗ Не удалось записать $OUT"; exit 1; }
chmod 600 "$OUT"

# Архив, который не разворачивается, хуже отсутствующего: на него надеются.
if ! tar tzf "$OUT" >/dev/null 2>&1; then
    echo "✗ Архив записался битым — не стирай ничего, разбираемся"
    exit 1
fi

echo
echo "Взято:"
for x in "${took[@]}"; do echo "  ✓ $x"; done
if [ ${#missed[@]} -gt 0 ]; then
    echo "Не нашлось (возможно, так и надо):"
    for x in "${missed[@]}"; do echo "  · $x"; done
fi

echo
echo "Готово: $OUT ($(du -h "$OUT" | cut -f1)), права 600"
echo "Файлов внутри: $(tar tzf "$OUT" | wc -l)"
echo
echo "ТЕПЕРЬ УНЕСИ ЕГО С ЭТОЙ МАШИНЫ — диск ты собираешься стирать."
echo "  На флешку:   cp $OUT /media/\$USER/ФЛЕШКА/"
echo "  На телефон:  scp -P 2222 ... или через тот же туннель"
echo
echo "На зарубежный сервер класть НЕ НАДО: там открыт вход root по паролю и"
echo "десятки тысяч попыток подбора в журнале. Если больше некуда — сначала"
echo "зашифруй:  gpg -c $OUT   (и увози уже .gpg)"
