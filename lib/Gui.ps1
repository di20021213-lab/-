# Окно программы (Windows Forms).

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic
. (Join-Path $PSScriptRoot 'GuiHelpers.ps1')

function New-Button {
    param([string]$Text, [scriptblock]$OnClick, [string]$Tip)
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $Text
    $b.AutoSize = $true
    $b.AutoSizeMode = 'GrowAndShrink'
    $b.Padding = New-Object System.Windows.Forms.Padding(6, 2, 6, 2)
    $b.Margin = New-Object System.Windows.Forms.Padding(3)
    if ($OnClick) { $b.add_Click($OnClick) }
    if ($Tip) { $script:ui.Tips.SetToolTip($b, $Tip) }
    return $b
}

function New-Label {
    param([string]$Text)
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $Text
    $l.AutoSize = $true
    $l.Margin = New-Object System.Windows.Forms.Padding(3, 9, 3, 3)
    return $l
}

function New-TextColumn {
    param([string]$Header, [int]$Weight, [bool]$ReadOnly = $true)
    $c = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
    $c.HeaderText = $Header
    $c.FillWeight = $Weight
    $c.ReadOnly = $ReadOnly
    $c.SortMode = 'NotSortable'
    return $c
}

function Show-MainWindow {
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $script:ui = @{ LockControls = @() }
    $script:ui.Tips = New-Object System.Windows.Forms.ToolTip

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'Silent Installer — тихая установка программ'
    $form.Size = New-Object System.Drawing.Size(1180, 780)
    $form.MinimumSize = New-Object System.Drawing.Size(900, 560)
    $form.StartPosition = 'CenterScreen'
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 9)
    $form.AllowDrop = $true
    $script:ui.Form = $form

    # ----- Верхняя панель -----
    $top = New-Object System.Windows.Forms.FlowLayoutPanel
    $top.Dock = 'Top'
    $top.AutoSize = $true
    $top.WrapContents = $true
    $top.Padding = New-Object System.Windows.Forms.Padding(6, 6, 6, 0)

    $cbPreset = New-Object System.Windows.Forms.ComboBox
    $cbPreset.DropDownStyle = 'DropDownList'
    $cbPreset.Width = 220
    $cbPreset.Margin = New-Object System.Windows.Forms.Padding(3, 5, 3, 3)
    $script:ui.CbPreset = $cbPreset

    $btnSavePreset = New-Button 'Сохранить набор…' { Save-CurrentPreset } 'Сохранить отмеченные программы как набор'
    $btnDelPreset = New-Button 'Удалить набор' { Remove-CurrentPreset }
    $btnAdd = New-Button 'Добавить дистрибутивы…' {
        $dlg = New-Object System.Windows.Forms.OpenFileDialog
        $dlg.Title = 'Выберите установщики программ'
        $dlg.Multiselect = $true
        $dlg.Filter = 'Установщики (*.exe;*.msi;*.msu;*.msix;*.appx;*.bat;*.cmd;*.ps1)|*.exe;*.msi;*.msu;*.msix;*.msixbundle;*.appx;*.appxbundle;*.bat;*.cmd;*.ps1|Все файлы (*.*)|*.*'
        if ($dlg.ShowDialog($script:ui.Form) -eq 'OK') { Add-Distributives -Paths $dlg.FileNames }
    } 'Скопировать установщики в папку Distrib'
    $btnFolder = New-Button 'Папка Distrib' { Start-Process explorer.exe -ArgumentList ('"{0}"' -f $script:DistribDir) } 'Открыть папку с дистрибутивами'
    $btnRefresh = New-Button 'Обновить' { Update-ItemList } 'Перечитать каталог и папку Distrib'
    $btnCheckFound = New-Button 'Отметить найденные' { Set-AllChecks -FoundOnly -Value $true } 'Отметить все программы, для которых есть дистрибутив'
    $btnUncheck = New-Button 'Снять отметки' { Set-AllChecks -Value $false }

    $top.Controls.AddRange(@((New-Label 'Набор:'), $cbPreset, $btnSavePreset, $btnDelPreset, $btnAdd, $btnFolder, $btnRefresh, $btnCheckFound, $btnUncheck))

    $filterBar = New-Object System.Windows.Forms.FlowLayoutPanel
    $filterBar.Dock = 'Top'
    $filterBar.AutoSize = $true
    $filterBar.Padding = New-Object System.Windows.Forms.Padding(6, 0, 6, 2)
    $txtSearch = New-Object System.Windows.Forms.TextBox
    $txtSearch.Width = 220
    $txtSearch.Margin = New-Object System.Windows.Forms.Padding(3, 5, 12, 3)
    $script:ui.TxtSearch = $txtSearch
    $chkOnlyFound = New-Object System.Windows.Forms.CheckBox
    $chkOnlyFound.Text = 'Только с дистрибутивом'
    $chkOnlyFound.AutoSize = $true
    $chkOnlyFound.Margin = New-Object System.Windows.Forms.Padding(3, 7, 12, 3)
    $script:ui.ChkOnlyFound = $chkOnlyFound
    $hint = New-Label 'Перетащите установщики (файлы или папки) прямо в это окно — они будут скопированы в папку Distrib.'
    $hint.ForeColor = [System.Drawing.Color]::DimGray
    $filterBar.Controls.AddRange(@((New-Label 'Поиск:'), $txtSearch, $chkOnlyFound, $hint))

    # ----- Таблица программ -----
    $grid = New-Object System.Windows.Forms.DataGridView
    $grid.Dock = 'Fill'
    $grid.AllowUserToAddRows = $false
    $grid.AllowUserToDeleteRows = $false
    $grid.AllowUserToResizeRows = $false
    $grid.RowHeadersVisible = $false
    $grid.SelectionMode = 'FullRowSelect'
    $grid.MultiSelect = $false
    $grid.AutoSizeColumnsMode = 'Fill'
    $grid.BackgroundColor = [System.Drawing.SystemColors]::Window
    $grid.BorderStyle = 'None'
    $grid.AllowDrop = $true
    $grid.ShowCellToolTips = $true
    $grid.AlternatingRowsDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(247, 249, 252)

    $colCheck = New-Object System.Windows.Forms.DataGridViewCheckBoxColumn
    $colCheck.HeaderText = ''
    $colCheck.Width = 32
    $colCheck.AutoSizeMode = 'None'
    $colCheck.Resizable = 'False'
    [void]$grid.Columns.Add($colCheck)
    [void]$grid.Columns.Add((New-TextColumn 'Программа' 150))
    [void]$grid.Columns.Add((New-TextColumn 'Категория' 95))
    [void]$grid.Columns.Add((New-TextColumn 'Дистрибутив' 150))
    [void]$grid.Columns.Add((New-TextColumn 'Тип' 70))
    [void]$grid.Columns.Add((New-TextColumn 'Ключи тихой установки' 160 $false))
    [void]$grid.Columns.Add((New-TextColumn 'Установлено' 70))
    [void]$grid.Columns.Add((New-TextColumn 'Статус' 140))
    $script:ui.Grid = $grid

    $menu = New-Object System.Windows.Forms.ContextMenuStrip
    $miEdit = $menu.Items.Add('Изменить ключи установки')
    $miDetect = $menu.Items.Add('Определить тип установщика заново')
    $miSave = $menu.Items.Add('Сохранить ключи в каталог (programs.json)')
    $miShow = $menu.Items.Add('Показать файл в проводнике')
    $grid.ContextMenuStrip = $menu

    # ----- Журнал -----
    $log = New-Object System.Windows.Forms.RichTextBox
    $log.Dock = 'Fill'
    $log.ReadOnly = $true
    $log.BackColor = [System.Drawing.SystemColors]::Window
    $log.Font = New-Object System.Drawing.Font('Consolas', 9)
    $log.BorderStyle = 'None'
    $log.DetectUrls = $false
    $script:ui.Log = $log

    $split = New-Object System.Windows.Forms.SplitContainer
    $split.Dock = 'Fill'
    $split.Orientation = 'Horizontal'
    $split.Panel1.Controls.Add($grid)
    $split.Panel2.Controls.Add($log)
    $split.BorderStyle = 'FixedSingle'
    $script:ui.Split = $split

    # ----- Нижняя панель -----
    $bottom = New-Object System.Windows.Forms.TableLayoutPanel
    $bottom.Dock = 'Bottom'
    $bottom.AutoSize = $true
    $bottom.ColumnCount = 1
    $bottom.Padding = New-Object System.Windows.Forms.Padding(6, 4, 6, 6)
    [void]$bottom.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))

    $actions = New-Object System.Windows.Forms.FlowLayoutPanel
    $actions.AutoSize = $true
    $actions.Dock = 'Fill'
    $actions.WrapContents = $true
    $chkSkip = New-Object System.Windows.Forms.CheckBox
    $chkSkip.Text = 'Пропускать уже установленные'
    $chkSkip.AutoSize = $true
    $chkSkip.Margin = New-Object System.Windows.Forms.Padding(3, 10, 16, 3)
    $script:ui.ChkSkip = $chkSkip

    $btnInstall = New-Button '▶  Установить выбранное' { Start-Install }
    $btnInstall.Font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
    $btnInstall.BackColor = [System.Drawing.Color]::FromArgb(0, 120, 215)
    $btnInstall.ForeColor = [System.Drawing.Color]::White
    $btnInstall.FlatStyle = 'Flat'
    $btnInstall.Padding = New-Object System.Windows.Forms.Padding(14, 4, 14, 4)
    $script:ui.BtnInstall = $btnInstall
    $btnStop = New-Button '■  Остановить после текущей' { Stop-Install }
    $btnStop.Visible = $false
    $script:ui.BtnStop = $btnStop
    $actions.Controls.AddRange(@($chkSkip, $btnInstall, $btnStop))

    $lblSummary = New-Object System.Windows.Forms.Label
    $lblSummary.AutoSize = $true
    $lblSummary.ForeColor = [System.Drawing.Color]::DimGray
    $lblSummary.Margin = New-Object System.Windows.Forms.Padding(3, 2, 3, 2)
    $script:ui.LblSummary = $lblSummary

    $progress = New-Object System.Windows.Forms.ProgressBar
    $progress.Dock = 'Fill'
    $progress.Height = 18
    $script:ui.Progress = $progress

    $lblStatus = New-Object System.Windows.Forms.Label
    $lblStatus.AutoSize = $true
    $lblStatus.Text = 'Готово'
    $lblStatus.Margin = New-Object System.Windows.Forms.Padding(3, 2, 3, 0)
    $script:ui.LblStatus = $lblStatus

    $bottom.Controls.Add($lblSummary)
    $bottom.Controls.Add($actions)
    $bottom.Controls.Add($progress)
    $bottom.Controls.Add($lblStatus)

    # Порядок добавления важен для Dock: сначала Fill, затем панели сверху и снизу.
    $form.Controls.Add($split)
    $form.Controls.Add($filterBar)
    $form.Controls.Add($top)
    $form.Controls.Add($bottom)

    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 400
    $script:ui.Timer = $timer

    $script:ui.LockControls = @($cbPreset, $btnSavePreset, $btnDelPreset, $btnAdd, $btnRefresh, $btnCheckFound, $btnUncheck, $chkSkip)

    # ----- События -----
    $timer.add_Tick({
            try { Receive-StatusEvents }
            catch { Add-UiLog ('Ошибка чтения состояния установки: ' + $_.Exception.Message) 'Error' }
        })

    $cbPreset.add_SelectedIndexChanged({
            if ($script:st.SuppressEvent -or $script:ui.CbPreset.SelectedIndex -le 0) { return }
            Select-Preset ([string]$script:ui.CbPreset.SelectedItem)
        })
    $txtSearch.add_TextChanged({ Update-Filter })
    $chkOnlyFound.add_CheckedChanged({ Update-Filter })

    $grid.add_CurrentCellDirtyStateChanged({
            $g = $script:ui.Grid
            if ($g.IsCurrentCellDirty -and $g.CurrentCell.ColumnIndex -eq $script:Col.Check) {
                [void]$g.CommitEdit([System.Windows.Forms.DataGridViewDataErrorContexts]::Commit)
            }
        })
    $grid.add_CellValueChanged({
            param($s, $e)
            if ($e.RowIndex -ge 0 -and $e.ColumnIndex -eq $script:Col.Check) { Update-Summary }
        })
    $grid.add_CellBeginEdit({
            param($s, $e)
            if ($script:st.Busy) { $e.Cancel = $true }
        })
    $grid.add_CellEndEdit({
            param($s, $e)
            if ($e.RowIndex -lt 0 -or $e.ColumnIndex -ne $script:Col.Args) { return }
            $row = $script:ui.Grid.Rows[$e.RowIndex]
            $row.Tag.Args = [string]$row.Cells[$script:Col.Args].Value
            $row.Tag.ArgsEdited = $true
            $row.Cells[$script:Col.Args].Style.BackColor = [System.Drawing.Color]::Empty
        })
    $grid.add_CellDoubleClick({
            param($s, $e)
            if ($e.RowIndex -ge 0 -and $e.ColumnIndex -eq $script:Col.Args -and -not $script:st.Busy) {
                $script:ui.Grid.CurrentCell = $script:ui.Grid.Rows[$e.RowIndex].Cells[$script:Col.Args]
                [void]$script:ui.Grid.BeginEdit($true)
            }
        })
    $grid.add_CellMouseDown({
            param($s, $e)
            if ($e.Button -eq [System.Windows.Forms.MouseButtons]::Right -and $e.RowIndex -ge 0) {
                $script:ui.Grid.CurrentCell = $script:ui.Grid.Rows[$e.RowIndex].Cells[$script:Col.Name]
            }
        })

    $menu.add_Opening({
            param($s, $e)
            $row = $script:ui.Grid.CurrentRow
            if (-not $row -or $script:st.Busy) { $e.Cancel = $true; return }
            $hasFile = [bool]$row.Tag.File
            foreach ($mi in $script:ui.Grid.ContextMenuStrip.Items) { $mi.Enabled = $hasFile }
        })
    $miEdit.add_Click({
            $row = $script:ui.Grid.CurrentRow
            if (-not $row) { return }
            $script:ui.Grid.CurrentCell = $row.Cells[$script:Col.Args]
            [void]$script:ui.Grid.BeginEdit($true)
        })
    $miDetect.add_Click({
            $row = $script:ui.Grid.CurrentRow
            if (-not $row -or -not $row.Tag.File) { return }
            $script:TypeCache.Clear()
            $t = Get-InstallerType $row.Tag.File
            $row.Tag.Type = $t.Type; $row.Tag.Args = $t.Args; $row.Tag.NeedsArgs = -not $t.Known; $row.Tag.ArgsEdited = $true
            $row.Cells[$script:Col.Type].Value = $t.Type
            $row.Cells[$script:Col.Args].Value = $t.Args
            Add-UiLog ('{0}: тип установщика — {1}, ключи: {2}' -f $row.Tag.Name, $t.Type, $t.Args)
        })
    $miSave.add_Click({
            $row = $script:ui.Grid.CurrentRow
            if (-not $row -or -not $row.Tag.File) { return }
            try {
                Set-CatalogArgs -Path $script:CatalogPath -Item $row.Tag -InstallArgs ([string]$row.Tag.Args)
                $row.Tag.ArgsEdited = $false
                Add-UiLog ('Ключи для «{0}» сохранены в programs.json' -f $row.Tag.Name) 'OK'
                Update-ItemList
            }
            catch { Add-UiLog ('Не удалось сохранить каталог: ' + $_.Exception.Message) 'Error' }
        })
    $miShow.add_Click({
            $row = $script:ui.Grid.CurrentRow
            if ($row -and $row.Tag.File) { Start-Process explorer.exe -ArgumentList ('/select,"{0}"' -f $row.Tag.File) }
        })

    $onDragEnter = {
        param($s, $e)
        if ($script:st.Busy) { $e.Effect = [System.Windows.Forms.DragDropEffects]::None; return }
        if ($e.Data.GetDataPresent([System.Windows.Forms.DataFormats]::FileDrop)) {
            $e.Effect = [System.Windows.Forms.DragDropEffects]::Copy
        }
        else { $e.Effect = [System.Windows.Forms.DragDropEffects]::None }
    }
    $onDragDrop = {
        param($s, $e)
        $paths = [string[]]$e.Data.GetData([System.Windows.Forms.DataFormats]::FileDrop)
        if ($paths) { Add-Distributives -Paths $paths }
    }
    foreach ($target in @($form, $grid, $log)) {
        $target.AllowDrop = $true
        $target.add_DragEnter($onDragEnter)
        $target.add_DragDrop($onDragDrop)
    }

    $form.add_Shown({
            $script:ui.Form.Activate()
            try { $script:ui.Split.SplitterDistance = [int]($script:ui.Split.Height * 0.68) } catch { }
        })
    $form.add_FormClosing({
            param($s, $e)
            if ($script:st.Busy) {
                $answer = Show-Message "Идёт установка программ. Закрыть окно?`r`n(Установка продолжится в фоне, итог будет в папке Logs.)" 'Warning' 'YesNo'
                if ($answer -ne 'Yes') { $e.Cancel = $true }
            }
        })

    # ----- Начальное заполнение -----
    $script:LogCallback = { param($line, $level) Add-UiLog $line $level }
    if (-not (Test-IsAdmin)) {
        Add-UiLog 'Права администратора будут запрошены при нажатии «Установить выбранное».'
    }
    Add-UiLog ('Папка дистрибутивов: {0}' -f $script:DistribDir)
    Update-PresetList
    Update-ItemList

    if ($SmokeTest) {
        # Проверка для CI: окно создаётся, список заполняется, затем закрывается.
        $form.Show()
        [System.Windows.Forms.Application]::DoEvents()
        Set-AllChecks -FoundOnly -Value $true
        if ($script:Presets.Count -gt 0) { Select-Preset ([string]@($script:Presets.Keys)[0]) }
        Update-Filter
        Write-Host ('SMOKE: rows={0}; summary={1}' -f $script:ui.Grid.Rows.Count, $script:ui.LblSummary.Text)
        Write-Host $script:ui.Log.Text
        $form.Close()
        $form.Dispose()
        if ($script:ui.Log.Text -match 'Ошибка') { throw 'В журнале окна есть ошибки' }
        return
    }
    [void]$form.ShowDialog()
    $form.Dispose()
}
