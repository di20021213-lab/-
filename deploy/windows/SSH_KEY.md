# SSH-ключ: чтобы туннель не спрашивал пароль

Пока ключа нет, `tunnel.bat` при каждом запуске просит пароль от `root`. Один
раз ввести не проблема — но связь иногда рвётся, скрипт переподключается сам, и
в этот момент тебя у экрана не будет. Туннель встанет и будет ждать пароль,
который некому ввести. С ключом он поднимается молча и живёт без тебя.

Ключ у тебя уже есть — он лежит в архиве, который мы сняли с Linux перед
установкой Windows.

## Забрать и разложить

PowerShell, из папки с ботом:

```powershell
cd C:\avito-watcher
```

```powershell
scp root@87.58.205.159:~/avito-backup.tgz .
```

Пароль спросит — это последний раз.

```powershell
tar -xzf avito-backup.tgz
```

```powershell
mkdir $env:USERPROFILE\.ssh -Force
```

```powershell
move .ssh\id_ed25519 $env:USERPROFILE\.ssh\
move .ssh\id_ed25519.pub $env:USERPROFILE\.ssh\
```

## Права на ключ — обязательный шаг

```powershell
icacls $env:USERPROFILE\.ssh\id_ed25519 /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

Windows-версия SSH отказывается работать с ключом, который доступен кому-то
ещё, — и говорит об этом так, что не сразу поймёшь: `UNPROTECTED PRIVATE KEY
FILE` или `bad permissions`. Команда выше снимает наследование прав от папки и
оставляет доступ только тебе, на чтение.

## Проверить

```powershell
ssh root@87.58.205.159 hostname
```

Должно ответить `VM-227782` и **не спросить пароль**. Если пароль всё-таки
просит — смотри таблицу ниже.

## Заодно разложить остальное из архива

В том же архиве лежат база виденных объявлений и настройки:

```powershell
move avito-watcher\seen.sqlite3 .
move avito-watcher\.env .
move avito-watcher\config.yaml .
rmdir avito-watcher, .ssh
```

`seen.sqlite3` важнее всего: без неё бот сочтёт запуск первым, молча запомнит
всю выдачу и не пришлёт ничего целый цикл.

## Запустить туннель заново

```powershell
.\deploy\windows\tunnel.bat
```

Теперь должно быть одно сообщение `connecting to ...` и тишина — без всякого
пароля.

## Если не работает

| Что видишь | Что делать |
|---|---|
| `UNPROTECTED PRIVATE KEY FILE`, `bad permissions` | Не выполнена команда `icacls` выше |
| Снова просит пароль | Ключ не там. Проверь: `dir $env:USERPROFILE\.ssh` — должен лежать `id_ed25519` без расширения |
| `Permission denied (publickey)` | Ключа нет в списке разрешённых на сервере. Проверь: `ssh root@87.58.205.159 "ssh-keygen -lf /root/.ssh/authorized_keys"` — там должен быть `danila@avito` |
| `tar` не найдена | Очень старая сборка Windows. Распакуй архив 7-Zip или WinRAR |
| `scp` не найдена | Нет клиента OpenSSH: `Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0` |
