#!/usr/bin/env bash
# Что за железо и потянет ли оно Windows 11 — виртуалкой или начисто.
#
# Запуск:  bash deploy/sysinfo.sh
# Через sudo покажет заодно модель материнской платы: sudo bash deploy/sysinfo.sh

say() { printf '%-22s %s\n' "$1" "$2"; }
section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

verdict_vm="да"; why_vm=""
verdict_bare="да"; why_bare=""
no() { # no <vm|bare> <причина>
    if [ "$1" = vm ]; then verdict_vm="НЕТ"; why_vm="$why_vm  · $2"$'\n'
    else verdict_bare="НЕТ"; why_bare="$why_bare  · $2"$'\n'; fi
}
maybe() {
    # Не повышаем вердикт: если что-то уже запретило установку начисто,
    # добавочная неясность её не разрешает.
    [ "$verdict_bare" = "да" ] && verdict_bare="под вопросом"
    why_bare="$why_bare  · $1"$'\n'
}

section "Железо"
say "модель" "$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo '?')"
cpu=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')
say "процессор" "${cpu:-?}"
cores=$(nproc)
say "ядер" "$cores"
[ "$cores" -lt 2 ] && { no vm "ядер меньше двух"; no bare "ядер меньше двух"; }

ram_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo)
ram_gb=$(( ram_kb / 1024 / 1024 ))
say "память" "${ram_gb} ГБ"
# Win11 требует 4 ГБ. Виртуалке нужно столько же ПЛЮС то, на чём живёт хост.
[ "$ram_gb" -lt 4 ] && no bare "меньше 4 ГБ — Windows 11 не поставится"
[ "$ram_gb" -lt 8 ] && no vm "меньше 8 ГБ: 4 нужны виртуалке, остальное хосту и боту"

if grep -qE '(vmx|svm)' /proc/cpuinfo; then
    say "виртуализация" "поддерживается"
else
    say "виртуализация" "НЕТ (или выключена в UEFI)"
    no vm "процессор не отдаёт vmx/svm — Windows в виртуалке будет непригодно медленной"
fi

section "Диск"
lsblk -d -o NAME,SIZE,MODEL 2>/dev/null | sed 's/^/  /'
free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
say "свободно на /" "${free_gb} ГБ"
[ "${free_gb:-0}" -lt 40 ] && no vm "мало места: виртуалке нужно 64 ГБ под диск, хотя бы 40 реально занятых"

section "Прошивка и защита"
if [ -d /sys/firmware/efi ]; then
    say "загрузка" "UEFI"
else
    say "загрузка" "Legacy BIOS"
    no bare "Windows 11 ставится только в UEFI"
fi

tpm_ver=$(cat /sys/class/tpm/tpm0/tpm_version_major 2>/dev/null)
if [ "$tpm_ver" = 2 ]; then
    say "TPM" "2.0 — есть"
elif [ -n "$tpm_ver" ]; then
    say "TPM" "версия $tpm_ver — Windows 11 нужен 2.0"
    no bare "TPM версии $tpm_ver вместо 2.0"
else
    say "TPM" "не виден"
    maybe "TPM не виден системе. Чаще всего он есть, но выключен в UEFI (fTPM у AMD, PTT у Intel) — включается ТОЛЬКО с клавиатурой у машины"
fi

sb=$(mokutil --sb-state 2>/dev/null | head -1)
if [ -n "$sb" ]; then
    say "Secure Boot" "$sb"
else
    ev=$(find /sys/firmware/efi/efivars -maxdepth 1 -name 'SecureBoot-*' 2>/dev/null | head -1)
    if [ -n "$ev" ]; then
        state=$(od -An -t u1 "$ev" 2>/dev/null | awk '{print $5}')
        say "Secure Boot" "$([ "$state" = 1 ] && echo включён || echo выключен)"
        [ "$state" != 1 ] && maybe "Secure Boot выключен — включается только в UEFI, с клавиатурой у машины"
    else
        say "Secure Boot" "определить не удалось"
    fi
fi

section "Сеть — от неё зависит, вернётся ли машина на связь"
lspci 2>/dev/null | grep -iE 'ethernet|network' | sed 's/^/  /' || echo "  lspci недоступен"
for i in $(ls /sys/class/net | grep -v lo); do
    drv=$(basename "$(readlink -f /sys/class/net/$i/device/driver 2>/dev/null)" 2>/dev/null)
    st=$(cat /sys/class/net/$i/operstate 2>/dev/null)
    printf '  %-10s драйвер %-12s %s\n' "$i" "${drv:-?}" "$st"
done

section "Вывод"
echo "Windows 11 в виртуалке (Linux остаётся): $verdict_vm"
[ -n "$why_vm" ] && printf '%s' "$why_vm"
echo "Windows 11 вместо Linux:                 $verdict_bare"
[ -n "$why_bare" ] && printf '%s' "$why_bare"

cat <<'TXT'

Про удалённую переустановку. Даже когда всё сходится, есть отказ, который
удалённо не лечится: если Windows не подхватит сетевую карту своим драйвером,
машина после установки не выйдет в сеть и достать её будет нечем. Модель карты
видно выше — покажи её мне, прикину.
TXT
