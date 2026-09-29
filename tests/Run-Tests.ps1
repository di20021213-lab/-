# Тесты Silent Installer.
#   .\tests\Run-Tests.ps1          — модульные тесты (работают и без Windows)
#   .\tests\Run-Tests.ps1 -E2E     — плюс настоящая тихая установка 7-Zip, PuTTY и Notepad++ (только Windows, нужны права администратора)
param([switch]$E2E)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$lib = Join-Path $root 'lib'
. (Join-Path $lib 'Common.ps1')
. (Join-Path $lib 'Catalog.ps1')
. (Join-Path $lib 'Installer.ps1')

$script:failures = 0
function Assert {
    param([bool]$Condition, [string]$Message)
    if ($Condition) { Write-Host "  [OK]   $Message" -ForegroundColor Green }
    else { Write-Host "  [FAIL] $Message" -ForegroundColor Red; $script:failures++ }
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('si-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null

function New-FakeFile {
    param([string]$RelPath, [string]$Content = 'dummy', [switch]$Utf16)
    $path = Join-Path (Join-Path $tmp 'Distrib') ($RelPath.Replace('\', [System.IO.Path]::DirectorySeparatorChar))
    New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
    $enc = if ($Utf16) { [System.Text.Encoding]::Unicode } else { [System.Text.Encoding]::ASCII }
    [System.IO.File]::WriteAllBytes($path, [byte[]](@(0x4D, 0x5A, 0, 0) + $enc.GetBytes($Content)))
    return $path
}

try {
    Write-Host 'Каталог и наборы' -ForegroundColor Cyan
    $catalogPath = Join-Path $root 'programs.json'
    $catalog = Get-Catalog $catalogPath
    Assert ($catalog.Count -ge 30) "каталог загружен ($($catalog.Count) программ)"
    $names = @($catalog | ForEach-Object { $_.Name })
    Assert ((@($names | Select-Object -Unique)).Count -eq $names.Count) 'имена программ уникальны'
    Assert (@($catalog | Where-Object { $_.Files.Count -eq 0 }).Count -eq 0) 'у каждой программы есть шаблон файла'

    $copy = Join-Path $tmp 'programs.json'
    Save-Catalog -Catalog $catalog -Path $copy
    $reloaded = Get-Catalog $copy
    $same = $reloaded.Count -eq $catalog.Count
    for ($i = 0; $same -and $i -lt $catalog.Count; $i++) {
        $a = $catalog[$i]; $b = $reloaded[$i]
        $same = ($a.Name -eq $b.Name) -and ($a.Args -eq $b.Args) -and ($a.MsiArgs -eq $b.MsiArgs) -and
        (($a.Files -join '|') -eq ($b.Files -join '|')) -and (($a.Detect -join '|') -eq ($b.Detect -join '|'))
    }
    Assert $same 'каталог сохраняется и читается без потерь'
    $origText = (Get-Content $catalogPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
    $newText = (Get-Content $copy -Raw -Encoding UTF8) -replace "`r`n", "`n"
    Assert ($origText.Trim() -eq $newText.Trim()) 'формат programs.json сохраняется при перезаписи'

    $presets = Get-Presets (Join-Path $root 'presets.json')
    Assert ($presets.Count -ge 1) "наборы загружены ($($presets.Count))"
    foreach ($k in $presets.Keys) {
        $unknown = @($presets[$k] | Where-Object { $names -notcontains $_ })
        Assert ($unknown.Count -eq 0) "набор «$k»: все программы есть в каталоге $($unknown -join ', ')"
    }
    $presetCopy = Join-Path $tmp 'presets.json'
    Save-Presets -Presets $presets -Path $presetCopy
    $p2 = Get-Presets $presetCopy
    Assert (($p2.Keys -join '|') -eq ($presets.Keys -join '|')) 'наборы сохраняются и читаются без потерь'

    Write-Host 'Определение типа установщика' -ForegroundColor Cyan
    $inno = New-FakeFile 'mystery-inno.exe' 'This installation was built with Inno Setup.' -Utf16
    $nsis = New-FakeFile 'mystery-nsis.exe' '<assemblyIdentity name="Nullsoft.NSIS.exehead"/>'
    $burn = New-FakeFile 'mystery-burn.exe' '.text....wixburn....'
    $ishield = New-FakeFile 'mystery-is.exe' 'InstallShield (R) Setup' -Utf16
    $unknown = New-FakeFile 'mystery-unknown.exe' 'nothing to see here'
    Assert ((Get-InstallerType $inno).Type -eq 'Inno Setup') 'Inno Setup (строка в UTF-16)'
    Assert ((Get-InstallerType $inno).Args -like '/VERYSILENT*') 'Inno Setup → /VERYSILENT'
    Assert ((Get-InstallerType $nsis).Args -eq '/S') 'NSIS → /S'
    Assert ((Get-InstallerType $burn).Type -eq 'WiX Burn') 'WiX Burn'
    Assert ((Get-InstallerType $ishield).Type -eq 'InstallShield') 'InstallShield'
    Assert (-not (Get-InstallerType $unknown).Known) 'неизвестный установщик помечается как неопределённый'

    Write-Host 'Сопоставление дистрибутивов с каталогом' -ForegroundColor Cyan
    New-FakeFile '7z2409-x64.exe' | Out-Null
    New-FakeFile 'putty-64bit-0.81-installer.msi' | Out-Null
    New-FakeFile 'AcroRdrDC2400221005_ru_RU.exe' | Out-Null
    New-FakeFile 'Adobe Acrobat\setup.exe' | Out-Null
    New-FakeFile 'Adobe Acrobat\AcroPro.msi' | Out-Null
    New-FakeFile 'Adobe Acrobat\Transforms\1049.mst' | Out-Null
    New-FakeFile 'LibreOffice_24.8.2_Win_x86-64.msi' | Out-Null
    New-FakeFile 'LibreOffice_24.8.2_Win_x86-64_helppack_ru.msi' | Out-Null
    New-FakeFile 'Office\setup.exe' | Out-Null
    New-FakeFile 'readme.txt' | Out-Null

    $items = Resolve-Items -Catalog $catalog -DistribDir (Join-Path $tmp 'Distrib') -Installed @(
        [pscustomobject]@{ Name = '7-Zip 23.01 (x64)'; Version = '23.01' })
    function Get-Item2([string]$n) { $items | Where-Object { $_.Name -eq $n } | Select-Object -First 1 }

    Assert ((Get-Item2 '7-Zip').RelPath -eq '7z2409-x64.exe') '7-Zip найден по шаблону'
    Assert ((Get-Item2 '7-Zip').Args -eq '/S') '7-Zip: ключи из каталога'
    Assert ((Get-Item2 '7-Zip').Installed -eq '23.01') '7-Zip: определена установленная версия'
    Assert ((Get-Item2 'PuTTY').Args -eq '/qn /norestart') 'MSI без ключей в каталоге → /qn /norestart'
    Assert ((Get-Item2 'Adobe Acrobat Reader').RelPath -eq 'AcroRdrDC2400221005_ru_RU.exe') 'Acrobat Reader найден'
    Assert ((Get-Item2 'Adobe Acrobat (Pro/Standard)').RelPath -eq 'Adobe Acrobat\setup.exe') 'Acrobat Pro найден в подпапке'
    Assert ((Get-Item2 'LibreOffice').RelPath -eq 'LibreOffice_24.8.2_Win_x86-64.msi') 'LibreOffice: основной пакет'
    Assert ((Get-Item2 'LibreOffice (справка)').RelPath -eq 'LibreOffice_24.8.2_Win_x86-64_helppack_ru.msi') 'LibreOffice: справка отдельно'
    Assert ((Get-Item2 'Microsoft Office (ODT)').RelPath -eq 'Office\setup.exe') 'Office (ODT) в подпапке'
    Assert ($null -eq (Get-Item2 'Google Chrome').File) 'Chrome без дистрибутива'
    $auto = @($items | Where-Object { $_.Source -eq 'auto' } | ForEach-Object { $_.Name })
    Assert ($auto -contains 'mystery-inno') 'неизвестный файл добавлен как автоопределённый'
    Assert (-not ($auto | Where-Object { $_ -like 'Adobe Acrobat*' })) 'файлы из папки Acrobat не дублируются'
    Assert (-not ($auto | Where-Object { $_ -like 'readme*' })) 'неустановочные файлы игнорируются'
    Assert ((Get-Item2 'mystery-unknown').NeedsArgs) 'для неопределённого установщика требуются ключи'

    Write-Host 'Команды установки' -ForegroundColor Cyan
    $c = Get-InstallCommand -Item (Get-Item2 'PuTTY') -LogDir 'C:\Logs'
    Assert ($c.FilePath -eq 'msiexec.exe' -and $c.Arguments -like '/i "*putty-64bit-0.81-installer.msi" /qn /norestart /l`*v "C:\Logs*PuTTY*.log"') "MSI: $($c.Arguments)"
    $c = Get-InstallCommand -Item (Get-Item2 '7-Zip')
    Assert ($c.FilePath -like '*7z2409-x64.exe' -and $c.Arguments -eq '/S') 'EXE: запуск с ключами из каталога'
    $cmdFile = Join-Path $tmp 'fix.cmd'
    $c = Get-InstallCommand -Item ([pscustomobject]@{ Name = 'x'; File = $cmdFile; Args = '/q' })
    Assert ($c.FilePath -eq 'cmd.exe' -and $c.Arguments -eq ('/c "pushd "{0}" && call "{1}" /q"' -f $tmp, $cmdFile)) "CMD: $($c.Arguments)"
    Assert ((Get-ExitCodeInfo 3010).Status -eq 'Reboot') 'код 3010 → нужна перезагрузка'
    Assert ((Get-ExitCodeInfo 1603).Status -eq 'Error') 'код 1603 → ошибка'
    Assert ((Get-ExitCodeInfo 5 @(5)).Status -eq 'OK') 'SuccessCodes из каталога учитываются'

    Write-Host 'Очередь установки (тестовый запуск)' -ForegroundColor Cyan
    $script:LogCallback = { param($line, $level) }
    $queue = @((Get-Item2 'Google Chrome'), (Get-Item2 'mystery-unknown'), (Get-Item2 '7-Zip'))
    $res = Invoke-InstallQueue -Items $queue -DryRun -SkipInstalled
    Assert ($res.Count -eq 3) 'обработаны все элементы очереди'
    Assert ($res[0].Message -like 'Нет дистрибутива*') 'нет дистрибутива → пропуск'
    Assert ($res[1].Message -like 'Тип установщика не определён*') 'неизвестный тип без ключей → пропуск'
    Assert ($res[2].Message -like 'Уже установлено*') 'уже установленная программа пропускается'
    $script:LogCallback = $null

    if ($E2E) {
        Write-Host 'Сквозной тест: настоящая тихая установка' -ForegroundColor Cyan
        if (-not (Test-IsWindowsOS) -or -not (Test-IsAdmin)) { throw 'Сквозной тест требует Windows и права администратора' }
        $dist = Join-Path $tmp 'E2E'
        New-Item -ItemType Directory -Path $dist | Out-Null
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $downloads = @{
            '7z2409-x64.exe'                 = 'https://www.7-zip.org/a/7z2409-x64.exe'
            'putty-64bit-0.81-installer.msi' = 'https://the.earth.li/~sgtatham/putty/0.81/w64/putty-64bit-0.81-installer.msi'
            'mystery-setup.exe'              = 'https://github.com/notepad-plus-plus/notepad-plus-plus/releases/download/v8.6.9/npp.8.6.9.Installer.x64.exe'
        }
        $ProgressPreference = 'SilentlyContinue'
        foreach ($k in $downloads.Keys) { Invoke-WebRequest -Uri $downloads[$k] -OutFile (Join-Path $dist $k) -UseBasicParsing }

        # Режим командной строки: программы из каталога (EXE и MSI) + автоопределение (NSIS, файл переименован).
        $ps = Get-PowerShellExe
        & $ps -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'SilentInstaller.ps1') -Distrib $dist -Programs '7-Zip,PuTTY,mystery-setup'
        Assert ($LASTEXITCODE -eq 0) "режим командной строки завершился успешно (код $LASTEXITCODE)"
        $installed = Get-InstalledPrograms
        Assert ($null -ne (Find-InstalledVersion @('7-Zip*') $installed)) '7-Zip установлен (EXE, ключи из каталога)'
        Assert ($null -ne (Find-InstalledVersion @('PuTTY*') $installed)) 'PuTTY установлен (MSI)'
        Assert ($null -ne (Find-InstalledVersion @('Notepad++*') $installed)) 'Notepad++ установлен (NSIS, автоопределение)'

        # Режим задания — так окно программы запускает установку с правами администратора.
        $status = Join-Path $tmp 'job.status'
        $job = [ordered]@{
            Items          = @([ordered]@{ Name = '7-Zip'; File = (Join-Path $dist '7z2409-x64.exe'); Args = '/S'; NeedsArgs = $false; Installed = $null; SuccessCodes = @(); TimeoutMinutes = $null })
            SkipInstalled  = $false
            TimeoutMinutes = 10
            StatusFile     = $status
            StopFile       = (Join-Path $tmp 'job.stop')
        }
        $jobFile = Join-Path $tmp 'job.json'
        Write-TextFileUtf8 -Path $jobFile -Text (ConvertTo-Json -InputObject $job -Depth 5)
        & $ps -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'SilentInstaller.ps1') -JobFile $jobFile
        Assert ($LASTEXITCODE -eq 0) "режим задания завершился успешно (код $LASTEXITCODE)"
        $events = @(Get-Content $status -Encoding UTF8 | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
        Assert (@($events | Where-Object { $_.Event -eq 'start' -and $_.Name -eq '7-Zip' }).Count -eq 1) 'событие start записано'
        Assert (@($events | Where-Object { $_.Event -eq 'done' -and $_.Status -eq 'OK' }).Count -eq 1) 'событие done со статусом OK'
        Assert (@($events | Where-Object { $_.Event -eq 'finished' }).Count -eq 1) 'событие finished записано'
    }
}
catch {
    Write-Host ('  [FAIL] Исключение: ' + $_.Exception.Message + "`n" + $_.ScriptStackTrace) -ForegroundColor Red
    $script:failures++
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

if ($script:failures -gt 0) { Write-Host "Ошибок: $($script:failures)" -ForegroundColor Red; exit 1 }
Write-Host 'Все тесты пройдены' -ForegroundColor Green
exit 0
