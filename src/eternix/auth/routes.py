"""Authentication API routes.

All routes under ``/auth`` implement the mandatory registration and
account-security operations. Responses never reveal internal state,
passwords, tokens beyond the issued credentials, or other account
enumeration signals.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from eternix.auth.config import auth_settings
from eternix.auth.dependencies import (
    SessionContext,
    clear_auth_cookies,
    get_auth_service,
    require_active_account,
    require_onboarding,
    require_session,
    set_auth_cookies,
)
from eternix.auth.models import AccountStatus
from eternix.auth.service import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _error_response(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterCompleteRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class OAuthCallbackRequest(BaseModel):
    state: str
    code: str
    redirect_uri: str


class VerifyConfirmRequest(BaseModel):
    code: str


class PaymentConfirmRequest(BaseModel):
    setup_id: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordResetRequest(BaseModel):
    token: str
    new_password: str


class PasswordForgotRequest(BaseModel):
    username: str


class AccountStateRequest(BaseModel):
    account_state: str


@router.get("/config")
async def auth_config(service: AuthService = Depends(get_auth_service)) -> dict[str, Any]:
    """Public discovery of identity providers and payment configuration."""
    providers = service.identity_providers()
    providers["password_policy"] = {
        "min_length": auth_settings.password_min_length,
        "require_digit": auth_settings.password_require_digit,
        "require_uppercase": auth_settings.password_require_uppercase,
        "require_lowercase": auth_settings.password_require_lowercase,
        "require_special": auth_settings.password_require_special,
    }
    providers["username_rules"] = {
        "min_length": auth_settings.username_min_length,
        "max_length": auth_settings.username_max_length,
        "pattern": auth_settings.username_pattern,
    }
    providers["payment"] = service.payment_status()
    return providers


@router.post("/register/dev")
async def register_dev(
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    """Development-only registration (refused in production)."""
    try:
        payload = service.register_dev_identity(ip_address=_client_ip(request))
    except AuthError as exc:
        raise _error_response(exc) from exc
    set_auth_cookies(response, payload["refresh_token"], secrets.token_urlsafe(16))
    return payload


@router.get("/oauth/google/start")
async def google_oauth_start(
    redirect_uri: str,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    try:
        return service.google_authorization_url(redirect_uri)
    except AuthError as exc:
        raise _error_response(exc) from exc


@router.post("/oauth/google/callback")
async def google_oauth_callback(
    body: OAuthCallbackRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        payload = service.complete_google_signin(body.state, body.code, body.redirect_uri)
    except AuthError as exc:
        raise _error_response(exc) from exc
    set_auth_cookies(response, payload["refresh_token"], secrets.token_urlsafe(16))
    return payload


@router.get("/username/check")
async def check_username(
    username: str,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    return service.check_username(username)


@router.post("/register/complete")
async def complete_registration(
    body: RegisterCompleteRequest,
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(require_onboarding),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        payload = service.complete_registration(
            ctx.user_id, body.username, body.password, email=body.email
        )
    except AuthError as exc:
        raise _error_response(exc) from exc
    set_auth_cookies(response, payload["refresh_token"], secrets.token_urlsafe(16))
    return payload


@router.get("/verify/contact")
async def verification_contact(
    ctx: SessionContext = Depends(require_onboarding),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    user = service.store.get_user(ctx.user_id)
    if user is None:
        raise HTTPException(404, "Account not found")
    contact = service._primary_contact(user)
    if contact is None:
        return {"contact": None, "available": False}
    return {"contact": service._mask_contact(contact["value"]), "available": True}


@router.post("/verify/request")
async def request_verification(
    request: Request,
    ctx: SessionContext = Depends(require_onboarding),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        return service.request_verification(ctx.user_id, ip_address=_client_ip(request))
    except AuthError as exc:
        raise _error_response(exc) from exc


@router.post("/verify/confirm")
async def confirm_verification(
    body: VerifyConfirmRequest,
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(require_onboarding),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        payload = service.confirm_verification(ctx.user_id, body.code, ip_address=_client_ip(request))
    except AuthError as exc:
        raise _error_response(exc) from exc
    set_auth_cookies(response, payload["refresh_token"], secrets.token_urlsafe(16))
    return payload


@router.get("/payment/status")
async def payment_status(service: AuthService = Depends(get_auth_service)) -> dict[str, Any]:
    return service.payment_status()


@router.post("/payment/setup")
async def payment_setup(
    ctx: SessionContext = Depends(require_onboarding),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        return service.create_payment_setup(ctx.user_id)
    except AuthError as exc:
        raise _error_response(exc) from exc


@router.post("/payment/confirm")
async def payment_confirm(
    body: PaymentConfirmRequest,
    response: Response,
    ctx: SessionContext = Depends(require_onboarding),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        payload = service.confirm_payment_setup(ctx.user_id, body.setup_id)
    except AuthError as exc:
        raise _error_response(exc) from exc
    set_auth_cookies(response, payload["refresh_token"], secrets.token_urlsafe(16))
    return payload


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        payload = service.login(
            body.username,
            body.password,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as exc:
        raise _error_response(exc) from exc
    set_auth_cookies(response, payload["refresh_token"], secrets.token_urlsafe(16))
    return payload


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    """Refresh an access token with rotation and reuse detection.

    The refresh credential may arrive in the request body or in the
    HttpOnly refresh cookie. Cookie submissions additionally require
    the double-submit CSRF token to match.
    """
    raw_token = body.refresh_token if body and body.refresh_token else None
    cookie_token = request.cookies.get(auth_settings.session_cookie_name + "_refresh")
    if not raw_token and cookie_token:
        csrf_header = request.headers.get("X-CSRF-Token")
        csrf_cookie = request.cookies.get("eternix_csrf")
        if not csrf_header or not csrf_cookie or csrf_header != csrf_cookie:
            raise HTTPException(401, "CSRF validation failed")
        raw_token = cookie_token
    if not raw_token:
        raise HTTPException(401, "Refresh credential required")
    try:
        payload = service.refresh(raw_token, ip_address=_client_ip(request))
    except AuthError as exc:
        raise _error_response(exc) from exc
    set_auth_cookies(response, payload["refresh_token"], secrets.token_urlsafe(16))
    return payload


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    raw_refresh = request.cookies.get(auth_settings.session_cookie_name + "_refresh")
    service.logout(ctx.user_id, ctx.session_id, raw_refresh)
    clear_auth_cookies(response)
    return {"status": "ok"}


@router.post("/logout/all")
async def global_logout(
    response: Response,
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    service.global_logout(ctx.user_id)
    clear_auth_cookies(response)
    return {"status": "ok"}


@router.get("/account")
async def current_account(
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    return service.current_account(ctx.user_id)


@router.get("/sessions")
async def list_sessions(
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> list[dict[str, Any]]:
    return service.list_sessions(ctx.user_id)


@router.delete("/sessions/{session_id}")
async def revoke_session_route(
    session_id: str,
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    service.revoke_session(ctx.user_id, session_id)
    return {"status": "ok"}


@router.post("/password/change")
async def change_password(
    body: PasswordChangeRequest,
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    try:
        service.change_password(ctx.user_id, body.current_password, body.new_password)
    except AuthError as exc:
        raise _error_response(exc) from exc
    return {"status": "ok"}


@router.post("/password/forgot")
async def password_forgot(
    body: PasswordForgotRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        return service.request_password_reset(body.username, ip_address=_client_ip(request))
    except AuthError as exc:
        raise _error_response(exc) from exc


@router.post("/password/reset")
async def password_reset(
    body: PasswordResetRequest,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        return service.reset_password(body.token, body.new_password)
    except AuthError as exc:
        raise _error_response(exc) from exc


@router.post("/identity/google/link")
async def link_google(
    body: OAuthCallbackRequest,
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        return service.link_google_identity(ctx.user_id, body.state, body.code, body.redirect_uri)
    except AuthError as exc:
        raise _error_response(exc) from exc


@router.post("/identity/google/unlink")
async def unlink_google(
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    try:
        return service.unlink_google_identity(ctx.user_id)
    except AuthError as exc:
        raise _error_response(exc) from exc


@router.get("/audit")
async def audit_events(
    limit: int = 50,
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> list[dict[str, Any]]:
    return service.audit_events(ctx.user_id, limit=min(max(limit, 1), 200))


@router.post("/account/delete")
async def delete_account(
    response: Response,
    ctx: SessionContext = Depends(require_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    service.delete_account(ctx.user_id)
    clear_auth_cookies(response)
    return {"status": "deletion_pending"}


@router.post("/account/state")
async def set_account_state(
    body: AccountStateRequest,
    ctx: SessionContext = Depends(require_active_account),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    # Self-service state transitions are restricted: users may request
    # deletion; suspension/disable remain administrative operations.
    if body.account_state != AccountStatus.DELETION_PENDING.value:
        raise HTTPException(403, "Only account deletion can be self-requested")
    return service.delete_account(ctx.user_id)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    client = request.client
    return client.host if client else None
