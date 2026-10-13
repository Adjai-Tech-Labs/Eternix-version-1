"""FastAPI dependencies for backend-authoritative authorization.

Every protected route evaluates the full condition set:
valid token AND valid session AND active account AND payment
eligibility AND resource authorization. The frontend never
replaces these checks.
"""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException, Request
from starlette.responses import Response

from eternix.auth.config import auth_settings
from eternix.auth.models import AccountStatus, PaymentEligibility
from eternix.auth.service import AuthService
from eternix.auth.store import AuthStore
from eternix.auth.tokens import decode_access_token

_service: AuthService | None = None
_store: AuthStore | None = None


def get_auth_store() -> AuthStore:
    global _store
    if _store is None:
        _store = AuthStore()
    return _store


def get_auth_service() -> AuthService:
    global _service
    if _service is None:
        _service = AuthService(get_auth_store())
    return _service


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


async def extract_access_token(
    request: Request,
    authorization: str | None = Header(default=None),
    eternix_access: str | None = Cookie(default=None),
) -> str | None:
    token = _extract_bearer(authorization)
    if token:
        return token
    return eternix_access or None


class SessionContext:
    def __init__(self, user_id: str, session_id: str, purpose: str, account_state: str, payment_eligible: bool):
        self.user_id = user_id
        self.session_id = session_id
        self.purpose = purpose
        self.account_state = account_state
        self.payment_eligible = payment_eligible

    @property
    def is_active(self) -> bool:
        return self.account_state == AccountStatus.ACTIVE.value


async def require_session(
    token: str | None = Depends(extract_access_token),
    service: AuthService = Depends(get_auth_service),
) -> SessionContext:
    """Validate token, session, and account existence.

    Accepts both onboarding-scoped and access-scoped sessions.
    """
    if not token:
        raise HTTPException(401, "Authentication required")
    try:
        payload = decode_access_token(token)
    except Exception as exc:
        raise HTTPException(401, "Invalid or expired session") from exc

    session_id = payload.get("sid")
    user_id = payload.get("sub")
    purpose = payload.get("purpose", "access")
    if not session_id or not user_id:
        raise HTTPException(401, "Invalid token claims")

    session = service.store.get_session(session_id)
    if session is None or session["revoked"] or session["user_id"] != user_id:
        raise HTTPException(401, "Session is no longer valid")
    from datetime import UTC, datetime

    if session["expires_at"] and session["expires_at"] < datetime.now(UTC):
        raise HTTPException(401, "Session expired")

    user = service.store.get_user(user_id)
    if user is None:
        raise HTTPException(401, "Account no longer exists")
    if user["status"] in (AccountStatus.DISABLED, AccountStatus.DELETION_PENDING):
        raise HTTPException(401, "Account is being deleted")

    payment = service.store.get_payment_record(user_id)
    payment_eligible = bool(
        payment and payment["eligibility"] == PaymentEligibility.ELIGIBLE
    )

    service.store.touch_session(session_id)
    return SessionContext(
        user_id=user_id,
        session_id=session_id,
        purpose=purpose,
        account_state=user["status"],
        payment_eligible=payment_eligible,
    )


async def require_onboarding(ctx: SessionContext = Depends(require_session)) -> SessionContext:
    """Allow any authenticated session (used by onboarding routes)."""
    return ctx


async def require_active_account(ctx: SessionContext = Depends(require_session)) -> SessionContext:
    """Require an active account with a confirmed eligible payment method.

    This is the mandatory gate for every protected application route.
    """
    if ctx.account_state != AccountStatus.ACTIVE.value:
        raise HTTPException(403, "Account registration is incomplete")
    if not ctx.payment_eligible:
        raise HTTPException(403, "Payment method eligibility is required")
    return ctx


async def require_access_session(ctx: SessionContext = Depends(require_session)) -> SessionContext:
    """Require an access-scoped (not onboarding) session."""
    if ctx.purpose != "access":
        raise HTTPException(403, "Onboarding must be completed first")
    return ctx


def set_auth_cookies(response: Response, refresh_token: str, csrf_token: str) -> None:
    """Set the refresh credential in a HttpOnly cookie plus a
    double-submit CSRF token for state-changing cookie requests."""
    response.set_cookie(
        key=auth_settings.session_cookie_name + "_refresh",
        value=refresh_token,
        httponly=True,
        secure=auth_settings.session_secure,
        samesite=auth_settings.session_same_site,
        max_age=auth_settings.refresh_token_ttl_seconds,
        path="/",
    )
    response.set_cookie(
        key="eternix_csrf",
        value=csrf_token,
        httponly=False,
        secure=auth_settings.session_secure,
        samesite=auth_settings.session_same_site,
        max_age=auth_settings.refresh_token_ttl_seconds,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    for key in (auth_settings.session_cookie_name + "_refresh", "eternix_csrf", auth_settings.session_cookie_name):
        response.delete_cookie(key=key, path="/")
