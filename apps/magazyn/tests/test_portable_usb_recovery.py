"""Portable independent recovery: real age CLI and synthetic Magazyn AES archive.

No real USB, NAS, AES key, device, user data, or network involved.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import subprocess

import pytest

from magazyn import backup
from test_magazyn import scenario


MODULE = Path(__file__).resolve().parents[1] / "recovery" / "windows" / "portable_restore.py"
spec=importlib.util.spec_from_file_location("portable_restore", MODULE)
assert spec is not None and spec.loader is not None
portable=importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


@pytest.fixture
def kit(scenario, tmp_path):
    client,store,admin,worker=scenario
    loc=store.add_location("OFFLINE-A1")
    actor={"id":admin,"username":"admin1","role":"admin"}
    item=store.add_item({
        "kind":"part","designation":"OFFLINE-RECOVERY-IC",
        "primary_number":"OFFLINE-TEST-001","category":"Układy scalone"},actor)
    store.stock_operation({
        "item_id":item,"location_id":loc,"action":"receive","quantity":5,
    },actor)
    pdf=b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    store.add_document(item,"datasheet.pdf","datasheet",pdf,actor)
    key=backup.init_key(tmp_path/"protected"/"aes.key")
    archive=Path(backup.create_local(store.path,tmp_path/"spool",key)[0])
    identity=tmp_path/"USB_PRIVATE_identity.txt"
    created=subprocess.run(["age-keygen","-o",str(identity)],
                           capture_output=True,text=True,check=True)
    public=created.stderr.split("Public key: ",1)[-1].strip().splitlines()[0]
    wrapped=tmp_path/"encrypted-aes.age"
    encrypted=subprocess.run(["age","-r",public],input=backup.read_key(key),
                             capture_output=True,check=True)
    wrapped.write_bytes(encrypted.stdout)
    return store,item,key,archive,identity,wrapped


def test_verify_independently_recovers_sqlite_and_document_in_ram(kit,tmp_path):
    store,item,key,archive,identity,wrapped=kit
    assert portable.main(["verify","--identity",str(identity),
                          "--wrapped-key",str(wrapped),
                          "--archive",str(archive)])==0
    result=portable.recovery_verify(identity,wrapped,archive)
    assert result["integrity"]=="ok"
    assert result["schema"]==3
    assert result["items"]==1 and result["documents"]==1
    assert not (tmp_path/"restored.sqlite3").exists()
    assert backup.read_key(key) not in wrapped.read_bytes()
    assert portable.MAGIC == backup.MAGIC
    assert portable.AAD == backup.AAD


def test_explicit_restore_only_to_new_sqlite_and_never_overwrites(kit,tmp_path):
    store,item,key,archive,identity,wrapped=kit
    output=tmp_path/"restored.sqlite3"
    assert portable.main(["restore","--identity",str(identity),
                          "--wrapped-key",str(wrapped),"--archive",str(archive),
                          "--output",str(output)])==0
    assert output.is_file()
    assert portable.verify_database(output.read_bytes())["documents"]==1
    with pytest.raises(portable.RecoveryError,match="nie może już istnieć"):
        portable.recovery_restore(identity,wrapped,archive,output)
    assert portable.main(["verify","--identity",str(identity),
                          "--wrapped-key",str(wrapped),"--archive",str(archive),
                          "--output",str(tmp_path/"leak.sqlite3")])==2
    assert not (tmp_path/"leak.sqlite3").exists()


def test_wrong_identity_and_modified_ciphertext_fail_closed(kit,tmp_path):
    store,item,key,archive,identity,wrapped=kit
    other=tmp_path/"other_age_identity.txt"
    subprocess.run(["age-keygen","-o",str(other)],
                   capture_output=True,check=True)
    with pytest.raises(portable.RecoveryError,match="Odszyfrowanie klucza"):
        portable.recovery_verify(other,wrapped,archive)
    tampered=tmp_path/"tampered.mgzb"
    encrypted=bytearray(archive.read_bytes())
    encrypted[-1]^=0x01
    tampered.write_bytes(encrypted)
    with pytest.raises(portable.RecoveryError,match="Zły klucz AES"):
        portable.recovery_verify(identity,wrapped,tampered)


def test_unexpected_age_header_is_rejected_without_running_tool(kit,tmp_path):
    store,item,key,archive,identity,wrapped=kit
    wrong=tmp_path/"not-age.age"
    wrong.write_bytes(b"not-an-age-file"+b"x"*150)
    with pytest.raises(portable.RecoveryError,match="format"):
        portable.read_wrapped_key(identity,wrong)
    assert not (tmp_path/"exported.sqlite3").exists()


def test_document_sha256_mismatch_rejects_even_valid_aes_archive(kit,tmp_path):
    store,item,key,archive,identity,wrapped=kit
    with store.connect(write=True) as con:
        con.execute("UPDATE item_documents SET sha256=? WHERE item_id=?",
                    ("0"*64,item))
    new_file=Path(backup.create_local(store.path,tmp_path/"spool2",key)[0])
    with pytest.raises(portable.RecoveryError,match="Uszkodzona dokumentacja"):
        portable.recovery_verify(identity,wrapped,new_file)


def test_private_identity_is_not_accepted_if_missing(kit,tmp_path):
    store,item,key,archive,identity,wrapped=kit
    identity.unlink()
    with pytest.raises(portable.RecoveryError,match="prywatnego klucza"):
        portable.read_wrapped_key(identity,wrapped)


def test_real_escrow_module_interoperates_with_independent_restore(kit,tmp_path,monkeypatch):
    from magazyn import offline_escrow
    from test_offline_escrow import mock_nas
    store,item,key,archive,identity,wrapped=kit
    # A completely synthetic recipient is used: the real private USB identity
    # never exists on the AI server.
    public=subprocess.run(["age-keygen","-y",str(identity)],
                          capture_output=True,text=True,check=True).stdout.strip()
    recipient_file=tmp_path/"public-recipient.txt"
    recipient_file.write_text(public+"\n")
    fake_nas,original_run=mock_nas(tmp_path,monkeypatch)
    result=offline_escrow.wrap_offline(key,recipient_file,fake_nas)
    assert result["status"]=="OFFLINE_RECOVERY_CIPHERTEXT_PASS"
    wrapped_from_nas=(fake_nas/"Magazyn"/"recovery"/offline_escrow.ARCHIVE_NAME)
    recovered=portable.recovery_verify(identity,wrapped_from_nas,archive)
    assert recovered["schema"]==3 and recovered["documents"]==1
    assert recovered["items"]==1
    # age public recipient and AES key are still separate, no other escrow overwritten.
    assert wrapped_from_nas.read_bytes()!=wrapped.read_bytes()


def test_output_collision_does_not_delete_unrelated_file(kit,tmp_path):
    store,item,key,archive,identity,wrapped=kit
    collision=tmp_path/"restored.sqlite3"
    collision.write_bytes(b"someone else's data")
    with pytest.raises(portable.RecoveryError):
        portable.recovery_restore(identity,wrapped,archive,collision)
    assert collision.read_bytes()==b"someone else's data"
