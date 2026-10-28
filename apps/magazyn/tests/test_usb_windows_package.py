"""Windows USB recovery kit integrity and fail-closed safety guardrails."""
from pathlib import Path
import zipfile

WINDOWS=Path(__file__).resolve().parents[1]/"recovery"/"windows"
NAMES=("README_PL.md","prepare_usb.ps1","sync_offline_copy.ps1",
       "test_recovery.ps1","portable_restore.py")


def test_distribution_zip_contains_exact_sources_no_credentials():
    artifact=WINDOWS/"MAGAZYN_RECOVERY_USB_WINDOWS.zip"
    assert artifact.is_file()
    with zipfile.ZipFile(artifact,"r") as z:
        assert z.testzip() is None
        assert sorted(z.namelist())==sorted("MAGAZYN_RECOVERY_WINDOWS/"+n for n in NAMES)
        for name in NAMES:
            assert z.read("MAGAZYN_RECOVERY_WINDOWS/"+name)==(WINDOWS/name).read_bytes()
    assert artifact.stat().st_size < 500_000


def test_powershell_safeguards_no_format_no_unencrypted_identity():
    create=(WINDOWS/"prepare_usb.ps1").read_text()
    sync=(WINDOWS/"sync_offline_copy.ps1").read_text()
    test=(WINDOWS/"test_recovery.ps1").read_text()
    for source in (create,sync,test):
        assert "Get-BitLockerVolume" in source
        assert "FullyEncrypted" in source
        assert "RemovableData" in source
        assert "ProtectionStatus" in source
        for risky in ("Format-Volume ","Clear-Disk ","Initialize-Disk ","Remove-BitLockerKeyProtector"):
            assert risky not in source
    assert "age-keygen" in create
    assert "& $ageCmd.Source -o $identity" in create
    assert "MAGAZYN_RECOVERY" in create
    assert "New-Item -ItemType Directory" in create
    assert "Copy-Verified" in sync
    assert "SHA256" in sync
    assert "-RestoreToUsb" in test or "RestoreToUsb" in test
    assert "portable_restore.py" in test
