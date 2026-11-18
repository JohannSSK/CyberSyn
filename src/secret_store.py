import os
from tempfile import NamedTemporaryFile
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

from config import repo_path
from db import connect
from errors import ApiError

KEY_FILE = Path(os.environ.get("CYBERSYN_KEY_FILE") or repo_path("KEY_FILE"))


def _file_key():
    try:
        return KEY_FILE.read_bytes().strip()
    except FileNotFoundError:
        pass
    KEY_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Publish a *complete*, mode-0600 key, without replacing another worker's
    # key. Opening the final path with O_EXCL before writing exposes an empty
    # file to other processes. A hard link is both atomic and no-clobber.
    with NamedTemporaryFile(dir=KEY_FILE.parent, prefix=".fernet-") as tmp:
        tmp.write(Fernet.generate_key())
        tmp.flush()
        os.fsync(tmp.fileno())
        try:
            os.link(tmp.name, KEY_FILE)
        except FileExistsError:
            pass
    return KEY_FILE.read_bytes().strip()


def _fernet():
    env_key = os.environ.get("CYBERSYN_KEY", "").strip()
    try:
        if env_key:
            return Fernet(env_key.encode("ascii"))
        return Fernet(_file_key())
    except (ValueError, UnicodeError, OSError):
        raise ApiError("Server encryption key (CYBERSYN_KEY) is misconfigured.", 500) from None


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
    return ("****" + key[-4:] if len(key) >= 8 else "********") if key else ""


def migrate_api_keys(db_file):
    con = connect(db_file)
    rows = con.execute("SELECT Parent_id, Employee_id, API_KEY FROM SETTINGS").fetchall()
    for parent_id, employee_id, key in rows:
        if key and not is_encrypted(key):
            con.execute(
                "UPDATE SETTINGS SET API_KEY = ? WHERE Parent_id = ? AND Employee_id = ?",
                (encrypt_secret(key), parent_id, employee_id),
            )
    con.commit()
    con.close()
