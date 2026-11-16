"""Password storage and validation.

Rows written by earlier versions of this app hold plain-text passwords, so
verification accepts both forms and quietly upgrades a plain-text row to a
hash the first time its owner signs in with it.
"""

import hmac

from werkzeug.security import check_password_hash, generate_password_hash

HASH_PREFIXES = ("scrypt:", "pbkdf2:")


def hash_password(password):
    return generate_password_hash(password)


def is_hashed(stored):
    return isinstance(stored, str) and stored.startswith(HASH_PREFIXES)


def verify_password(stored, given):
    if not isinstance(stored, str) or not isinstance(given, str):
        return False
    if is_hashed(stored):
        return check_password_hash(stored, given)
    # Plain-text rows left over from earlier builds.
    return hmac.compare_digest(stored.encode("utf-8"), given.encode("utf-8"))


def upgrade_password(db, table, row_id, stored, given):
    """Replace a plain-text password with a hash, in place."""
    if is_hashed(stored):
        return False
    db.execute(
        f"UPDATE {table} SET password = ? WHERE id = ?",
        (generate_password_hash(given), row_id),
    )
    db.commit()
    return True


def admin_password_problem(password):
    """Return a message if the password is too weak, else None."""
    if len(password) < 8:
        return "Admin password must be at least 8 characters."
    if not any(c.isdigit() for c in password):
        return "Admin password must include at least one number."
    if not any(c.isalpha() for c in password):
        return "Admin password must include at least one letter."
    return None
