# Общие вспомогательные функции: лог, права администратора, JSON, пути.

$script:LogFile = $null       # путь к файлу лога (если задан)
$script:LogCallback = $null   # scriptblock { param($line, $level) } — вывод в GUI / файл статуса

function Write-Log {
    param(
        [string]$Message,
        [ValidateSet('Info', 'OK', 'Warn', 'Error')][string]$Level = 'Info'
    )
    $line = '{0}  {1}' -f (Get-Date -Format 'HH:mm:ss'), $Message
    if ($script:LogFile) {
        try { Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8 } catch { }
    }
    if ($script:LogCallback) {
        & $script:LogCallback $line $Level
    }
    else {
        $color = switch ($Level) { 'OK' { 'Green' } 'Warn' { 'Yellow' } 'Error' { 'Red' } default { 'Gray' } }
        Write-Host $line -ForegroundColor $color
    }
}

function Test-IsWindowsOS {
    if ($PSVersionTable.PSEdition -eq 'Core' -and -not $IsWindows) { return $false }
    return $true
}

function Test-IsAdmin {
    if (-not (Test-IsWindowsOS)) { return $true }
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal $id
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-PowerShellExe {
    return (Get-Process -Id $PID).Path
}

function Get-OrDefault {
    param($Value, $Default)
    if ($null -eq $Value -or "$Value" -eq '') { return $Default }
    return $Value
}

function ConvertTo-CleanArray {
    # Превращает значение (строку, массив или $null) в массив непустых строк.
    param($Value)
    $result = @()
    foreach ($v in @($Value)) {
        if ($null -ne $v -and "$v".Trim() -ne '') { $result += "$v" }
    }
    return , $result
}

function Get-SafeName {
    param([string]$Name)
    $invalid = [System.IO.Path]::GetInvalidFileNameChars() + @(' ', '\', '/')
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $Name.ToCharArray()) {
        if ($invalid -contains $ch) { [void]$sb.Append('_') } else { [void]$sb.Append($ch) }
    }
    return $sb.ToString()
}

function Join-PathParts {
    # Join-Path для нескольких частей (Join-Path в PS 5.1 принимает только две).
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Parts)
    $path = $Parts[0]
    for ($i = 1; $i -lt $Parts.Count; $i++) { $path = Join-Path $path $Parts[$i] }
    return $path
}

function Convert-ToUncPath {
    # Подключённые сетевые диски (Z:\) не видны процессу, запущенному с правами
    # администратора, поэтому для него пути переводятся в UNC (\\server\share\...).
    param([string]$Path)
    if (-not $Path -or -not (Test-IsWindowsOS)) { return $Path }
    if ($Path -notmatch '^([A-Za-z]):\\?') { return $Path }
    $letter = $Matches[1]
    try {
        $drive = Get-PSDrive -Name $letter -PSProvider FileSystem -ErrorAction Stop
        if ($drive.DisplayRoot -and $drive.DisplayRoot.StartsWith('\\')) {
            return $drive.DisplayRoot.TrimEnd('\') + $Path.Substring(2)
        }
    }
    catch { }
    return $Path
}

# ---------- JSON ----------

function ConvertTo-JsonLiteral {
    param($Value)
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [bool]) { if ($Value) { return 'true' } else { return 'false' } }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [decimal]) {
        return [string]::Format([System.Globalization.CultureInfo]::InvariantCulture, '{0}', $Value)
    }
    $text = [string]$Value
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    foreach ($ch in $text.ToCharArray()) {
        $code = [int]$ch
        if ($code -eq 34) { [void]$sb.Append('\"') }
        elseif ($code -eq 92) { [void]$sb.Append('\\') }
        elseif ($code -lt 32) { [void]$sb.Append(('\u{0:x4}' -f $code)) }
        else { [void]$sb.Append($ch) }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function ConvertTo-JsonArrayLiteral {
    param($Values)
    $parts = @()
    foreach ($v in @($Values)) { if ($null -ne $v) { $parts += (ConvertTo-JsonLiteral $v) } }
    return '[' + ($parts -join ', ') + ']'
}

function Read-JsonFile {
    param([string]$Path)
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ($null -eq $text -or $text.Trim() -eq '') { return $null }
    return ($text | ConvertFrom-Json)
}

function Write-TextFileUtf8 {
    param([string]$Path, [string]$Text)
    # UTF-8 с BOM — чтобы файл корректно открывался в Блокноте и Windows PowerShell 5.1.
    $enc = New-Object System.Text.UTF8Encoding $true
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}
