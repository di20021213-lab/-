# Функции окна программы: список программ, наборы, добавление дистрибутивов, запуск установки.

$script:Col = @{ Check = 0; Name = 1; Category = 2; File = 3; Type = 4; Args = 5; Installed = 6; Status = 7 }

$script:st = @{
    Busy          = $false
    Worker        = $null
    JobFile       = $null
    StatusFile    = $null
    StopFile      = $null
    StatusPos     = 0
    Finished      = $true
    ExitedTicks   = 0
    Statuses      = @{}
    Results       = @()
    SuppressEvent = $false
}
$script:Presets = [ordered]@{}

function Get-StatusColor {
    param([string]$Key)
    switch ($Key) {
        'OK' { return [System.Drawing.Color]::ForestGreen }
        'Reboot' { return [System.Drawing.Color]::DarkOrange }
        'Skipped' { return [System.Drawing.Color]::DimGray }
        'Running' { return [System.Drawing.Color]::RoyalBlue }
        'Queued' { return [System.Drawing.Color]::SlateGray }
        default { return [System.Drawing.Color]::Firebrick }
    }
}

function Add-UiLog {
    param([string]$Line, [string]$Level = 'Info')
    $box = $script:ui.Log
    if (-not $box) { return }
    $color = switch ($Level) {
        'OK' { [System.Drawing.Color]::ForestGreen }
        'Warn' { [System.Drawing.Color]::DarkOrange }
        'Error' { [System.Drawing.Color]::Firebrick }
        default { [System.Drawing.Color]::Black }
    }
    $box.SelectionStart = $box.TextLength
    $box.SelectionLength = 0
    $box.SelectionColor = $color
    $box.AppendText($Line + "`r`n")
    $box.SelectionColor = $box.ForeColor
    $box.ScrollToCaret()
}

function Show-Message {
    param([string]$Text, [string]$Icon = 'Information', [string]$Buttons = 'OK')
    return [System.Windows.Forms.MessageBox]::Show($script:ui.Form, $Text, 'Silent Installer', $Buttons, $Icon)
}

function Find-Row {
    param([string]$Name)
    foreach ($row in $script:ui.Grid.Rows) {
        if ($row.Tag -and $row.Tag.Name -eq $Name) { return $row }
    }
    return $null
}

function Set-RowStatus {
    param($Row, [string]$Key, [string]$Text)
    if (-not $Row) { return }
    $cell = $Row.Cells[$script:Col.Status]
    $cell.Value = $Text
    $cell.ToolTipText = $Text
    $cell.Style.ForeColor = Get-StatusColor $Key
    $script:st.Statuses[$Row.Tag.Name] = @{ Key = $Key; Text = $Text }
}

function Update-Summary {
    $total = 0; $found = 0; $checked = 0
    foreach ($row in $script:ui.Grid.Rows) {
        $total++
        if ($row.Tag.File) { $found++ }
        if ([bool]$row.Cells[$script:Col.Check].Value) { $checked++ }
    }
    $script:ui.LblSummary.Text = 'Программ в списке: {0}   ·   найдено дистрибутивов: {1}   ·   отмечено: {2}' -f $total, $found, $checked
}

function Update-Filter {
    $grid = $script:ui.Grid
    $text = $script:ui.TxtSearch.Text.Trim()
    $onlyFound = $script:ui.ChkOnlyFound.Checked
    $grid.CurrentCell = $null
    foreach ($row in $grid.Rows) {
        $it = $row.Tag
        $visible = $true
        if ($onlyFound -and -not $it.File) { $visible = $false }
        if ($visible -and $text) {
            $hay = '{0} {1} {2}' -f $it.Name, $it.Category, $it.RelPath
            $visible = $hay.IndexOf($text, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        }
        $row.Visible = $visible
    }
}

function Update-ItemList {
    # Перечитывает каталог и папку Distrib; сохраняет отметки и изменённые ключи.
    param([string[]]$CheckPaths = @())
    $form = $script:ui.Form
    $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
    try {
        $grid = $script:ui.Grid
        $prev = @{}
        foreach ($row in $grid.Rows) {
            $prev[$row.Tag.Name] = @{ Checked = [bool]$row.Cells[$script:Col.Check].Value; Args = $row.Tag.Args; Edited = $row.Tag.ArgsEdited }
        }
        $catalog = Get-Catalog $script:CatalogPath
        $installed = Get-InstalledPrograms
        $items = Resolve-Items -Catalog $catalog -DistribDir $script:DistribDir -Installed $installed

        $grid.Rows.Clear()
        foreach ($it in @($items | Sort-Object Order)) {
            $checked = $false
            if ($prev.ContainsKey($it.Name)) {
                $p = $prev[$it.Name]
                $checked = $p.Checked
                if ($p.Edited -and $it.File) { $it.Args = $p.Args; $it.ArgsEdited = $true }
            }
            if ($it.File) {
                foreach ($cp in $CheckPaths) {
                    if (-not $cp) { continue }
                    $dirPrefix = $cp.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
                    if ($it.File -eq $cp -or $it.File.StartsWith($dirPrefix, [System.StringComparison]::OrdinalIgnoreCase)) { $checked = $true }
                }
            }
            $fileText = if ($it.File) { $it.RelPath } else { 'нет — перетащите установщик в окно' }
            $idx = $grid.Rows.Add([object[]]@($checked, $it.Name, $it.Category, $fileText, $it.Type, $it.Args, [string]$it.Installed, ''))
            $row = $grid.Rows[$idx]
            $row.Tag = $it
            if (-not $it.File) {
                $row.DefaultCellStyle.ForeColor = [System.Drawing.Color]::Gray
            }
            elseif ($it.NeedsArgs) {
                $row.Cells[$script:Col.Args].Style.BackColor = [System.Drawing.Color]::LightYellow
                $row.Cells[$script:Col.Args].ToolTipText = 'Тип установщика не определён. Укажите ключи тихой установки (двойной щелчок).'
            }
            if ($it.Notes) { $row.Cells[$script:Col.Name].ToolTipText = [string]$it.Notes }
            if ($it.Installed) { $row.Cells[$script:Col.Installed].Style.ForeColor = [System.Drawing.Color]::ForestGreen }
            if ($script:st.Statuses.ContainsKey($it.Name)) {
                $s = $script:st.Statuses[$it.Name]
                Set-RowStatus $row $s.Key $s.Text
            }
        }
        Update-Filter
        Update-Summary
    }
    catch {
        Add-UiLog ('Ошибка при обновлении списка: ' + $_.Exception.Message) 'Error'
    }
    finally {
        $form.Cursor = [System.Windows.Forms.Cursors]::Default
    }
}

function Get-CheckedItems {
    $result = @()
    foreach ($row in $script:ui.Grid.Rows) {
        if ([bool]$row.Cells[$script:Col.Check].Value) { $result += $row.Tag }
    }
    return @($result | Sort-Object Order)
}

function Set-AllChecks {
    param([switch]$FoundOnly, [bool]$Value = $true)
    foreach ($row in $script:ui.Grid.Rows) {
        if (-not $row.Visible) { continue }
        if ($FoundOnly -and -not $row.Tag.File) { continue }
        $row.Cells[$script:Col.Check].Value = $Value
    }
    Update-Summary
}

# ---------- Наборы ----------

function Update-PresetList {
    param([string]$Select)
    $cb = $script:ui.CbPreset
    $script:st.SuppressEvent = $true
    try {
        $script:Presets = Get-Presets $script:PresetsPath
        $cb.Items.Clear()
        [void]$cb.Items.Add('— выберите набор —')
        foreach ($k in $script:Presets.Keys) { [void]$cb.Items.Add([string]$k) }
        $idx = 0
        if ($Select) { $idx = [Math]::Max(0, $cb.Items.IndexOf($Select)) }
        $cb.SelectedIndex = $idx
    }
    catch { Add-UiLog ('Не удалось прочитать presets.json: ' + $_.Exception.Message) 'Error' }
    finally { $script:st.SuppressEvent = $false }
}

function Select-Preset {
    param([string]$Name)
    if (-not $script:Presets.Contains($Name)) { return }
    $names = @($script:Presets[$Name])
    $present = @{}
    foreach ($row in $script:ui.Grid.Rows) {
        $on = $names -contains $row.Tag.Name
        $row.Cells[$script:Col.Check].Value = $on
        if ($on) { $present[$row.Tag.Name] = $true }
    }
    foreach ($n in $names) {
        if (-not $present.ContainsKey($n)) { Add-UiLog ('Набор «{0}»: программа «{1}» отсутствует в списке' -f $Name, $n) 'Warn' }
    }
    Update-Summary
}

function Save-CurrentPreset {
    $names = @(Get-CheckedItems | ForEach-Object { $_.Name })
    if ($names.Count -eq 0) { Show-Message 'Сначала отметьте программы, которые войдут в набор.' 'Warning' | Out-Null; return }
    $current = ''
    if ($script:ui.CbPreset.SelectedIndex -gt 0) { $current = [string]$script:ui.CbPreset.SelectedItem }
    $name = [Microsoft.VisualBasic.Interaction]::InputBox("Название набора (программ: $($names.Count)):", 'Сохранить набор', $current)
    $name = $name.Trim()
    if (-not $name) { return }
    $script:Presets[$name] = $names
    Save-Presets -Presets $script:Presets -Path $script:PresetsPath
    Update-PresetList -Select $name
    Add-UiLog ('Набор «{0}» сохранён ({1} программ)' -f $name, $names.Count) 'OK'
}

function Remove-CurrentPreset {
    if ($script:ui.CbPreset.SelectedIndex -le 0) { return }
    $name = [string]$script:ui.CbPreset.SelectedItem
    if ((Show-Message "Удалить набор «$name»?" 'Question' 'YesNo') -ne 'Yes') { return }
    $script:Presets.Remove($name)
    Save-Presets -Presets $script:Presets -Path $script:PresetsPath
    Update-PresetList
}

# ---------- Добавление дистрибутивов ----------

function Add-Distributives {
    param([string[]]$Paths)
    $targets = @()
    $distribFull = [System.IO.Path]::GetFullPath($script:DistribDir).TrimEnd('\', '/')
    foreach ($p in $Paths) {
        if (-not $p) { continue }
        $src = [System.IO.Path]::GetFullPath($p)
        $name = Split-Path $src -Leaf
        $isDir = Test-Path -LiteralPath $src -PathType Container
        if (-not $isDir) {
            $ext = [System.IO.Path]::GetExtension($src).ToLowerInvariant()
            if ($script:SupportedExtensions -notcontains $ext) {
                $hint = if ($ext -in @('.zip', '.7z', '.rar')) { ' — распакуйте архив и перетащите папку' } else { '' }
                Add-UiLog ('Пропущен «{0}»: это не установщик{1}' -f $name, $hint) 'Warn'
                continue
            }
        }
        if ($src.StartsWith($distribFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            $targets += $src   # файл уже лежит в папке Distrib
            continue
        }
        $dest = Join-Path $distribFull $name
        try {
            $script:ui.LblStatus.Text = "Копирование: $name…"
            [System.Windows.Forms.Application]::DoEvents()
            if ($isDir) {
                [Microsoft.VisualBasic.FileIO.FileSystem]::CopyDirectory($src, $dest,
                    [Microsoft.VisualBasic.FileIO.UIOption]::AllDialogs, [Microsoft.VisualBasic.FileIO.UICancelOption]::DoNothing)
            }
            else {
                [Microsoft.VisualBasic.FileIO.FileSystem]::CopyFile($src, $dest,
                    [Microsoft.VisualBasic.FileIO.UIOption]::AllDialogs, [Microsoft.VisualBasic.FileIO.UICancelOption]::DoNothing)
            }
            if (Test-Path -LiteralPath $dest) {
                $targets += $dest
                Add-UiLog ('Добавлен дистрибутив: {0}' -f $name) 'OK'
            }
        }
        catch {
            Add-UiLog ('Не удалось скопировать «{0}»: {1}' -f $name, $_.Exception.Message) 'Error'
        }
    }
    $script:ui.LblStatus.Text = 'Готово'
    Update-ItemList -CheckPaths $targets
}

# ---------- Установка ----------

function Set-Busy {
    param([bool]$Busy)
    $script:st.Busy = $Busy
    foreach ($c in $script:ui.LockControls) { $c.Enabled = -not $Busy }
    $script:ui.BtnStop.Enabled = $Busy
    $script:ui.BtnStop.Visible = $Busy
    $script:ui.BtnInstall.Visible = -not $Busy
}

function Start-Install {
    if ($script:st.Busy) { return }
    $script:ui.Grid.EndEdit() | Out-Null
    $items = @(Get-CheckedItems)
    if ($items.Count -eq 0) { Show-Message 'Отметьте галочками программы, которые нужно установить.' 'Information' | Out-Null; return }

    $missing = @($items | Where-Object { -not $_.File })
    $toRun = @($items | Where-Object { $_.File })
    if ($missing.Count -gt 0) {
        $list = ($missing | ForEach-Object { '  • ' + $_.Name }) -join "`r`n"
        if ($toRun.Count -eq 0) {
            Show-Message ("Для отмеченных программ нет дистрибутивов:`r`n$list`r`n`r`nПеретащите установщики в окно программы.") 'Warning' | Out-Null
            return
        }
        $answer = Show-Message ("Нет дистрибутивов для:`r`n$list`r`n`r`nЭти программы будут пропущены. Продолжить?") 'Warning' 'YesNo'
        if ($answer -ne 'Yes') { return }
    }

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $jobFile = Join-Path $script:LogDir "job_$stamp.json"
    $statusFile = Join-Path $script:LogDir "job_$stamp.status"
    $stopFile = Join-Path $script:LogDir "job_$stamp.stop"
    $jobItems = @()
    foreach ($it in $toRun) {
        $jobItems += [ordered]@{
            Name = $it.Name; File = (Convert-ToUncPath $it.File); Args = [string]$it.Args; NeedsArgs = [bool]$it.NeedsArgs
            Installed = $it.Installed; SuccessCodes = @($it.SuccessCodes); TimeoutMinutes = $it.TimeoutMinutes
        }
    }
    $job = [ordered]@{
        Items          = $jobItems
        SkipInstalled  = [bool]$script:ui.ChkSkip.Checked
        TimeoutMinutes = 60
        StatusFile     = (Convert-ToUncPath $statusFile)
        StopFile       = (Convert-ToUncPath $stopFile)
    }
    try {
        Write-TextFileUtf8 -Path $jobFile -Text (ConvertTo-Json -InputObject $job -Depth 5)
        [System.IO.File]::WriteAllText($statusFile, '')
    }
    catch {
        Show-Message ("Не удалось создать файл задания в папке Logs:`r`n" + $_.Exception.Message) 'Error' | Out-Null
        return
    }

    $script:st.JobFile = $jobFile
    $script:st.StatusFile = $statusFile
    $script:st.StopFile = $stopFile
    $script:st.StatusPos = 0
    $script:st.Finished = $false
    $script:st.ExitedTicks = 0
    $script:st.Results = @()
    foreach ($it in $toRun) { Set-RowStatus (Find-Row $it.Name) 'Queued' 'В очереди' }

    $scriptPath = Convert-ToUncPath (Join-Path $script:Root 'SilentInstaller.ps1')
    $argLine = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -JobFile "{1}"' -f $scriptPath, (Convert-ToUncPath $jobFile)
    Add-UiLog ('Запуск установки ({0} программ)…' -f $toRun.Count)
    try {
        if (Test-IsAdmin) {
            $proc = Start-Process -FilePath (Get-PowerShellExe) -ArgumentList $argLine -WindowStyle Hidden -PassThru
        }
        else {
            $proc = Start-Process -FilePath (Get-PowerShellExe) -ArgumentList $argLine -Verb RunAs -WindowStyle Hidden -PassThru
        }
    }
    catch {
        Add-UiLog 'Установка отменена: не получены права администратора.' 'Error'
        foreach ($it in $toRun) { Set-RowStatus (Find-Row $it.Name) 'Skipped' 'Отменено' }
        $script:st.Finished = $true
        return
    }
    $script:st.Worker = $proc
    $script:ui.Progress.Maximum = $toRun.Count
    $script:ui.Progress.Value = 0
    Set-Busy $true
    $script:ui.Timer.Start()
}

function Stop-Install {
    if (-not $script:st.Busy -or -not $script:st.StopFile) { return }
    try { [System.IO.File]::WriteAllText($script:st.StopFile, 'stop') } catch { }
    $script:ui.BtnStop.Enabled = $false
    Add-UiLog 'Установка будет остановлена после завершения текущей программы.' 'Warn'
}

function Read-NewStatusLines {
    $path = $script:st.StatusFile
    if (-not $path -or -not (Test-Path -LiteralPath $path)) { return @() }
    $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $len = $fs.Length
        if ($len -le $script:st.StatusPos) { return @() }
        $fs.Position = $script:st.StatusPos
        $buf = New-Object byte[] ([int]($len - $script:st.StatusPos))
        $read = $fs.Read($buf, 0, $buf.Length)
        # Берём только полностью записанные строки.
        $last = -1
        for ($i = $read - 1; $i -ge 0; $i--) { if ($buf[$i] -eq 10) { $last = $i; break } }
        if ($last -lt 0) { return @() }
        $script:st.StatusPos += $last + 1
        $text = [System.Text.Encoding]::UTF8.GetString($buf, 0, $last + 1)
        return @($text -split "`n" | Where-Object { $_.Trim() })
    }
    finally { $fs.Dispose() }
}

function Receive-StatusEvents {
    foreach ($line in (Read-NewStatusLines)) {
        $ev = $null
        try { $ev = $line | ConvertFrom-Json } catch { }
        if (-not $ev) { continue }
        $evName = [string]$ev.Event
        if ($evName -eq 'log') {
            Add-UiLog ([string]$ev.Text) ([string]$ev.Level)
        }
        elseif ($evName -eq 'start') {
            $row = Find-Row ([string]$ev.Name)
            Set-RowStatus $row 'Running' 'Устанавливается…'
            if ($row -and $row.Visible) { try { $script:ui.Grid.FirstDisplayedScrollingRowIndex = $row.Index } catch { } }
            $script:ui.Progress.Value = [Math]::Min($script:ui.Progress.Maximum, [int]$ev.Index - 1)
            $script:ui.LblStatus.Text = 'Установка {0} из {1}: {2}' -f $ev.Index, $ev.Total, $ev.Name
        }
        elseif ($evName -eq 'done') {
            Set-RowStatus (Find-Row ([string]$ev.Name)) ([string]$ev.Status) ([string]$ev.Message)
            $script:st.Results += $ev
            $script:ui.Progress.Value = [Math]::Min($script:ui.Progress.Maximum, $script:ui.Progress.Value + 1)
        }
        elseif ($evName -eq 'finished') {
            Complete-Install $ev
            return
        }
    }
    if (-not $script:st.Finished -and $script:st.Worker) {
        $exited = $false
        try { $exited = $script:st.Worker.HasExited } catch { }
        if ($exited) {
            $script:st.ExitedTicks++
            if ($script:st.ExitedTicks -ge 4) {
                Complete-Install ([pscustomobject]@{ Event = 'finished'; Error = 'Процесс установки неожиданно завершился.' })
            }
        }
    }
}

function Complete-Install {
    param($FinishEvent)
    $script:st.Finished = $true
    $script:ui.Timer.Stop()
    $script:st.Worker = $null
    Set-Busy $false
    $script:ui.Progress.Value = $script:ui.Progress.Maximum
    foreach ($f in @($script:st.JobFile, $script:st.StatusFile, $script:st.StopFile)) {
        if ($f -and (Test-Path -LiteralPath $f)) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
    }
    # Сбрасываем «В очереди» у программ, до которых установка не дошла.
    foreach ($row in $script:ui.Grid.Rows) {
        $s = $script:st.Statuses[$row.Tag.Name]
        if ($s -and $s.Key -in @('Queued', 'Running')) { Set-RowStatus $row 'Skipped' 'Не установлено (остановлено)' }
    }

    $ok = @($script:st.Results | Where-Object { $_.Status -in @('OK', 'Reboot') }).Count
    $skipped = @($script:st.Results | Where-Object { $_.Status -eq 'Skipped' }).Count
    $failed = @($script:st.Results | Where-Object { $_.Status -in @('Error', 'Timeout') }).Count
    $script:ui.LblStatus.Text = 'Готово: установлено {0}, пропущено {1}, ошибок {2}' -f $ok, $skipped, $failed

    Update-ItemList
    if ($FinishEvent.Error) {
        Show-Message ("Установка прервана:`r`n" + $FinishEvent.Error) 'Error' | Out-Null
        return
    }
    $summary = "Установка завершена.`r`n`r`nУспешно: $ok`r`nПропущено: $skipped`r`nОшибок: $failed"
    if ($FinishEvent.LogFile) { $summary += "`r`n`r`nЛог: $($FinishEvent.LogFile)" }
    if ($FinishEvent.Reboot) {
        $answer = Show-Message ($summary + "`r`n`r`nДля завершения установки нужна перезагрузка. Перезагрузить компьютер сейчас?") 'Question' 'YesNo'
        if ($answer -eq 'Yes') { & shutdown.exe /r /t 5 }
    }
    else {
        $icon = if ($failed -gt 0) { 'Warning' } else { 'Information' }
        Show-Message $summary $icon | Out-Null
    }
}
