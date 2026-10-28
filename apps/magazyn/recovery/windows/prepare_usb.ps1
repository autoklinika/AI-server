#Requires -Version 5.1
<#
Przygotowuje klucz age WYŁĄCZNIE na już w pełni zaszyfrowanym pendrivie
BitLocker To Go. Nie formatuje dysku, nie włącza szyfrowania i nie zapisuje
klucza prywatnego na dysku systemowym ani na serwerze AI.
Uruchom: .\prepare_usb.ps1 -DriveLetter E
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[a-zA-Z]$')]
    [string]$DriveLetter
)
$ErrorActionPreference = 'Stop'
$mount = $DriveLetter.ToUpperInvariant() + ':'
if ($mount -eq $env:SystemDrive) {
    throw "Odmowa użycia dysku systemowego."
}

# DriveType 2 = genuine Windows removable drive. Fail closed for unusual USB
# disks reporting as fixed, rather than guessing by the volume letter.
$logical = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$mount'"
if (-not $logical -or [int]$logical.DriveType -ne 2) {
    throw "Wybierz prawdziwy pendrive wymienny, nie dysk wewnętrzny: $mount"
}
$bitlockerCommand = Get-Command Get-BitLockerVolume -ErrorAction SilentlyContinue
if (-not $bitlockerCommand) {
    throw "Brak BitLocker To Go: użyj Windows Pro/Enterprise/Education albo przygotuj nośnik na takim komputerze."
}
$volume = Get-BitLockerVolume -MountPoint $mount -ErrorAction Stop
if ($volume.VolumeType.ToString() -ne 'RemovableData' -or
    $volume.VolumeStatus.ToString() -ne 'FullyEncrypted' -or
    $volume.ProtectionStatus.ToString() -ne 'On' -or
    [int]$volume.EncryptionPercentage -ne 100) {
    throw "Najpierw w pełni zaszyfruj pendrive BitLocker To Go i włącz ochronę. Nie używaj trybu bez szyfrowania."
}

$ageCmd = Get-Command age-keygen -ErrorAction SilentlyContinue
if (-not $ageCmd) {
    throw "Zainstaluj age: winget install --id FiloSottile.age --exact, potem otwórz nowy PowerShell."
}

$root = Join-Path ($mount + '\') 'MAGAZYN_RECOVERY'
$private = Join-Path $root 'private'
$public = Join-Path $root 'public'
$backups = Join-Path $root 'backups'
$recovery = Join-Path $root 'recovery'
$tools = Join-Path $root 'tools'
$identity = Join-Path $private 'identity.txt'
$recipientFile = Join-Path $public 'recipient.txt'
if ((Test-Path -LiteralPath $identity) -or (Test-Path -LiteralPath $recipientFile)) {
    throw "Klucz już istnieje. Nie nadpisuję; użyj poprzedniego lub zdiagnozuj nośnik."
}

foreach ($directory in @($root,$private,$public,$backups,$recovery,$tools)) {
    if (Test-Path -LiteralPath $directory) {
        $existing=Get-Item -LiteralPath $directory -Force
        if (($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Wykryto dowiązanie katalogu. Nie zapisuję klucza poza USB."
        }
    } else {
        New-Item -ItemType Directory -Path $directory -ErrorAction Stop | Out-Null
    }
}

& $ageCmd.Source -o $identity
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $identity)) {
    throw "Nie udało się wygenerować prywatnego klucza bezpośrednio na USB."
}
$recipient = (& $ageCmd.Source -y $identity | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $recipient -notmatch '^age1[a-z0-9]{40,90}$') {
    throw "Nie udało się wyprowadzić prawidłowego klucza publicznego age."
}
[System.IO.File]::WriteAllText($recipientFile, $recipient + [Environment]::NewLine,
    [System.Text.Encoding]::ASCII)

$ageExe = Get-Command age -ErrorAction SilentlyContinue
if ($ageExe -and -not (Test-Path -LiteralPath (Join-Path $tools 'age.exe'))) {
    Copy-Item -LiteralPath $ageExe.Source -Destination (Join-Path $tools 'age.exe') -ErrorAction Stop
}
if (-not (Test-Path -LiteralPath (Join-Path $tools 'age.exe'))) {
    throw "Nie znaleziono age.exe; bez niego odzyskiwanie offline na nowym Windows nie zadziała."
}
& (Join-Path $tools 'age.exe') --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Skopiowany program age.exe nie działa. Nie uznaję zestawu USB za kompletny."
}
foreach ($name in @('portable_restore.py','prepare_usb.ps1','sync_offline_copy.ps1',
                    'test_recovery.ps1','README_PL.md')) {
    $source = Join-Path $PSScriptRoot $name
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        $destination = Join-Path $tools $name
        if (-not (Test-Path -LiteralPath $destination)) {
            Copy-Item -LiteralPath $source -Destination $destination -ErrorAction Stop
        }
    }
}

Write-Host ""
Write-Host "ENCRYPTED_USB_BITLOCKER=PASS"
Write-Host "PRIVATE_IDENTITY_CREATED_ON_USB=PASS"
Write-Host "Klucz publiczny age (mozna bezpiecznie udostepnic):"
Write-Host $recipient
Write-Host ""
Write-Host "Klucz PRYWATNY pozostaje na pendrivie. Nie wysylaj identity.txt do czatu ani na serwer."
Write-Host "Nie zapisuj hasla BitLocker i recovery key na tym samym pendrivie."
Write-Host "Kolejny etap: przekaz tylko wartosc publiczna age1... w celu zaszyfrowania AES na GlobalNAS."
