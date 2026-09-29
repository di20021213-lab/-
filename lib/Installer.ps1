# Запуск установщиков в тихом режиме и очередь установки.

function Get-ExitCodeInfo {
    # Возвращает @{ Status = OK|Reboot|Error; Text = '...' }
    param([int]$Code, $SuccessCodes = @())
    if (@($SuccessCodes) -contains $Code) { return @{ Status = 'OK'; Text = "Успешно (код $Code)" } }
    switch ($Code) {
        0 { return @{ Status = 'OK'; Text = 'Успешно' } }
        3010 { return @{ Status = 'Reboot'; Text = 'Успешно, требуется перезагрузка' } }
        1641 { return @{ Status = 'Reboot'; Text = 'Успешно, инициирована перезагрузка' } }
        1638 { return @{ Status = 'OK'; Text = 'Уже установлена эта или более новая версия' } }
        (-2147023258) { return @{ Status = 'OK'; Text = 'Уже установлена эта или более новая версия' } } # 0x80070666
        1602 { return @{ Status = 'Error'; Text = 'Установка отменена' } }
        1223 { return @{ Status = 'Error'; Text = 'Установка отменена' } }
        1603 { return @{ Status = 'Error'; Text = 'Критическая ошибка установки (1603), см. лог MSI' } }
        1618 { return @{ Status = 'Error'; Text = 'Уже выполняется другая установка (1618)' } }
        1619 { return @{ Status = 'Error'; Text = 'Не удалось открыть пакет установки (1619)' } }
        1620 { return @{ Status = 'Error'; Text = 'Пакет установки повреждён (1620)' } }
        1625 { return @{ Status = 'Error'; Text = 'Установка запрещена политикой (1625)' } }
        1633 { return @{ Status = 'Error'; Text = 'Пакет не подходит для этой платформы (1633)' } }
        1639 { return @{ Status = 'Error'; Text = 'Неверные ключи командной строки (1639)' } }
        740 { return @{ Status = 'Error'; Text = 'Требуются права администратора (740)' } }
    }
    return @{ Status = 'Error'; Text = "Ошибка, код выхода $Code" }
}

function Get-InstallCommand {
    # Формирует команду запуска: @{ FilePath = '...'; Arguments = '...' }
    param([Parameter(Mandatory = $true)]$Item, [string]$LogDir)
    $file = [string]$Item.File
    $dir = [System.IO.Path]::GetDirectoryName($file)
    $ext = [System.IO.Path]::GetExtension($file).ToLowerInvariant()
    $userArgs = ([string]$Item.Args).Trim()
    switch ($ext) {
        '.msi' {
            $a = ('/i "{0}" {1}' -f $file, $userArgs).Trim()
            if ($LogDir) {
                $log = [System.IO.Path]::Combine($LogDir, ('msi_{0}_{1}.log' -f (Get-SafeName $Item.Name), (Get-Date -Format 'yyyyMMdd_HHmmss')))
                $a += ' /l*v "{0}"' -f $log
            }
            return @{ FilePath = 'msiexec.exe'; Arguments = $a }
        }
        '.msu' {
            return @{ FilePath = 'wusa.exe'; Arguments = ('"{0}" {1}' -f $file, $userArgs).Trim() }
        }
        { $_ -in @('.msix', '.msixbundle', '.appx', '.appxbundle') } {
            $p = $file.Replace("'", "''")
            $cmdText = "try { Add-AppxProvisionedPackage -Online -PackagePath '$p' -SkipLicense -ErrorAction Stop | Out-Null; exit 0 } catch { Write-Error `$_; exit 1 }"
            return @{ FilePath = 'powershell.exe'; Arguments = '-NoProfile -ExecutionPolicy Bypass -Command "' + $cmdText + '"' }
        }
        { $_ -in @('.bat', '.cmd') } {
            # pushd позволяет запускать скрипты и из сетевых папок (UNC).
            return @{ FilePath = 'cmd.exe'; Arguments = ('/c "pushd "{0}" && call "{1}" {2}"' -f $dir, $file, $userArgs) }
        }
        '.ps1' {
            return @{ FilePath = 'powershell.exe'; Arguments = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" {1}' -f $file, $userArgs).Trim() }
        }
    }
    return @{ FilePath = $file; Arguments = $userArgs }
}

function New-InstallResult {
    param([string]$Status, [string]$Message, $ExitCode = $null, [double]$Seconds = 0)
    [pscustomobject]@{ Status = $Status; Message = $Message; ExitCode = $ExitCode; Seconds = [Math]::Round($Seconds) }
}

function Wait-Seconds {
    param([int]$Seconds, [scriptblock]$OnWait)
    $until = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $until) {
        if ($OnWait) { & $OnWait }
        Start-Sleep -Milliseconds 200
    }
}

function Invoke-Installer {
    param(
        [Parameter(Mandatory = $true)]$Item,
        [string]$LogDir,
        [int]$TimeoutMinutes = 60,
        [scriptblock]$OnWait
    )
    $file = [string]$Item.File
    if (-not (Test-Path -LiteralPath $file)) { return (New-InstallResult 'Error' "Файл не найден: $file") }
    # Снимаем пометку «загружено из интернета», иначе Windows может показать окно подтверждения.
    try { Unblock-File -LiteralPath $file -ErrorAction SilentlyContinue } catch { }

    $timeout = [int](Get-OrDefault $Item.TimeoutMinutes $TimeoutMinutes)
    $started = Get-Date
    $attempt = 0
    while ($true) {
        $attempt++
        $cmd = Get-InstallCommand -Item $Item -LogDir $LogDir
        Write-Log ('    Команда: "{0}" {1}' -f $cmd.FilePath, $cmd.Arguments)

        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $cmd.FilePath
        $psi.Arguments = $cmd.Arguments
        $psi.WorkingDirectory = [System.IO.Path]::GetDirectoryName($file)
        # Без ShellExecute: не появляется окно «Предупреждение системы безопасности»
        # для файлов из сети, а код выхода всегда доступен.
        $psi.UseShellExecute = $false
        try {
            $proc = [System.Diagnostics.Process]::Start($psi)
        }
        catch {
            return (New-InstallResult 'Error' ("Не удалось запустить: " + $_.Exception.Message) $null ((Get-Date) - $started).TotalSeconds)
        }

        $deadline = $started.AddMinutes($timeout)
        $timedOut = $false
        while (-not $proc.WaitForExit(250)) {
            if ($OnWait) { & $OnWait }
            if ((Get-Date) -gt $deadline) { $timedOut = $true; break }
        }
        if ($timedOut) {
            Write-Log "    Превышено время ожидания ($timeout мин), процесс установки будет остановлен" 'Warn'
            try { & taskkill.exe /PID $proc.Id /T /F 2>&1 | Out-Null } catch { }
            try { if (-not $proc.HasExited) { $proc.Kill() } } catch { }
            return (New-InstallResult 'Timeout' "Превышено время ожидания ($timeout мин)" $null ((Get-Date) - $started).TotalSeconds)
        }
        $proc.WaitForExit()
        $code = $proc.ExitCode
        $proc.Dispose()

        if ($code -eq 1618 -and $attempt -le 10) {
            Write-Log '    Windows Installer занят другой установкой, повтор через 30 секунд…' 'Warn'
            Wait-Seconds 30 $OnWait
            continue
        }
        $info = Get-ExitCodeInfo -Code $code -SuccessCodes $Item.SuccessCodes
        return (New-InstallResult $info.Status $info.Text $code ((Get-Date) - $started).TotalSeconds)
    }
}

function Invoke-InstallQueue {
    # Устанавливает программы по очереди. Возвращает массив результатов.
    param(
        [Parameter(Mandatory = $true)]$Items,
        [string]$LogDir,
        [switch]$SkipInstalled,
        [switch]$DryRun,
        [int]$TimeoutMinutes = 60,
        [scriptblock]$OnItemStart,   # param($item, $index, $total)
        [scriptblock]$OnItemDone,    # param($item, $result)
        [scriptblock]$OnWait,
        [scriptblock]$ShouldStop
    )
    $list = @($Items)
    $total = $list.Count
    $results = New-Object System.Collections.ArrayList
    $n = 0
    foreach ($item in $list) {
        $n++
        if ($ShouldStop -and (& $ShouldStop)) {
            Write-Log 'Установка остановлена пользователем.' 'Warn'
            break
        }
        if ($OnItemStart) { & $OnItemStart $item $n $total }
        Write-Log ('[{0}/{1}] {2}' -f $n, $total, $item.Name)

        if (-not $item.File) {
            $r = New-InstallResult 'Skipped' 'Нет дистрибутива в папке Distrib'
        }
        elseif ($SkipInstalled -and $item.Installed) {
            $r = New-InstallResult 'Skipped' ('Уже установлено (версия {0})' -f $item.Installed)
        }
        elseif ($item.NeedsArgs -and ([string]$item.Args).Trim() -eq '') {
            $r = New-InstallResult 'Skipped' 'Тип установщика не определён — укажите ключи тихой установки вручную'
        }
        elseif ($DryRun) {
            $cmd = Get-InstallCommand -Item $item -LogDir $LogDir
            Write-Log ('    (тестовый запуск) "{0}" {1}' -f $cmd.FilePath, $cmd.Arguments)
            $r = New-InstallResult 'Skipped' 'Тестовый запуск — установка не выполнялась'
        }
        else {
            $r = Invoke-Installer -Item $item -LogDir $LogDir -TimeoutMinutes $TimeoutMinutes -OnWait $OnWait
        }

        $level = switch ($r.Status) { 'OK' { 'OK' } 'Reboot' { 'OK' } 'Skipped' { 'Warn' } default { 'Error' } }
        $suffix = if ($r.Seconds -gt 0) { " [$($r.Seconds) с]" } else { '' }
        Write-Log ('    {0}{1}' -f $r.Message, $suffix) $level
        $r | Add-Member -NotePropertyName Name -NotePropertyValue $item.Name
        if ($OnItemDone) { & $OnItemDone $item $r }
        [void]$results.Add($r)
    }

    $ok = @($results | Where-Object { $_.Status -in @('OK', 'Reboot') }).Count
    $skipped = @($results | Where-Object { $_.Status -eq 'Skipped' }).Count
    $failed = @($results | Where-Object { $_.Status -in @('Error', 'Timeout') }).Count
    $level = if ($failed -gt 0) { 'Error' } else { 'OK' }
    Write-Log ('Итог: установлено {0}, пропущено {1}, ошибок {2}.' -f $ok, $skipped, $failed) $level
    if (@($results | Where-Object { $_.Status -eq 'Reboot' }).Count -gt 0) {
        Write-Log 'Для завершения установки требуется перезагрузка компьютера.' 'Warn'
    }
    return , $results.ToArray()
}

# ---------- Обмен данными между окном программы и процессом установки ----------

function Write-StatusEvent {
    # Процесс установки (с правами администратора) пишет события в файл по одной JSON-строке.
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][hashtable]$Data)
    $json = ConvertTo-Json -InputObject $Data -Compress -Depth 4
    $enc = New-Object System.Text.UTF8Encoding $false
    for ($i = 0; $i -lt 20; $i++) {
        try { [System.IO.File]::AppendAllText($Path, $json + "`n", $enc); return }
        catch { Start-Sleep -Milliseconds 50 }
    }
}
