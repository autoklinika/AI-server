#Requires -Version 5.1
<#
NIE korzysta z serwera ani NAS. Odszyfrowuje klucz AES w pamięci, weryfikuje
prawdziwą zawartość .mgzb i SQLite, w tym dokumenty i sumy SHA-256.

  .\test_recovery.ps1 -DriveLetter E
  .\test_recovery.ps1 -DriveLetter E -RestoreToUsb

Druga opcja tworzy jawny plik SQLite WYŁĄCZNIE na odblokowanym,
zaszyfrowanym BitLocker To Go pendrivie. Nigdy nie nadpisuje istniejącego pliku.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[A-Za-z]$')]
    [string]$DriveLetter,
    [switch]$RestoreToUsb
)
$ErrorActionPreference='Stop'
$mount=$DriveLetter.ToUpperInvariant()+':'
$logical=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$mount'"
$bitlocker=Get-BitLockerVolume -MountPoint $mount -ErrorAction Stop
if (-not $logical -or [int]$logical.DriveType -ne 2 -or
    $bitlocker.VolumeType.ToString() -ne 'RemovableData' -or
    $bitlocker.VolumeStatus.ToString() -ne 'FullyEncrypted' -or
    $bitlocker.ProtectionStatus.ToString() -ne 'On') {
    throw "Przerwano: nośnik nie jest w pełni zaszyfrowany BitLocker To Go."
}
$root=Join-Path ($mount+'\') 'MAGAZYN_RECOVERY'
$identity=Join-Path $root 'private\identity.txt'
$wrapped=Join-Path $root 'recovery\magazyn-v1-aes256-key-offline.age'
$script=Join-Path $root 'tools\portable_restore.py'
$backupDir=Join-Path $root 'backups'
$archive=Get-ChildItem -LiteralPath $backupDir -File -Filter '*.mgzb' |
         Sort-Object Name -Descending | Select-Object -First 1
if (-not $archive -or
    -not (Test-Path -LiteralPath $identity -PathType Leaf) -or
    -not (Test-Path -LiteralPath $wrapped -PathType Leaf) -or
    -not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "Brak kompletnego zestawu: prywatnego identity, .age, archiwum .mgzb lub portable_restore.py."
}
$python=Get-Command py -ErrorAction SilentlyContinue
$pythonArgs=@()
if ($python) {
    $pythonArgs=@('-3')
} else {
    $python=Get-Command python -ErrorAction Stop
}

$arguments=$pythonArgs+@(
    $script,'verify',
    '--identity',$identity,
    '--wrapped-key',$wrapped,
    '--archive',$archive.FullName
)
& $python.Source @arguments
if ($LASTEXITCODE -ne 0) { throw "Nie udało się odzyskać i sprawdzić archiwum. Nie oznaczaj recovery jako PASS." }
Write-Host "REAL_BACKUP_AES_AND_SQLITE_IN_RAM_RECOVERY=PASS"
Write-Host "Bez plików jawnego AES ani SQLite zapisanych na dysk."

if ($RestoreToUsb) {
    $directory=Join-Path $root 'recovered'
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
    $target=Join-Path $directory ("magazyn-recovered-"+$stamp+".sqlite3")
    $restoreArguments=$pythonArgs+@(
        $script,'restore','--identity',$identity,
        '--wrapped-key',$wrapped,
        '--archive',$archive.FullName,
        '--output',$target
    )
    & $python.Source @restoreArguments
    if ($LASTEXITCODE -ne 0) { throw "Pełne odtworzenie bazy na USB NIE zostało zaliczone." }
    Write-Host "REAL_SQLITE_RESTORED_ON_ENCRYPTED_USB=PASS"
    Write-Host "OSTRZEŻENIE: plik recovered/*.sqlite3 jest jawny po odblokowaniu BitLockera."
    Write-Host "Po kontroli usuń go, gdy nie jest już potrzebny."
}
