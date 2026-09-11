#!/usr/bin/env bash
# Отключает вход по паролю на сервере, оставляя вход по ключу.
#
# По умолчанию НИЧЕГО НЕ МЕНЯЕТ — только показывает, что происходит сейчас.
# Применить:  bash harden_ssh.sh --apply
#
# Почему это важно: пароль к root на белом адресе подбирают круглосуточно
# (в журнале десятки тысяч попыток). Ключ подобрать нельзя.
#
# Почему drop-in называется 01-, а не 99-: sshd берёт ПЕРВОЕ найденное значение,
# а файлы из sshd_config.d читаются по порядку имён в начале конфига. Файл 99-
# проиграл бы уже существующему 50-cloud-init.conf с PasswordAuthentication yes —
# именно поэтому у тебя пароль включён, хотя в 60-cloudimg-settings.conf стоит no.

set -u
# Пути через переменные — чтобы скрипт можно было прогнать на подставном sshd,
# а не проверять его впервые на живом сервере.
DROPIN=${DROPIN:-/etc/ssh/sshd_config.d/01-hardening.conf}
ROOT_KEYS=${ROOT_KEYS:-/root/.ssh/authorized_keys}
APPLY=${1:-}

section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

effective() {
    # sshd -T печатает ИТОГОВЫЕ значения с учётом всех файлов и порядка их чтения.
    # Это единственный честный ответ на вопрос «что реально включено».
    # Смотрим на текст, а не на код возврата: последним в конвейере стоит sed,
    # и он возвращает 0 даже когда не пришло ни строки.
    local out
    out=$(sshd -T 2>/dev/null | grep -iE '^(passwordauthentication|permitrootlogin|pubkeyauthentication|kbdinteractiveauthentication)')
    if [ -n "$out" ]; then
        printf '%s\n' "$out" | sed 's/^/  /'
    else
        echo "  sshd -T недоступен (нужен root и установленный sshd)"
    fi
}

section "Как настроено сейчас"
effective

section "Ключи, которыми можно войти под root"
if [ -r "$ROOT_KEYS" ]; then
    ssh-keygen -lf "$ROOT_KEYS" 2>/dev/null | sed 's/^/  /'
    echo "  Отключать пароль можно, только если среди них есть ТВОЙ рабочий ключ."
else
    echo "  ФАЙЛА НЕТ — войти по ключу нельзя!"
    echo "  Отключишь пароль сейчас — потеряешь доступ. Сначала заведи ключ."
    exit 1
fi

if [ "$APPLY" != "--apply" ]; then
    section "Что будет сделано при --apply"
    cat <<TXT
  Создать $DROPIN:
      PasswordAuthentication no
      KbdInteractiveAuthentication no
      PermitRootLogin prohibit-password
      PubkeyAuthentication yes
  Проверить конфиг (sshd -t) и перезагрузить sshd.

  PermitRootLogin prohibit-password, а не no: под root ходит мини-ПК по ключу,
  и полный запрет оборвал бы туннель.

  Запусти с --apply, когда будешь готов. ТЕКУЩУЮ СЕССИЮ НЕ ЗАКРЫВАЙ.
TXT
    exit 0
fi

section "Применяю"
[ -f "$DROPIN" ] && cp -a "$DROPIN" "$DROPIN.bak-$(date +%Y%m%d-%H%M%S)"
cat > "$DROPIN" <<'CONF'
# Вход только по ключу. Пароль к root на белом адресе перебирают роботы.
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
# prohibit-password: root пускаем, но только по ключу — им ходит мини-ПК.
PermitRootLogin prohibit-password
CONF
echo "  записан $DROPIN"

if ! sshd -t; then
    echo "  КОНФИГ БИТЫЙ — откатываю, ничего не перезагружаю"
    rm -f "$DROPIN"
    exit 1
fi
echo "  sshd -t: конфиг корректен"

# reload, а не restart: существующие сессии не рвутся, и если что-то пойдёт
# не так, ты останешься внутри и сможешь откатить.
systemctl reload ssh 2>/dev/null || systemctl reload sshd
echo "  sshd перечитал настройки"

section "Стало"
effective

cat <<'TXT'

ПРОВЕРЬ ПРЯМО СЕЙЧАС, НЕ ЗАКРЫВАЯ ЭТУ СЕССИЮ:
  открой ВТОРОЕ окно и зайди на сервер заново.

  Зашло  — всё в порядке, дверь закрыта.
  Не зашло — в этой, ещё живой сессии выполни:
      rm /etc/ssh/sshd_config.d/01-hardening.conf && systemctl reload ssh
TXT
