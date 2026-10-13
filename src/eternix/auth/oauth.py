"""Google OAuth 2.0 / OpenID Connect integration.

Implements the authorization-code flow with PKCE (S256).  The flow
uses a random ``state`` and OIDC ``nonce``, and validates the
identity-token signature against Google's published JWKS, in addition
to the issuer, audience, expiry, and nonce claims.

No client secret is ever embedded in the frontend.  The backend
exchanges the authorization code for tokens server-side.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from eternix.auth.config import auth_settings


@dataclass
class GoogleIdentity:
    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    raw_claims: dict[str, Any]


GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUER = "https://accounts.google.com"

DEFAULT_SCOPES = ["openid", "email", "profile"]


class OAuthError(Exception):
    """Raised when the Google OAuth/OIDC flow cannot be completed."""


class GoogleOAuthClient:
    """Stateless Google OAuth/OIDC client.

    The client is only usable when a Google client ID (and, for the
    token exchange, a client secret) is configured.  When unconfigured
    the methods raise ``OAuthError`` so callers can surface a truthful
    "not configured" state rather than silently succeeding.
    """

    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        self.client_id = client_id or auth_settings.google_client_id
        self.client_secret = client_secret or auth_settings.google_client_secret
        self.redirect_uri = auth_settings.google_redirect_uri
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id)

    def build_authorization_url(self, state: str, nonce: str, code_challenge: str) -> str:
        if not self.configured:
            raise OAuthError("Google OAuth is not configured")
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(DEFAULT_SCOPES),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    @staticmethod
    def generate_state() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def generate_nonce() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def generate_code_verifier() -> str:
        return secrets.token_urlsafe(64)[:128]

    @staticmethod
    def derive_code_challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    async def exchange_code(self, code: str, code_verifier: str) -> dict[str, Any]:
        """Exchange an authorization code for Google tokens."""
        if not self.configured:
            raise OAuthError("Google OAuth is not configured")
        payload = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
        if response.status_code != 200:
            raise OAuthError(f"Google token exchange failed: HTTP {response.status_code}")
        return response.json()

    async def fetch_jwks(self) -> dict[str, Any]:
        now = time.time()
        if self._jwks_cache and (now - self._jwks_fetched_at) < 300:
            return self._jwks_cache
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(GOOGLE_JWKS_ENDPOINT)
        if response.status_code != 200:
            raise OAuthError("Unable to fetch Google JWKS")
        self._jwks_cache = response.json()
        self._jwks_fetched_at = now
        return self._jwks_cache

    def _public_key_for(self, kid: str, jwks: dict[str, Any]) -> Any:
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        raise OAuthError("Google signing key not found")

    async def validate_id_token(
        self,
        id_token: str,
        *,
        expected_nonce: str | None = None,
    ) -> dict[str, Any]:
        """Validate a Google identity token and return its claims.

        Validates the RS256 signature against Google's JWKS, the issuer,
        the audience (client ID), expiry, and — when supplied — the OIDC
        nonce.
        """
        if not self.configured:
            raise OAuthError("Google OAuth is not configured")
        try:
            unverified = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OAuthError("Malformed identity token") from exc

        kid = unverified.get("kid")
        jwks = await self.fetch_jwks()
        key = self._public_key_for(kid, jwks) if kid else None

        try:
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=GOOGLE_ISSUER,
                options={
                    "require": ["iss", "aud", "exp", "iat", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise OAuthError("Identity token expired") from exc
        except jwt.InvalidIssuerError as exc:
            raise OAuthError("Invalid identity-token issuer") from exc
        except jwt.InvalidAudienceError as exc:
            raise OAuthError("Invalid identity-token audience") from exc
        except jwt.PyJWTError as exc:
            raise OAuthError("Identity-token validation failed") from exc

        if expected_nonce is not None:
            token_nonce = claims.get("nonce")
            if token_nonce != expected_nonce:
                raise OAuthError("Identity-token nonce mismatch")

        subject = claims.get("sub")
        if not subject:
            raise OAuthError("Identity token missing subject")
        return claims

def build_authorization_url(store=None, redirect_uri: str = '') -> tuple[str, str]:
    client = GoogleOAuthClient()
    if not client.configured:
        raise OAuthError('Google identity provider is not configured')
    state = GoogleOAuthClient.generate_state()
    nonce = GoogleOAuthClient.generate_nonce()
    verifier = GoogleOAuthClient.generate_code_verifier()
    challenge = GoogleOAuthClient.derive_code_challenge(verifier)
    if store is not None:
        store.store_oauth_state(
            state=state,
            code_verifier=verifier,
            nonce=nonce,
            redirect_uri=redirect_uri,
            expires_at=store.now() + __import__('datetime').timedelta(seconds=600),
        )
    return client.build_authorization_url(state, nonce, challenge), state


def exchange_code_and_validate(store, state: str, code: str, expected_redirect_uri: str) -> GoogleIdentity:
    import asyncio
    if store is not None:
        oauth_state = store.consume_oauth_state(state)
        if oauth_state is None:
            raise OAuthError('Invalid, expired, or already-used OAuth state')
        if oauth_state.redirect_uri != expected_redirect_uri:
            raise OAuthError('Redirect URI mismatch')
        verifier = oauth_state.code_verifier
        nonce = oauth_state.nonce
    else:
        raise OAuthError('Store required')
    client = GoogleOAuthClient()
    if not client.configured:
        raise OAuthError('Google identity provider is not configured')
    payload = asyncio.run(client.exchange_code(code, verifier))
    id_token = payload.get('id_token')
    if not id_token:
        raise OAuthError('Google did not return an identity token')
    claims = asyncio.run(client.validate_id_token(id_token, expected_nonce=nonce))
    return GoogleIdentity(
        subject=claims['sub'],
        email=claims.get('email'),
        email_verified=bool(claims.get('email_verified')),
        name=claims.get('name'),
        raw_claims=claims,
    )
