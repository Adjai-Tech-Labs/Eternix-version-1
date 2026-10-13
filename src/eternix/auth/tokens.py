"""JWT access-token issuance and verification.

Access tokens are short-lived JWTs signed with the configured
algorithm (HS256 by default).  Only the configured algorithm is
accepted; unsigned tokens, tokens signed with a different
algorithm, tokens for another audience, and expired tokens are
rejected.

The signing key comes from the environment
(``ETERNIX_AUTH_JWT_KEY`` / ``ETERNIX_JWT_KEY``).  It is never
read from source control or embedded in the frontend bundle.
"""

from __future__ import annotations

import secrets
import time
import uuid
from typing import Any

import jwt

from eternix.auth.config import auth_settings


class TokenError(Exception):
    """Raised when a token cannot be validated."""


def _signing_key() -> str:
    key = auth_settings.jwt_signing_key.get_secret_value()
    if not key:
        # Development-only fallback so local runs work out of the box.
        # Production mode refuses to operate without an explicit key.
        if auth_settings.is_production:
            raise RuntimeError("ETERNIX_AUTH_JWT_KEY must be set in production mode")
        return "eternix-dev-insecure-jwt-signing-key-change-me"
    return key


def _algorithm() -> str:
    return auth_settings.jwt_algorithm or "HS256"


def _issuer() -> str:
    return auth_settings.jwt_issuer or "eternix"


def _audience() -> str:
    return auth_settings.jwt_audience or "eternix-api"


def _access_ttl() -> int:
    return auth_settings.access_token_ttl_seconds or 300


def create_access_token(
    user_id: str,
    *,
    lifetime_seconds: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Issue a short-lived JWT access token for a user."""
    now = int(time.time())
    lifetime = lifetime_seconds if lifetime_seconds is not None else _access_ttl()
    claims: dict[str, Any] = {
        "sub": user_id,
        "iss": _issuer(),
        "aud": _audience(),
        "iat": now,
        "exp": now + lifetime,
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, _signing_key(), algorithm=_algorithm())


def decode_access_token(token: str) -> dict[str, Any]:
    """Validate and decode an access token.

    Raises ``TokenError`` for any invalid, expired, or wrongly-scoped
    token.
    """
    if not token:
        raise TokenError("Missing token")
    try:
        claims = jwt.decode(
            token,
            _signing_key(),
            algorithms=[_algorithm()],
            issuer=_issuer(),
            audience=_audience(),
            options={
                "require": ["sub", "iss", "aud", "exp", "iat"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired") from exc
    except jwt.InvalidAlgorithmError as exc:
        raise TokenError("Invalid algorithm") from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenError("Invalid issuer") from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenError("Invalid audience") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid token") from exc
    if claims.get("typ") != "access":
        raise TokenError("Invalid token type")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise TokenError("Invalid subject")
    return claims


def generate_opaque_token() -> str:
    """Generate a cryptographically random opaque token (refresh/session)."""
    return secrets.token_urlsafe(auth_settings.refresh_token_bytes or 48)


def generate_recovery_token() -> tuple[str, str]:
    import hashlib
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode('utf-8')).hexdigest()


def generate_otp() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(auth_settings.otp_length))


def hash_otp(code: str) -> str:
    import hashlib
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def hash_refresh_token(raw_token: str) -> str:
    import hashlib
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode('utf-8'), b.encode('utf-8'))
