<#
.SYNOPSIS
    Silent Installer — пакетная тихая установка программ из папки с дистрибутивами.

.DESCRIPTION
    Без параметров открывает окно программы: выберите программы из списка,
    перетащите в окно их установщики и нажмите «Установить выбранное».

    С параметрами -Programs / -Preset / -All работает без окна (из командной строки).

.EXAMPLE
    .\SilentInstaller.ps1
    Открыть окно программы.

.EXAMPLE
    .\SilentInstaller.ps1 -Programs "7-Zip,Google Chrome,Adobe Acrobat Reader"
    Установить перечисленные программы без окна.

.EXAMPLE
    .\SilentInstaller.ps1 -Preset "Базовый набор" -SkipInstalled
    Установить программы из набора, пропуская уже установленные.

.EXAMPLE
    .\SilentInstaller.ps1 -List
    Показать каталог и найденные дистрибутивы.
#>
[CmdletBinding()]
param(
    # Имена программ (можно через запятую).
    [string[]]$Programs,
    # Имя набора из presets.json.
    [string]$Preset,
    # Установить все программы, для которых найдены дистрибутивы.
    [switch]$All,
    # Показать список программ и найденных дистрибутивов.
    [switch]$List,
    # Пропускать программы, которые уже установлены.
    [switch]$SkipInstalled,
    # Показать команды установки, ничего не устанавливая.
    [switch]$DryRun,
    # Папка с дистрибутивами (по умолчанию .\Distrib).
    [string]$Distrib,
    # Максимальное время установки одной программы, минут.
    [int]$TimeoutMinutes = 60,
    # Не запрашивать права администратора.
    [switch]$NoElevate,

    # Служебные параметры.
    [string]$JobFile,
    [switch]$Elevated,
    [switch]$SmokeTest
)

$ErrorActionPreference = 'Continue'
$script:BoundArgs = $PSBoundParameters
$script:Root = $PSScriptRoot
$libDir = Join-Path $script:Root 'lib'
. (Join-Path $libDir 'Common.ps1')
. (Join-Path $libDir 'Catalog.ps1')
. (Join-Path $libDir 'Installer.ps1')

$script:CatalogPath = Join-Path $script:Root 'programs.json'
$script:PresetsPath = Join-Path $script:Root 'presets.json'
$script:DistribDir = if ($Distrib) { $Distrib.TrimEnd('\', '/') } else { Join-Path $script:Root 'Distrib' }
$script:LogDir = Join-Path $script:Root 'Logs'
foreach ($d in @($script:DistribDir, $script:LogDir)) {
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

function Get-RelaunchArguments {
    # Собирает строку параметров для перезапуска скрипта с правами администратора.
    param([switch]$AddElevated)
    $parts = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f (Convert-ToUncPath $PSCommandPath)))
    foreach ($kv in $script:BoundArgs.GetEnumerator()) {
        $v = $kv.Value
        if ($v -is [System.Management.Automation.SwitchParameter]) {
            if ($v.IsPresent) { $parts += "-$($kv.Key)" }
            continue
        }
        if ($v -is [array]) { $v = $v -join ',' }
        if ($kv.Key -eq 'Distrib') { $v = Convert-ToUncPath ([string]$v) }
        $parts += "-$($kv.Key)"
        $parts += ('"{0}"' -f ([string]$v).TrimEnd('\'))
    }
    if ($AddElevated) { $parts += '-Elevated' }
    return ($parts -join ' ')
}

# ---------- Режим 1: процесс установки, запущенный из окна программы ----------

function Invoke-JobMode {
    $job = Read-JsonFile $JobFile
    $statusFile = [string]$job.StatusFile
    $stopFile = [string]$job.StopFile
    $script:LogFile = Join-Path $script:LogDir ('install_{0}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
    $script:LogCallback = {
        param($line, $level)
        Write-StatusEvent -Path $statusFile -Data @{ Event = 'log'; Text = $line; Level = $level }
    }
    try {
        Write-Log ('Запуск установки. Программ: {0}. Лог: {1}' -f @($job.Items).Count, $script:LogFile)
        $results = Invoke-InstallQueue -Items @($job.Items) -LogDir $script:LogDir `
            -SkipInstalled:([bool]$job.SkipInstalled) -TimeoutMinutes ([int]$job.TimeoutMinutes) `
            -OnItemStart { param($it, $n, $total) Write-StatusEvent -Path $statusFile -Data @{ Event = 'start'; Name = $it.Name; Index = $n; Total = $total } } `
            -OnItemDone { param($it, $r) Write-StatusEvent -Path $statusFile -Data @{ Event = 'done'; Name = $it.Name; Status = $r.Status; Message = $r.Message; ExitCode = $r.ExitCode } } `
            -ShouldStop { Test-Path -LiteralPath $stopFile }
        $reboot = @($results | Where-Object { $_.Status -eq 'Reboot' }).Count -gt 0
        Write-StatusEvent -Path $statusFile -Data @{ Event = 'finished'; Reboot = $reboot; LogFile = $script:LogFile }
    }
    catch {
        Write-Log ('Непредвиденная ошибка: ' + $_.Exception.Message) 'Error'
        Write-StatusEvent -Path $statusFile -Data @{ Event = 'finished'; Error = $_.Exception.Message; LogFile = $script:LogFile }
        exit 1
    }
    exit 0
}

# ---------- Режим 2: командная строка ----------

function Invoke-CliMode {
    $catalog = Get-Catalog $script:CatalogPath
    $installed = Get-InstalledPrograms
    $items = Resolve-Items -Catalog $catalog -DistribDir $script:DistribDir -Installed $installed

    if ($List) {
        Write-Host ('Папка дистрибутивов: {0}' -f $script:DistribDir)
        $items | Sort-Object Order | Format-Table -AutoSize -Wrap `
            @{ Label = 'Программа'; Expression = { $_.Name } },
            @{ Label = 'Дистрибутив'; Expression = { if ($_.RelPath) { $_.RelPath } else { '—' } } },
            @{ Label = 'Тип'; Expression = { $_.Type } },
            @{ Label = 'Ключи'; Expression = { $_.Args } },
            @{ Label = 'Установлено'; Expression = { $_.Installed } } | Out-String -Width 220 | Write-Host
        return 0
    }

    $names = @()
    if ($Preset) {
        $presets = Get-Presets $script:PresetsPath
        if (-not $presets.Contains($Preset)) {
            Write-Log ('Набор «{0}» не найден в presets.json. Доступные: {1}' -f $Preset, (@($presets.Keys) -join ', ')) 'Error'
            return 2
        }
        $names += $presets[$Preset]
    }
    foreach ($p in @($Programs)) {
        $names += @(([string]$p) -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }

    if ($All) {
        $selected = @($items | Where-Object { $_.File })
    }
    else {
        $selected = @()
        foreach ($name in $names) {
            $it = $items | Where-Object { $_.Name -eq $name } | Select-Object -First 1
            if ($it) { $selected += $it } else { Write-Log ('Программа «{0}» не найдена в каталоге и в папке Distrib' -f $name) 'Warn' }
        }
    }
    $selected = @($selected | Sort-Object Order -Unique)
    if ($selected.Count -eq 0) {
        Write-Log 'Нечего устанавливать.' 'Warn'
        return 2
    }

    if (-not $DryRun) {
        $script:LogFile = Join-Path $script:LogDir ('install_{0}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
        Write-Log ('Лог установки: {0}' -f $script:LogFile)
    }
    $results = Invoke-InstallQueue -Items $selected -LogDir $script:LogDir -SkipInstalled:$SkipInstalled -DryRun:$DryRun -TimeoutMinutes $TimeoutMinutes
    if (@($results | Where-Object { $_.Status -in @('Error', 'Timeout') }).Count -gt 0) { return 1 }
    return 0
}

# ---------- Запуск ----------

if ($JobFile) {
    Invoke-JobMode
}

$cliMode = $List -or $All -or $Preset -or (@($Programs | Where-Object { $_ }).Count -gt 0) -or $DryRun
if ($cliMode) {
    if (-not ($List -or $DryRun -or $NoElevate) -and -not (Test-IsAdmin)) {
        Write-Host 'Для установки нужны права администратора — запрашиваю повышение прав…'
        try {
            Start-Process -FilePath (Get-PowerShellExe) -Verb RunAs -ArgumentList (Get-RelaunchArguments -AddElevated) -WorkingDirectory $env:SystemRoot | Out-Null
            exit 0
        }
        catch {
            Write-Host 'Не удалось получить права администратора. Установка отменена.' -ForegroundColor Red
            exit 5
        }
    }
    $code = Invoke-CliMode
    if ($Elevated) { Read-Host 'Готово. Нажмите Enter, чтобы закрыть окно' | Out-Null }
    exit $code
}

# Режим 3: окно программы.
try {
    . (Join-Path $libDir 'Gui.ps1')
    Show-MainWindow
}
catch {
    $msg = 'Ошибка: ' + $_.Exception.Message + "`r`n`r`n" + $_.ScriptStackTrace
    if ($SmokeTest) { Write-Host $msg -ForegroundColor Red; exit 1 }
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show($msg, 'Silent Installer', 'OK', 'Error') | Out-Null
    }
    catch { Write-Host $msg -ForegroundColor Red }
}
