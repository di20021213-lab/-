# Каталог программ, наборы (пресеты), поиск дистрибутивов и определение типа установщика.

$script:SupportedExtensions = @('.exe', '.msi', '.msu', '.msix', '.msixbundle', '.appx', '.appxbundle', '.bat', '.cmd', '.ps1')
$script:TypeCache = @{}

# Сигнатуры установщиков: что искать в начале .exe-файла и какие ключи использовать.
$script:InstallerSignatures = @(
    @{ Type = 'WiX Burn';           Marks = @('.wixburn');                              Args = '/quiet /norestart' }
    @{ Type = 'Inno Setup';         Marks = @('Inno Setup');                            Args = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-' }
    @{ Type = 'NSIS';               Marks = @('Nullsoft', 'NSIS Error');                Args = '/S' }
    @{ Type = 'InstallShield';      Marks = @('InstallShield');                         Args = '/s /v"/qn /norestart"' }
    @{ Type = 'Advanced Installer'; Marks = @('Advanced Installer');                    Args = '/exenoui /qn /norestart' }
    @{ Type = 'Setup Factory';      Marks = @('Setup Factory');                         Args = '/S' }
    @{ Type = 'InstallAware';       Marks = @('InstallAware');                          Args = '/s' }
)

$script:CatalogFields = @('Name', 'Category', 'Files', 'Args', 'MsiArgs', 'Detect', 'SuccessCodes', 'TimeoutMinutes', 'Notes')

# ---------- Каталог ----------

function Get-Catalog {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Не найден файл каталога: $Path" }
    $json = Read-JsonFile $Path
    $list = New-Object System.Collections.ArrayList
    $order = 0
    foreach ($e in @($json.Programs)) {
        if ($null -eq $e -or -not $e.Name) { continue }
        $entry = [pscustomobject]@{
            Name           = [string]$e.Name
            Category       = [string](Get-OrDefault $e.Category 'Прочее')
            Files          = ConvertTo-CleanArray $e.Files
            Args           = $e.Args
            MsiArgs        = $e.MsiArgs
            Detect         = ConvertTo-CleanArray $e.Detect
            SuccessCodes   = @(@($e.SuccessCodes) | Where-Object { $null -ne $_ } | ForEach-Object { [int]$_ })
            TimeoutMinutes = $e.TimeoutMinutes
            Notes          = $e.Notes
            Order          = $order
        }
        [void]$list.Add($entry)
        $order++
    }
    return , $list
}

function Save-Catalog {
    param([Parameter(Mandatory = $true)]$Catalog, [Parameter(Mandatory = $true)][string]$Path)
    $blocks = @()
    foreach ($e in $Catalog) {
        $lines = @()
        foreach ($f in $script:CatalogFields) {
            $v = $e.$f
            if ($null -eq $v) { continue }
            if ($f -in @('Files', 'Detect', 'SuccessCodes')) {
                if (@($v).Count -eq 0) { continue }
                $lines += ('      "{0}": {1}' -f $f, (ConvertTo-JsonArrayLiteral $v))
            }
            else {
                if ("$v" -eq '' -and $f -ne 'Args') { continue }
                $lines += ('      "{0}": {1}' -f $f, (ConvertTo-JsonLiteral $v))
            }
        }
        $blocks += ("    {`r`n" + ($lines -join ",`r`n") + "`r`n    }")
    }
    $text = "{`r`n  `"Programs`": [`r`n" + ($blocks -join ",`r`n") + "`r`n  ]`r`n}`r`n"
    Write-TextFileUtf8 -Path $Path -Text $text
}

function Set-CatalogArgs {
    # Сохраняет ключи установки программы в каталог (создаёт запись, если её нет).
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Item,
        [string]$InstallArgs
    )
    $catalog = Get-Catalog $Path
    $isMsi = $Item.File -and ([System.IO.Path]::GetExtension($Item.File).ToLowerInvariant() -eq '.msi')
    $entry = $catalog | Where-Object { $_.Name -eq $Item.Name } | Select-Object -First 1
    if (-not $entry) {
        $pattern = if ($Item.File) { $Item.RelPath } else { $Item.Name }
        $entry = [pscustomobject]@{
            Name = $Item.Name; Category = 'Мои программы'; Files = @($pattern); Args = $null; MsiArgs = $null
            Detect = @(); SuccessCodes = @(); TimeoutMinutes = $null; Notes = $null; Order = $catalog.Count
        }
        [void]$catalog.Add($entry)
    }
    if ($isMsi) { $entry.MsiArgs = $InstallArgs } else { $entry.Args = $InstallArgs }
    Save-Catalog -Catalog $catalog -Path $Path
}

# ---------- Наборы (пресеты) ----------

function Get-Presets {
    param([Parameter(Mandatory = $true)][string]$Path)
    $result = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path)) { return $result }
    $json = Read-JsonFile $Path
    if ($null -eq $json -or $null -eq $json.Presets) { return $result }
    foreach ($p in $json.Presets.PSObject.Properties) {
        $result[$p.Name] = ConvertTo-CleanArray $p.Value
    }
    return $result
}

function Save-Presets {
    param([Parameter(Mandatory = $true)]$Presets, [Parameter(Mandatory = $true)][string]$Path)
    $lines = @()
    foreach ($key in $Presets.Keys) {
        $lines += ('    {0}: {1}' -f (ConvertTo-JsonLiteral $key), (ConvertTo-JsonArrayLiteral $Presets[$key]))
    }
    $text = "{`r`n  `"Presets`": {`r`n" + ($lines -join ",`r`n") + "`r`n  }`r`n}`r`n"
    Write-TextFileUtf8 -Path $Path -Text $text
}

# ---------- Определение типа установщика ----------

function Get-InstallerType {
    # Возвращает @{ Type = '...'; Args = '...'; Known = $true/$false }
    param([Parameter(Mandatory = $true)][string]$Path)
    $ext = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
    switch ($ext) {
        '.msi' { return @{ Type = 'MSI'; Args = '/qn /norestart'; Known = $true } }
        '.msu' { return @{ Type = 'MSU (обновление)'; Args = '/quiet /norestart'; Known = $true } }
        { $_ -in @('.msix', '.msixbundle', '.appx', '.appxbundle') } { return @{ Type = 'MSIX/AppX'; Args = ''; Known = $true } }
        { $_ -in @('.bat', '.cmd', '.ps1') } { return @{ Type = 'Скрипт'; Args = ''; Known = $true } }
    }

    $fi = Get-Item -LiteralPath $Path
    $key = '{0}|{1}|{2}' -f $fi.FullName, $fi.Length, $fi.LastWriteTimeUtc.Ticks
    if ($script:TypeCache.ContainsKey($key)) { return $script:TypeCache[$key] }

    $text = ''
    try {
        $vi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($fi.FullName)
        $text = @($vi.Comments, $vi.CompanyName, $vi.FileDescription, $vi.ProductName, $vi.LegalCopyright) -join ' | '
    }
    catch { }
    try {
        # Сигнатуры находятся в заголовке/ресурсах в начале файла — читаем первые 4 МБ.
        $fs = [System.IO.File]::OpenRead($fi.FullName)
        try {
            $size = [int][Math]::Min($fs.Length, 4MB)
            $buf = New-Object byte[] $size
            $read = $fs.Read($buf, 0, $size)
        }
        finally { $fs.Dispose() }
        $latin = [System.Text.Encoding]::GetEncoding(28591).GetString($buf, 0, $read)
        # Удаляем нулевые байты, чтобы строки в UTF-16 (ресурсы версии) тоже находились.
        $text += ' | ' + $latin.Replace([string][char]0, '')
    }
    catch { }

    $result = @{ Type = 'Не определён'; Args = ''; Known = $false }
    foreach ($sig in $script:InstallerSignatures) {
        $found = $false
        foreach ($mark in $sig.Marks) {
            if ($text.IndexOf($mark, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { $found = $true; break }
        }
        if ($found) { $result = @{ Type = $sig.Type; Args = $sig.Args; Known = $true }; break }
    }
    $script:TypeCache[$key] = $result
    return $result
}

# ---------- Установленные программы ----------

function Get-InstalledPrograms {
    $paths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    $result = New-Object System.Collections.ArrayList
    if (-not (Test-IsWindowsOS)) { return , $result }
    foreach ($p in $paths) {
        try {
            Get-ItemProperty -Path $p -ErrorAction SilentlyContinue | ForEach-Object {
                if ($_.DisplayName) {
                    [void]$result.Add([pscustomobject]@{ Name = [string]$_.DisplayName; Version = [string]$_.DisplayVersion })
                }
            }
        }
        catch { }
    }
    return , $result
}

function Find-InstalledVersion {
    # Возвращает версию (или 'да'), если программа найдена среди установленных, иначе $null.
    param($Patterns, $Installed)
    foreach ($pattern in @($Patterns)) {
        if (-not $pattern) { continue }
        foreach ($prog in $Installed) {
            if ($prog.Name -like $pattern) {
                if ($prog.Version) { return $prog.Version } else { return 'да' }
            }
        }
    }
    return $null
}

# ---------- Сопоставление дистрибутивов с каталогом ----------

function Get-DistribFiles {
    param([Parameter(Mandatory = $true)][string]$Dir)
    if (-not (Test-Path -LiteralPath $Dir)) { return @() }
    return @(Get-ChildItem -LiteralPath $Dir -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $script:SupportedExtensions -contains $_.Extension.ToLowerInvariant() })
}

function New-InstallItem {
    param($Name, $Category, $FileInfo, $RelPath, $Entry, $Installed, [int]$Order)
    $file = $null; $type = ''; $installArgs = ''; $needsArgs = $false
    if ($FileInfo) {
        $file = $FileInfo.FullName
        $isMsi = $FileInfo.Extension.ToLowerInvariant() -eq '.msi'
        $explicit = $null
        if ($Entry) { if ($isMsi) { $explicit = $Entry.MsiArgs } else { $explicit = $Entry.Args } }
        if ($null -ne $explicit) {
            $installArgs = [string]$explicit
            $type = if ($isMsi) { 'MSI' } else { 'Каталог' }
        }
        else {
            $t = Get-InstallerType $file
            $type = $t.Type; $installArgs = $t.Args; $needsArgs = -not $t.Known
        }
    }
    $detect = @()
    if ($Entry -and $Entry.Detect.Count -gt 0) { $detect = $Entry.Detect }
    elseif ($Entry) { $detect = @($Entry.Name + '*') }
    [pscustomobject]@{
        Name           = $Name
        Category       = $Category
        File           = $file
        RelPath        = $RelPath
        Args           = $installArgs
        Type           = $type
        NeedsArgs      = $needsArgs
        Source         = if ($Entry) { 'catalog' } else { 'auto' }
        Detect         = $detect
        Installed      = if ($detect.Count -gt 0) { Find-InstalledVersion $detect $Installed } else { $null }
        SuccessCodes   = if ($Entry) { $Entry.SuccessCodes } else { @() }
        TimeoutMinutes = if ($Entry) { $Entry.TimeoutMinutes } else { $null }
        Notes          = if ($Entry) { $Entry.Notes } else { $null }
        Order          = $Order
        ArgsEdited     = $false
    }
}

function Resolve-Items {
    # Сопоставляет файлы из папки дистрибутивов с каталогом.
    # Файлы, которых нет в каталоге, добавляются как «автоопределённые».
    param(
        [Parameter(Mandatory = $true)]$Catalog,
        [Parameter(Mandatory = $true)][string]$DistribDir,
        $Installed = @()
    )
    $sep = [System.IO.Path]::DirectorySeparatorChar
    $root = [System.IO.Path]::GetFullPath($DistribDir).TrimEnd('\', '/')
    $files = @(Get-DistribFiles $root | ForEach-Object {
            [pscustomobject]@{ Info = $_; Rel = $_.FullName.Substring($root.Length).TrimStart('\', '/').Replace('/', '\') }
        })
    $claimed = @{}
    $claimedDirs = @()
    $items = New-Object System.Collections.ArrayList

    foreach ($entry in $Catalog) {
        $match = $null
        foreach ($pattern in $entry.Files) {
            $p = $pattern.Replace('/', '\')
            $byPath = $p.Contains('\')
            $cands = @($files | Where-Object {
                    -not $claimed.ContainsKey($_.Info.FullName) -and
                    $(if ($byPath) { $_.Rel -like $p } else { $_.Info.Name -like $p })
                })
            if ($cands.Count -gt 0) {
                $match = $cands | Sort-Object -Property @{ Expression = { $_.Info.LastWriteTimeUtc } } -Descending | Select-Object -First 1
                break
            }
        }
        if ($match) {
            $claimed[$match.Info.FullName] = $true
            # Дистрибутив в подпапке (например, Distrib\Office\setup.exe): вся папка принадлежит программе.
            if ($match.Rel.Contains('\')) { $claimedDirs += $match.Info.DirectoryName + $sep }
            [void]$items.Add((New-InstallItem -Name $entry.Name -Category $entry.Category -FileInfo $match.Info -RelPath $match.Rel -Entry $entry -Installed $Installed -Order $entry.Order))
        }
        else {
            [void]$items.Add((New-InstallItem -Name $entry.Name -Category $entry.Category -FileInfo $null -RelPath '' -Entry $entry -Installed $Installed -Order $entry.Order))
        }
    }

    $order = 100000
    foreach ($f in $files) {
        if ($claimed.ContainsKey($f.Info.FullName)) { continue }
        $inClaimedDir = $false
        foreach ($d in $claimedDirs) {
            if ($f.Info.FullName.StartsWith($d, [System.StringComparison]::OrdinalIgnoreCase)) { $inClaimedDir = $true; break }
        }
        if ($inClaimedDir) { continue }
        $name = [System.IO.Path]::ChangeExtension($f.Rel, $null).TrimEnd('.')
        [void]$items.Add((New-InstallItem -Name $name -Category 'Не из каталога (автоопределение)' -FileInfo $f.Info -RelPath $f.Rel -Entry $null -Installed $Installed -Order $order))
        $order++
    }
    return , $items
}
