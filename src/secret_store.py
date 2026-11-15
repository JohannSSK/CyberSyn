import os
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

KEY_FILE = Path(__file__).resolve().parent / "backend" / "secret.key"


def _fernet():
    env_key = os.environ.get("CYBERSYN_KEY", "").strip()
    if env_key:
        return Fernet(env_key.encode("ascii"))
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_bytes(Fernet.generate_key())
        os.chmod(KEY_FILE, 0o600)
    return Fernet(KEY_FILE.read_bytes().strip())


def is_encrypted(value):
    return isinstance(value, str) and value.startswith("gAAAA")


def encrypt_secret(value):
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(stored):
    if not is_encrypted(stored):
        return ""
    try:
        return _fernet().decrypt(stored.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def mask_stored_key(stored):
    key = decrypt_secret(stored)
    return "****" + key[-4:] if key else ""


def migrate_api_keys(db_file):
    con = sqlite3.connect(db_file)
    rows = con.execute("SELECT Parent_id, Employee_id, API_KEY FROM SETTINGS").fetchall()
    for parent_id, employee_id, key in rows:
        if key and not is_encrypted(key):
            con.execute(
                "UPDATE SETTINGS SET API_KEY = ? WHERE Parent_id = ? AND Employee_id = ?",
                (encrypt_secret(key), parent_id, employee_id),
            )
    con.commit()
    con.close()
