#!/usr/bin/env bash
# Кто заходил на эту машину и что на ней слушает сеть. Только чтение, ничего
# не меняет. Запускать и на мини-ПК, и на зарубежном сервере — сервер важнее,
# у него белый адрес.
#
#   bash deploy/audit.sh          — что доступно без прав
#   sudo bash deploy/audit.sh     — полностью (журнал неудачных входов нужен root)

section() { printf '\n\033[1m%s\033[0m\n' "$1"; }
note() { printf '  %s\n' "$1"; }

section "Сейчас в системе"
who -u 2>/dev/null | sed 's/^/  /' || note "who недоступен"

section "История входов (последние 20)"
# Здесь смотрим на адрес: свои заходы идут с домашней сети или через туннель
# (127.0.0.1), чужой заход будет с постороннего адреса.
last -aiw 2>/dev/null | head -20 | sed 's/^/  /' || note "журнал входов недоступен"

section "Успешные входы по SSH за 7 дней"
ok=$(journalctl -u ssh -u sshd --since -7d 2>/dev/null | grep -c 'Accepted')
journalctl -u ssh -u sshd --since -7d 2>/dev/null \
  | grep 'Accepted' | awk '{print $1,$2,$3,$9,$11,$13}' | sort | uniq -c \
  | sort -rn | head -15 | sed 's/^/  /'
[ "${ok:-0}" = 0 ] && note "ни одного — либо SSH-сервера тут нет, либо журнал не ведётся"

section "Неудачные попытки входа"
if [ "$(id -u)" = 0 ]; then
    bad=$(lastb 2>/dev/null | wc -l)
    note "всего записей: $bad"
    lastb -aiw 2>/dev/null | head -5 | sed 's/^/  /'
    note ""
    note "Тысячи таких на машине с белым адресом — это фоновый перебор паролей"
    note "роботами, он идёт у всех и сам по себе НЕ означает взлом. Важны только"
    note "успешные входы из раздела выше."
else
    note "нужен sudo"
fi

section "Ключи, которыми можно войти без пароля"
for f in /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys; do
    [ -r "$f" ] || continue
    note "$f (изменён: $(stat -c %y "$f" 2>/dev/null | cut -d. -f1))"
    ssh-keygen -lf "$f" 2>/dev/null | sed 's/^/    /' || sed 's/^/    /' "$f"
done
note "Каждая строка — чей-то доступ. Незнакомый комментарий в конце ключа — повод насторожиться."

section "Учётные записи, под которыми можно войти"
awk -F: '$3>=1000 && $7 !~ /(nologin|false)$/ {print "  "$1"  (uid "$3", "$7")"}' /etc/passwd
note "Появившийся тут незнакомый пользователь — прямой признак чужого вмешательства."

section "Что слушает сеть"
ss -tulnp 2>/dev/null | grep LISTEN | sed 's/^/  /' | head -20
note "0.0.0.0 или * — доступно снаружи; 127.0.0.1 — только с самой машины."

section "Установленные соединения наружу"
ss -tnp state established 2>/dev/null \
  | grep -vE '127\.0\.0\.1|\[::1\]' | head -15 | sed 's/^/  /'

section "Автозапуск"
crontab -l 2>/dev/null | grep -v '^#' | sed 's/^/  crontab: /' || note "crontab пуст"
ls -1 /etc/cron.d 2>/dev/null | sed 's/^/  cron.d: /'
systemctl list-unit-files --state=enabled --type=service 2>/dev/null \
  | awk 'NR>1 && $1 ~ /\.service/ {print "  "$1}' | head -25

section "Настройки SSH-сервера"
if [ -r /etc/ssh/sshd_config ]; then
    grep -HiE '^\s*(PermitRootLogin|PasswordAuthentication|Port|PubkeyAuthentication)' \
        /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null | sed 's/^/  /'
    note ""
    note "PasswordAuthentication yes на машине с белым адресом — самая частая"
    note "дверь: пароль подбирают перебором. Ключи такого не допускают."
else
    note "конфига нет — SSH-сервер, скорее всего, не установлен"
fi
