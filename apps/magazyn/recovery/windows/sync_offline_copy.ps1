#Requires -Version 5.1
<#
Kopiuje tylko ZASZYFROWANE archiwum Magazynu i kopię AES.age na gotowy
BitLocker To Go. Nigdy nie kopiuje jawnego AES ani bazy SQLite.
Uruchom: .\sync_offline_copy.ps1 -DriveLetter E
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[A-Za-z]$')]
    [string]$DriveLetter,
    [string]$NasRoot = '\\globalnas.local\AI_Platform\Magazyn'
)
$ErrorActionPreference='Stop'
$mount=$DriveLetter.ToUpperInvariant()+':'
$logical=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$mount'"
$volume=Get-BitLockerVolume -MountPoint $mount -ErrorAction Stop
if (-not $logical -or [int]$logical.DriveType -ne 2 -or
    $volume.VolumeType.ToString() -ne 'RemovableData' -or
    $volume.VolumeStatus.ToString() -ne 'FullyEncrypted' -or
    $volume.ProtectionStatus.ToString() -ne 'On') {
    throw "Odmowa: pendrive nie jest w pełni zaszyfrowany BitLocker To Go."
}
$root=Join-Path ($mount+'\') 'MAGAZYN_RECOVERY'
$identity=Join-Path $root 'private\identity.txt'
if (-not (Test-Path -LiteralPath $identity -PathType Leaf)) {
    throw "Nie znaleziono klucza prywatnego age na pendrivie."
}
$sourceKey=Join-Path $NasRoot 'recovery\magazyn-v1-aes256-key-offline.age'
$daily=Join-Path $NasRoot 'daily'
if (-not (Test-Path -LiteralPath $sourceKey -PathType Leaf)) {
    throw "Na NAS nie ma jeszcze kopii AES zaszyfrowanej publicznym kluczem USB. Najpierw przekaż tylko recipient age1..."
}
$latest=Get-ChildItem -LiteralPath $daily -File -Filter '*.mgzb' |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $latest) {
    throw "Na GlobalNAS nie znaleziono zaszyfrowanej kopii Magazynu."
}
$targetKey=Join-Path $root 'recovery\magazyn-v1-aes256-key-offline.age'
$targetBackup=Join-Path (Join-Path $root 'backups') $latest.Name

function Copy-Verified([string]$Source,[string]$Target) {
    $parent=Split-Path -Parent $Target
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "Brakuje katalogu na USB: $parent"
    }
    $sourceHash=(Get-FileHash -Algorithm SHA256 -LiteralPath $Source).Hash
    if (Test-Path -LiteralPath $Target) {
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Target).Hash -ne $sourceHash) {
            throw "Istniejący plik ma inny SHA-256. Nie nadpisuję: $Target"
        }
        return
    }
    $temporary=$Target + '.partial'
    if (Test-Path -LiteralPath $temporary) {
        throw "Istnieje niedokończona kopia. Wymaga kontroli: $temporary"
    }
    try {
        Copy-Item -LiteralPath $Source -Destination $temporary -ErrorAction Stop
        $destinationHash=(Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash
        if ($sourceHash -ne $destinationHash) {
            throw "SHA-256 pliku na USB nie zgadza się ze źródłem."
        }
        Move-Item -LiteralPath $temporary -Destination $Target -ErrorAction Stop
    } catch {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}
Copy-Verified $sourceKey $targetKey
Copy-Verified $latest.FullName $targetBackup
Write-Host "ENCRYPTED_ARCHIVE_COPY_SHA256=PASS"
Write-Host "ENCRYPTED_AES_ESCROW_COPY_SHA256=PASS"
Write-Host "Archiwum: $($latest.Name)"
Write-Host "Na USB pozostały tylko zaszyfrowane archiwum, plik .age i prywatny klucz osłonięty BitLockerem."
Write-Host "Następny krok: .\test_recovery.ps1 -DriveLetter $DriveLetter"
