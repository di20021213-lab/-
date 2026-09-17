#!/usr/bin/env bash
# Кто на ЭТОЙ машине шлёт в Telegram — и шлёт ли вообще.
#
#     bash deploy/whoami.sh
#
# Нужен, когда сообщения от бота приходят, а машина, на которой он должен
# работать, выключена или разобрана. Токен один, и Telegram не показывает, кто
# именно им пользуется, — значит опрашивать надо каждую машину по очереди.
#
# Ничего не меняет и не останавливает. Токен не печатает: только его хвост,
# по которому можно сверить, тот ли это бот, не выдавая сам токен.

set -u

BOT_DIR="${BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

echo "=== $(hostname) ==="
echo "  папка бота:     $BOT_DIR"

if [ -f "$BOT_DIR/.env" ]; then
    # Показываем только хвост: по нему видно, тот же это бот или другой, а
    # восстановить по нему токен нельзя.
    tail=$(grep -m1 '^TELEGRAM_BOT_TOKEN=' "$BOT_DIR/.env" 2>/dev/null | sed 's/.*\(.\{6\}\)$/\1/')
    chat=$(grep -m1 '^TELEGRAM_CHAT_ID=' "$BOT_DIR/.env" 2>/dev/null | cut -d= -f2)
    echo "  токен здесь:    …${tail:-НЕТ}  (chat_id: ${chat:-нет})"
else
    echo "  токен здесь:    .env отсутствует"
fi

if [ -f "$BOT_DIR/config.yaml" ]; then
    echo "  поиски в конфиге:"
    grep '^\s*- label:' "$BOT_DIR/config.yaml" | sed 's/.*- label: /      /'
else
    echo "  config.yaml отсутствует"
fi

echo
echo "  Запущенные процессы бота:"
# Ищем именно питон с модулем, а не слово «avito_watcher» где попало: иначе в
# список попадает любая команда, в которой это слово упомянуто, — например та,
# которой этот скрипт и правят.
procs=$(pgrep -af "python.*avito_watcher" 2>/dev/null)
if [ -n "$procs" ]; then
    echo "$procs" | sed 's/^/      /'
else
    echo "      нет"
fi

echo
echo "  Службы:"
for unit in avito-watcher avito-tunnel; do
    state=$(systemctl is-active "$unit" 2>/dev/null || echo "нет такой службы")
    echo "      $unit: $state"
done

echo
echo "  Задания по расписанию (cron), упоминающие бота:"
# grep в конвейере с sed не даёт узнать, нашлось ли что-нибудь: код возврата
# приходит от sed, и «|| echo нет» не срабатывает никогда.
jobs=$({ crontab -l 2>/dev/null; cat /etc/crontab /etc/cron.d/* 2>/dev/null; } | grep -i "avito")
if [ -n "$jobs" ]; then
    echo "$jobs" | sed 's/^/      /'
else
    echo "      нет"
fi
