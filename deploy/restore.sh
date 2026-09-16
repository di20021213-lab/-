#!/usr/bin/env bash
# Развернуть копию, снятую deploy/backup.sh, обратно на Linux.
#
#     bash deploy/restore.sh ~/avito-backup-20260916-1830.tgz
#
# Обратная сторона backup.sh. Файлы кладутся на места, права восстанавливаются
# (ключ SSH без 600 не примут, .env с чужими правами читает кто угодно), юниты
# systemd НЕ включаются сами — их надо посмотреть глазами и запустить руками.

set -uo pipefail

ARCHIVE="${1:-}"
BOT_DIR="${BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
    echo "Укажи архив: bash deploy/restore.sh ~/avito-backup-ГГГГММДД-ЧЧММ.tgz"
    exit 1
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

tar xzf "$ARCHIVE" -C "$STAGE" || { echo "✗ Архив не разворачивается"; exit 1; }
SRC="$STAGE/avito-backup"
[ -d "$SRC" ] || { echo "✗ Это не копия от backup.sh: внутри нет avito-backup/"; exit 1; }

echo "Разворачиваю $ARCHIVE в $BOT_DIR"
[ -f "$SRC/README-BACKUP.txt" ] && sed -n '3,5p' "$SRC/README-BACKUP.txt" | sed 's/^/  /'
echo

# Перезаписывать молча нельзя: в config.yaml на этой машине могли уже что-то
# поправить, и потерять правку хуже, чем лишний раз спросить.
if [ -f "$BOT_DIR/config.yaml" ] || [ -f "$BOT_DIR/.env" ]; then
    echo "В $BOT_DIR уже есть .env или config.yaml."
    read -r -p "Перезаписать их из архива? [y/N] " answer
    case "$answer" in
        y|Y|д|Д) ;;
        *) echo "Ничего не трогаю. Разверни архив руками: tar xzf $ARCHIVE"; exit 0 ;;
    esac
fi

if [ -d "$SRC/bot" ]; then
    cp -a "$SRC/bot/." "$BOT_DIR/" && echo "  ✓ данные бота на месте"
    [ -f "$BOT_DIR/.env" ] && chmod 600 "$BOT_DIR/.env" && echo "  ✓ .env закрыт (600)"
fi

if [ -d "$SRC/ssh" ] && [ -n "$(ls -A "$SRC/ssh" 2>/dev/null)" ]; then
    mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
    cp -a "$SRC/ssh/." "$HOME/.ssh/"
    # Закрытый ключ с открытыми правами ssh просто не примет.
    find "$HOME/.ssh" -maxdepth 1 -name 'id_*' ! -name '*.pub' -exec chmod 600 {} +
    find "$HOME/.ssh" -maxdepth 1 -name 'id_*.pub' -exec chmod 644 {} +
    echo "  ✓ ключи SSH на месте, права выставлены"
fi

if [ -d "$SRC/systemd" ] && [ -n "$(ls -A "$SRC/systemd" 2>/dev/null)" ]; then
    # Кладём рядом с ботом, а не во временную папку: она исчезнет на выходе, и
    # совет «скопируй их сам» указывал бы на несуществующий путь.
    KEEP="$BOT_DIR/restored-systemd"
    mkdir -p "$KEEP" && cp -a "$SRC/systemd/." "$KEEP/"
    echo
    echo "  Юниты systemd сложены в $KEEP — сам я их НЕ ставлю."
    echo "  В них прописаны пути и адрес сервера со старой машины, сверь глазами:"
    for u in "$KEEP"/*; do echo "      $u"; done
    echo "  Когда сверишь:"
    echo "      sudo cp $KEEP/* /etc/systemd/system/"
    echo "      sudo systemctl daemon-reload"
    echo "      sudo systemctl enable --now avito-watcher"
fi

echo
echo "Готово. Проверить, не запуская бота:"
echo "    .venv/bin/python -m avito_watcher.main --check"
