#!/usr/bin/env bash
# Один снимок состояния: всё, что обычно приходится выяснять по частям.
#
# Запуск на мини-ПК:  bash ~/avito-watcher/deploy/status.sh
#
# Смысл в том, чтобы вместо десяти команд по переписке была одна: запустил,
# скопировал вывод целиком, отправил. Ничего не меняет и не пишет — только
# читает, поэтому гонять можно сколько угодно.
#
# Содержимое .env сюда НЕ попадает: токен бота и пароль от прокси не должны
# оказаться в переписке даже случайно.

set -u

BOT_DIR="${BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SINCE="${SINCE:-1 day ago}"

section() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
say() { printf '  %-24s %s\n' "$1" "$2"; }

section "Машина"
say "имя" "$(hostname)"
say "работает" "$(uptime -p 2>/dev/null || uptime)"
if command -v free >/dev/null; then
    say "память" "$(free -h | awk '/^Mem:/ {print $3" занято из "$2", доступно "$7}')"
fi
say "диск" "$(df -h "$BOT_DIR" | awk 'NR==2 {print $3" занято из "$2", свободно "$4}')"

section "Службы"
for unit in avito-watcher avito-tunnel; do
    state=$(systemctl is-active "$unit" 2>/dev/null || echo "нет такой службы")
    since=$(systemctl show "$unit" -p ActiveEnterTimestamp --value 2>/dev/null)
    restarts=$(systemctl show "$unit" -p NRestarts --value 2>/dev/null)
    say "$unit" "$state${since:+, с $since}${restarts:+, перезапусков: $restarts}"
done

section "Сеть"
ip route | grep -q default && say "шлюз" "$(ip route | awk '/default/ {print $3}')"
addr=$(curl -s --max-time 10 ifconfig.me 2>/dev/null)
say "публичный адрес" "${addr:-НЕ ОТВЕЧАЕТ (интернета нет?)}"
# Второй-третий прыжок в диапазоне 100.64/10 — это CGNAT провайдера, то есть
# адрес общий и бюджет запросов к Авито делится с соседями.
hops=$( { traceroute -n -w 2 -q 1 -m 4 8.8.8.8 2>/dev/null || tracepath -n -m 4 8.8.8.8 2>/dev/null; } \
        | grep -oE '(^| )(100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])|10|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9.]+' | head -1)
say "NAT провайдера" "${hops:+да, через${hops} (CGNAT — адрес общий)}${hops:-не обнаружен}"

section "Авито за $SINCE"
if command -v journalctl >/dev/null; then
    ok=$(journalctl -u avito-watcher --since "$SINCE" --no-pager 2>/dev/null | grep -c "получено объявлений")
    blocked=$(journalctl -u avito-watcher --since "$SINCE" --no-pager 2>/dev/null | grep -c "HTTP 429")
    other=$(journalctl -u avito-watcher --since "$SINCE" --no-pager 2>/dev/null | grep -c "антибот/капчу" )
    say "удачных проверок" "$ok"
    say "блокировок (429)" "$blocked"
    say "прочих отказов" "$(( other > blocked ? other - blocked : 0 ))"
    if [ "$((ok + blocked))" -gt 0 ]; then
        say "доля удачных" "$(( ok * 100 / (ok + blocked) ))%"
    fi
    sent=$(journalctl -u avito-watcher --since "$SINCE" --no-pager 2>/dev/null | grep -c "уведомление:")
    say "уведомлений ушло" "$sent"

    echo
    echo "  Последние отказы:"
    journalctl -u avito-watcher --since "$SINCE" --no-pager 2>/dev/null \
        | grep "HTTP 429" | tail -5 | awk '{print "    "$1, $2, $3}' || echo "    нет"

    echo
    echo "  Последние уведомления:"
    journalctl -u avito-watcher --since "$SINCE" --no-pager 2>/dev/null \
        | grep "уведомление:" | tail -5 | sed 's/.*уведомление: /    /' || echo "    нет"

    echo
    echo "  Последние 10 строк журнала:"
    journalctl -u avito-watcher --no-pager -n 10 2>/dev/null | sed 's/^/    /'
fi

section "Конфиг"
CFG="$BOT_DIR/config.yaml"
if [ -f "$CFG" ]; then
    n=$(grep -c '^\s*- label:' "$CFG")
    lo=$(grep -m1 'poll_interval_min:' "$CFG" | grep -oE '[0-9]+')
    hi=$(grep -m1 'poll_interval_max:' "$CFG" | grep -oE '[0-9]+')
    say "поисков" "$n"
    say "интервал" "${lo:-?}-${hi:-?} сек"
    if [ -n "${lo:-}" ] && [ "$n" -gt 0 ]; then
        say "круг по всем поискам" "$(awk -v n="$n" -v l="$lo" -v h="${hi:-$lo}" \
            'BEGIN {printf "%.1f - %.1f ч", n*l/3600, n*h/3600}')"
    fi
    echo
    echo "  Что ищем:"
    grep '^\s*- label:' "$CFG" | sed 's/.*- label: /    /' | head -30
else
    say "config.yaml" "НЕ НАЙДЕН в $BOT_DIR"
fi

section "База виденных"
DB="$BOT_DIR/seen.sqlite3"
if [ -f "$DB" ] && command -v sqlite3 >/dev/null; then
    say "размер" "$(du -h "$DB" | cut -f1)"
    sqlite3 "$DB" "SELECT '  '||label||': '||COUNT(*)||' объявлений, из них отправлено '||
                          SUM(notified) FROM seen GROUP BY label ORDER BY COUNT(*) DESC LIMIT 15;" \
        2>/dev/null || echo "  (таблица seen не читается)"
elif [ -f "$DB" ]; then
    say "размер" "$(du -h "$DB" | cut -f1) (sqlite3 не установлен, подробностей нет)"
else
    say "seen.sqlite3" "нет — бот ещё ни разу не отработал"
fi

echo
