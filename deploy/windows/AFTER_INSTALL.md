# Windows встала. Что дальше

По порядку. Команды выполняй в PowerShell (Win+X → «Терминал» или «PowerShell»).

## 1. Не отходя от машины

Это делается один раз, пока ты рядом с клавиатурой.

| Что | Как |
|---|---|
| Сеть работает | Открой любой сайт. Не работает — ставь драйвер с флешки |
| TPM на месте | Win+R → `tpm.msc` → «TPM готов к использованию» |
| Сон выключен | Параметры → Система → Питание → Сон → **Никогда** |
| Удалённый доступ | См. ниже, и **проверь заход с телефона, пока стоишь рядом** |

Удалённый доступ — сервер OpenSSH (на LTSC через «Параметры» часто не ставится,
тогда так):

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service sshd -StartupType Automatic
Start-Service sshd
```

## 2. Программы

- [Python](https://www.python.org/downloads/) — при установке **обязательно**
  галочка «Add python.exe to PATH».
- [Git для Windows](https://git-scm.com/download/win) — все настройки по умолчанию.

Проверка, что встало:

```powershell
python --version
git --version
```

## 3. Забрать код

```powershell
cd C:\
git clone https://github.com/di20021213-lab/- avito-watcher
cd C:\avito-watcher
git checkout claude/avito-gpu-parser-mmp6rr
```

## 4. Вернуть данные из бэкапа

> Подробно, с разбором ошибок — [SSH_KEY.md](SSH_KEY.md). Там же про права
> на ключ, без которых Windows его не примет.

Архив лежит на зарубежном сервере. `scp` и `tar` в Windows уже есть,
ставить нечего:

```powershell
cd C:\avito-watcher
scp root@87.58.205.159:~/avito-backup.tgz .
tar -xzf avito-backup.tgz
```

Разложить по местам:

```powershell
move avito-watcher\seen.sqlite3 .
move avito-watcher\.env .
move avito-watcher\config.yaml .
mkdir $env:USERPROFILE\.ssh -Force
move .ssh\id_ed25519 $env:USERPROFILE\.ssh\
move .ssh\id_ed25519.pub $env:USERPROFILE\.ssh\
rmdir avito-watcher, .ssh
```

**Права на ключ.** Windows-версия SSH откажется брать ключ, который доступен
кому-то ещё, — и это самая частая заминка на этом шаге:

```powershell
icacls $env:USERPROFILE\.ssh\id_ed25519 /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

Проверка, что ключ принят:

```powershell
ssh root@87.58.205.159 hostname
```

Должно ответить `VM-227782` и **не спросить пароль**.

## 5. Запустить бота

```powershell
.\deploy\windows\run.bat
```

Первый запуск ставит зависимости и браузер — минут пять. Дальше окно можно
не закрывать: пока оно открыто, бот работает.

Проверить настройку, ничего не отправляя: `.\deploy\windows\check.bat`

## 6. Туннель для Telegram

Открой `deploy\windows\tunnel.bat`, впиши адрес своего сервера, запусти.
Затем убедись, что канал жив:

```powershell
.venv\Scripts\python test_notify.py
```

Должно прийти сообщение в Telegram.

## 7. Автозапуск

Планировщик задач (Win+R → `taskschd.msc`), **две** задачи: сначала
`tunnel.bat`, потом `run.bat`. Подробности — в `README.md` рядом.

Главное: на вкладке «Общие» отметить **«Выполнять вне зависимости от
регистрации пользователя»**, иначе задача не переживёт выход из системы.

## 8. Проверить гипотезу про Озон

Ради этого всё и затевалось — пустит ли Озон браузер на Windows:

```powershell
.venv\Scripts\python ozon_check.py --file ozon-links.example.txt
```

Если снова капча — её можно разгадать руками, и на Windows это просто, без
всякого VNC:

```powershell
set OZON_HEADLESS=0
.venv\Scripts\python ozon_login.py "https://ozon.ru/t/l1ZC6Ti"
```

Откроется обычное окно браузера — двигай ползунок. Дальше проверки гоняй
тем же видимым браузером: сессия привязана и к отпечатку тоже.
