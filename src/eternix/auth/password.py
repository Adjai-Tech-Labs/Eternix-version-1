"""Password hashing and policy using Argon2id.

Passwords are hashed with Argon2id through the maintained ``argon2-cffi``
library.  Plaintext passwords are never stored, logged, or returned.
"""

from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerificationError

from eternix.auth.config import auth_settings

_hasher: PasswordHasher | None = None


def _get_hasher() -> PasswordHasher:
    global _hasher
    if _hasher is None:
        _hasher = PasswordHasher(
            time_cost=auth_settings.argon2_time_cost,
            memory_cost=auth_settings.argon2_memory_cost,
            parallelism=auth_settings.argon2_parallelism,
            hash_len=auth_settings.argon2_hash_len,
            salt_len=auth_settings.argon2_salt_len,
        )
    return _hasher


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    if not password:
        raise ValueError("Password must not be empty")
    return _get_hasher().hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2id hash.

    Returns ``False`` for any malformed hash or verification failure so
    callers can treat the result uniformly.
    """
    if not password or not password_hash:
        return False
    try:
        return bool(_get_hasher().verify(password_hash, password))
    except (VerificationError, Argon2Error, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Return True when the stored hash was produced with weaker parameters."""
    if not password_hash:
        return True
    try:
        return bool(_get_hasher().check_needs_rehash(password_hash))
    except (Argon2Error, ValueError):
        return True


def password_policy_error(password: str) -> str | None:
    """Validate a password against the configured policy.

    Returns ``None`` when the password is acceptable, otherwise a
    human-readable explanation of the first violated rule.
    """
    if len(password) < auth_settings.password_min_length:
        return f"Password must be at least {auth_settings.password_min_length} characters."
    if auth_settings.password_require_digit and not re.search(r"\d", password):
        return "Password must contain at least one digit."
    if auth_settings.password_require_uppercase and not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if auth_settings.password_require_lowercase and not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if auth_settings.password_require_special and not re.search(r"[^A-Za-z0-9]", password):
        return "Password must contain at least one special character."
    return None


def is_common_password(password: str) -> bool:
    """Reject a small blocklist of trivially common passwords.

    This is a pragmatic minimum; production deployments should consult a
    breached-password corpus (e.g. HaveIBeenPwned) out of band.
    """
    common = {
        "password",
        "password1",
        "12345678",
        "qwerty123",
        "eternix",
        "eternix123",
        "letmein",
        "iloveyou",
    }
    return password.strip().lower() in common
