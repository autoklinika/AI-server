"""Encrypted DEV-only SQLite config. Never reads production paths or .env files."""
import json
import os
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet

PROVIDERS = {
    "tme": {
        "name": "TME API v2", "auth": "oauth2_client_credentials",
        "fields": ["client_token", "app_secret"],
        "required": ["client_token", "app_secret"],
        "description": "OAuth2 TME — token aplikacji i sekret",
    },
    "mouser": {
        "name": "Mouser", "auth": "api_key",
        "fields": ["api_key"], "required": ["api_key"],
        "description": "Search API Key Mouser",
    },
}

class InvalidConfig(Exception):
    pass


class DevConfig:
    def __init__(self, root):
        self.root = Path(root).resolve()
        prod_root = Path("/srv/ai-data/magazyn-v1/private/suppliers")
        # Only the explicitly fixed production private directory, or test DEV
        # fixture directories. User-provided API requests never select a path.
        if self.root == prod_root:
            self.data = self.root
        elif self.root.name == "magazyn-hurtownie-webgui-dev-20261029":
            self.data = self.root / "data"
        else:
            raise InvalidConfig("Niedozwolona lokalizacja danych integracji.")
        self.data.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.data, 0o700)
        self.key_file = self.data / "fernet.key"
        self.db_file = self.data / "suppliers-dev.sqlite3"
        if not self.key_file.exists():
            fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(Fernet.generate_key())
            except BaseException:
                self.key_file.unlink(missing_ok=True)
                raise
        self.cipher = Fernet(self.key_file.read_bytes())
        self._init_db()

    def _db(self):
        conn = sqlite3.connect(self.db_file, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._db() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS suppliers (
                supplier TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL,
                ciphertext BLOB,
                changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            for priority, provider in enumerate(PROVIDERS, start=1):
                conn.execute(
                    "INSERT OR IGNORE INTO suppliers (supplier,priority) VALUES (?,?)",
                    (provider, priority))
        os.chmod(self.db_file, 0o600)

    def internal(self, supplier):
        if supplier not in PROVIDERS:
            raise InvalidConfig("Nieznana hurtownia.")
        with self._db() as conn:
            row = conn.execute("SELECT * FROM suppliers WHERE supplier=?", (supplier,)).fetchone()
        if row is None:
            raise InvalidConfig("Brak konfiguracji hurtowni.")
        creds = json.loads(self.cipher.decrypt(row["ciphertext"])) if row["ciphertext"] else {}
        return {
            "supplier": supplier, "enabled": bool(row["enabled"]),
            "priority": int(row["priority"]), "creds": creds,
        }

    def public(self):
        result = []
        for code, info in PROVIDERS.items():
            cfg = self.internal(code)
            creds = cfg.pop("creds")
            result.append({
                **cfg, **info,
                "saved_fields": [key for key in info["fields"] if creds.get(key)],
                "configured": all(creds.get(key) for key in info["required"]),
            })
        return sorted(result, key=lambda x: x["priority"])

    def save(self, supplier, enabled=None, priority=None, credentials=None, clear=False):
        cfg = self.internal(supplier)
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise InvalidConfig("enabled musi być wartością true/false.")
            cfg["enabled"] = enabled
        if priority is not None:
            if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 99:
                raise InvalidConfig("Priorytet musi należeć do 1–99.")
            cfg["priority"] = priority
        if clear:
            cfg["creds"] = {}
        if credentials is not None:
            if not isinstance(credentials, dict) or (set(credentials) - set(PROVIDERS[supplier]["fields"])):
                raise InvalidConfig("Niedozwolone pola uwierzytelniania.")
            for field, value in credentials.items():
                if not isinstance(value, str) or len(value) > 512:
                    raise InvalidConfig("Niepoprawna długość lub typ wartości.")
                if value:
                    cfg["creds"][field] = value
        encoded = self.cipher.encrypt(
            json.dumps(cfg["creds"], ensure_ascii=False).encode()) if cfg["creds"] else None
        with self._db() as conn:
            conn.execute("""UPDATE suppliers
                SET enabled=?,priority=?,ciphertext=?,changed_at=CURRENT_TIMESTAMP
                WHERE supplier=?""",
                (int(cfg["enabled"]), cfg["priority"], encoded, supplier))
        return next(p for p in self.public() if p["supplier"] == supplier)
