#!/usr/bin/env bash
# Что за процесс держит SOCKS-прокси на 1080 и откуда он взялся.
#
# Запускать ИМЕННО НА СЕРВЕРЕ. Проще всего — с мини-ПК одной строкой:
#   ssh root@87.58.205.159 'bash -s' < deploy/audit_socks.sh

section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

section "Это точно сервер?"
echo "  hostname: $(hostname)"
echo "  адреса:   $(hostname -I 2>/dev/null)"
echo "  Если тут не адрес сервера — ты снова на мини-ПК, и смотреть надо не здесь."

section "Кто слушает 1080"
# Проверяем сам текст, а не код возврата: sed возвращает 0 и на пустом вводе,
# из-за чего ветка «никто» не срабатывала никогда.
listen=$(ss -tlnp 2>/dev/null | grep ':1080')
if [ -n "$listen" ]; then
    printf '%s\n' "$listen" | sed 's/^/  /'
else
    echo "  никто не слушает — процесс уже завершился или его тут не было"
fi

pid=$(ss -tlnpH 2>/dev/null | grep ':1080' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
if [ -z "$pid" ]; then
    echo "  (нечего разбирать)"
else
    section "Что это за процесс"
    # args, а не cmd: нужна полная командная строка со всеми ключами —
    # именно она отличает нашу конструкцию от чужой.
    ps -o pid,ppid,user,lstart,etime,args -p "$pid" | sed 's/^/  /'

    section "Кто его запустил"
    ppid=$(ps -o ppid= -p "$pid" | tr -d ' ')
    [ -n "$ppid" ] && ps -o pid,ppid,user,lstart,args -p "$ppid" | sed 's/^/  /'
    echo "  Родитель 1 (systemd) — значит запущен как служба или отвязан от сессии."
    echo "  Родитель — sshd или bash — значит запущен руками из чьей-то сессии."

    section "Откуда запущен"
    ls -l "/proc/$pid/cwd" "/proc/$pid/exe" 2>/dev/null | sed 's/^/  /'
    tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null \
      | grep -iE 'ssh_|user|home|sudo' | head -10 | sed 's/^/  /'
    echo "  SSH_CLIENT/SSH_CONNECTION в окружении покажут, с какого адреса пришёл тот,"
    echo "  кто его запустил."
fi

section "Не прописан ли на автозапуск"
crontab -l 2>/dev/null | grep -v '^#' | sed 's/^/  root: /'
for u in ubuntu avito; do
    crontab -l -u "$u" 2>/dev/null | grep -v '^#' | sed "s|^|  $u: |"
done
ls -la /etc/cron.d/ 2>/dev/null | sed 's/^/  /'
grep -rn 'ssh -D\|ssh -R\|ssh -L\|:1080' \
    /etc/rc.local /root/.bashrc /root/.profile /root/.bash_profile \
    /home/*/.bashrc /etc/systemd/system/*.service /etc/systemd/system/*/*.service \
    2>/dev/null | sed 's/^/  /'
echo "  (пусто выше — значит нигде не закреплён и после перезагрузки не вернётся)"

section "Все входы за последнее время"
last -aiw 2>/dev/null | head -25 | sed 's/^/  /'
