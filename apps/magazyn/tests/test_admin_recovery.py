"""Administrator protection tests on synthetic SQLite databases."""
import pytest
from magazyn.store import Store, Problem

def test_last_admin_retained(tmp_path):
    store=Store(str(tmp_path/"inventory.sqlite3"))
    identifier=store.create_user("owner","long-example-password-123","admin")
    for mutation in ({"role":"user"},{"active":False}):
        with pytest.raises(Problem) as caught:
            store.change_user(identifier,**mutation)
        assert caught.value.status==409
    with pytest.raises(Problem) as caught:
        store.delete_user(identifier)
    assert caught.value.status==409
    assert store.users()[0]["role"]=="admin"

def test_admin_transfer_allowed(tmp_path):
    store=Store(str(tmp_path/"inventory.sqlite3"))
    first=store.create_user("owner","long-example-password-123","admin")
    second=store.create_user("backup-admin","long-example-password-456","admin")
    store.change_user(first,active=False)
    assert [u["id"] for u in store.users() if u["active"] and u["role"]=="admin"]==[second]
