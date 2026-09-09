#!/usr/bin/env bash
#
# Кладёт WAN роутера Keenetic на несколько минут, чтобы провайдер выдал новый IP.
#
# Зачем не «перезагрузка»: короткий реконнект часто возвращает тот же адрес,
# а вот сессия, закрытая на несколько минут, меняет его заметно чаще. Обесточить
# роутер удалённо нельзя — включать будет некому, — но положить WAN можно:
# роутер остаётся под питанием, локальная сеть работает, и мини-ПК всё это время
# видит его по LAN.
#
# СТРАХОВКА. Финалом идёт system reboot, а НЕ «поднять интерфейс». Keenetic не
# сохраняет изменения конфигурации, пока не сказать configuration save, поэтому
# перезагрузка возвращает WAN в исходное состояние сама. Даже если что-то пойдёт
# не так между командами, интернет вернётся после перезагрузки.
#
# Использование:
#   ./wan-bounce.sh                       — показать интерфейсы и выйти
#   ./wan-bounce.sh PPPoE0                — положить WAN на 5 минут (по умолчанию)
#   ./wan-bounce.sh PPPoE0 600            — на 10 минут
#
# Пароль от роутера — в переменной окружения:
#   KEENETIC_PASSWORD='пароль' ./wan-bounce.sh PPPoE0
#
# Запускать ОТВЯЗАННО от SSH-сессии: интернет пропадёт, и сессия оборвётся
# раньше, чем скрипт дойдёт до перезагрузки.
#   KEENETIC_PASSWORD='пароль' setsid nohup ./wan-bounce.sh PPPoE0 300 &
#
set -uo pipefail

ROUTER="${ROUTER:-192.168.1.1}"
LOGIN="${KEENETIC_LOGIN:-admin}"
DOWN_SECONDS="${2:-300}"
IFACE="${1:-}"
LOG="${LOG:-$HOME/wan-bounce.log}"

say() { printf '%s  %s\n' "$(date '+%d.%m %H:%M:%S')" "$*" | tee -a "$LOG"; }

if [ -z "${KEENETIC_PASSWORD:-}" ]; then
    if [ -t 0 ]; then
        read -rsp "Пароль от роутера ($LOGIN@$ROUTER): " KEENETIC_PASSWORD
        echo
    else
        echo "Нужен пароль: KEENETIC_PASSWORD='...' $0 ..." >&2
        exit 2
    fi
fi

# Отправляет команды в CLI роутера. Паузы нужны: telnet-сессия Keenetic ждёт
# приглашения, а сыпать всё разом она не даёт.
kcmd() {
    {
        printf '%s\n' "$LOGIN";            sleep 2
        printf '%s\n' "$KEENETIC_PASSWORD"; sleep 2
        for c in "$@"; do printf '%s\n' "$c"; sleep 1; done
        printf 'exit\n';                   sleep 1
    } | telnet "$ROUTER" 2>&1
}

if [ -z "$IFACE" ]; then
    echo "Интерфейсы роутера $ROUTER (ищи свой WAN — обычно PPPoE0 или ISP):"
    echo
    kcmd "show interface" | grep -iE 'ppp|isp|gigabit|ethernet|description|connected' | head -40
    echo
    echo "Нашёл имя — запускай:  KEENETIC_PASSWORD='...' setsid nohup $0 ИМЯ 300 &"
    exit 0
fi

say "=== старт: кладу $IFACE на $DOWN_SECONDS сек ==="
say "IP до: $(curl -s --max-time 15 https://api.ipify.org || echo '?')"

kcmd "interface $IFACE down" >>"$LOG" 2>&1
say "команда down отправлена, жду $DOWN_SECONDS сек"
sleep "$DOWN_SECONDS"

# Возвращаем связь перезагрузкой: она поднимает WAN из сохранённого конфига,
# где интерфейс включён. Пробуем несколько раз — остаться без интернета
# из-за одной неудачной telnet-сессии никак нельзя.
for attempt in 1 2 3 4 5; do
    say "перезагружаю роутер (попытка $attempt)"
    kcmd "system reboot" >>"$LOG" 2>&1
    sleep 60
    if curl -s --max-time 15 https://api.ipify.org >/dev/null; then
        break
    fi
    say "интернета ещё нет, жду"
    sleep 60
done

# Роутер поднимается около минуты-двух — даём ему время и проверяем.
for _ in $(seq 1 20); do
    ip=$(curl -s --max-time 10 https://api.ipify.org)
    if [ -n "$ip" ]; then
        say "IP после: $ip"
        say "=== готово ==="
        exit 0
    fi
    sleep 15
done

say "!!! интернет не вернулся за 5 минут — передёрни роутер питанием"
exit 1
