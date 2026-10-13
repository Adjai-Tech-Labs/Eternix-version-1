"""ETERNIX authentication and account lifecycle service.

Backend-authoritative implementation of the mandatory registration
state machine:

    registration_incomplete
        -> awaiting_verification      (username + Argon2id password set)
        -> awaiting_payment_method    (verified contact on record)
        -> active                   (eligible payment method confirmed)

No protected resource is accessible unless the account reaches
``active`` with an eligible payment method. All transitions are
persisted and audited.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from eternix.auth.config import auth_settings
from eternix.auth.delivery import DeliveryError, send_emailjs_email
from eternix.auth.models import (
    AccountStatus,
    ContactType,
    ContactVerificationStatus,
    IdentityProvider,
    OTPChannel,
    OTPPurpose,
    PaymentEligibility,
    PaymentProviderKind,
    RegistrationStep,
)
from eternix.auth.oauth import GoogleOAuthClient, OAuthError
from eternix.auth.password import (
    hash_password,
    is_common_password,
    needs_rehash,
    password_policy_error,
    verify_password,
)
from eternix.auth.payment import (
    PaymentProviderError,
    SetupSession,
    get_payment_provider,
    payment_provider_status,
)
from eternix.auth.store import AuthStore, _as_utc, hash_token
from eternix.auth.tokens import (
    create_access_token,
    generate_opaque_token,
    generate_otp,
)

logger = logging.getLogger(__name__)


class AuthError(ValueError):
    """User-facing authentication error with a safe message."""

    def __init__(self, message: str, code: str = "auth_error", status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


USERNAME_RE = re.compile(auth_settings.username_pattern)
RESERVED_USERNAMES = {
    "admin", "root", "eternix", "api", "support", "help",
    "info", "system", "administrator", "moderator", "staff", "security",
}

# In-memory sliding-window rate limits (single-process deployment).
_rate_limits: dict[str, list[float]] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _check_rate_limit(key: str, max_attempts: int, window_seconds: int, record: bool = True) -> bool:
    """Sliding-window rate limit.

    When ``record`` is true a failed attempt is registered in
    the window. Checks without recording are used to reject
    callers that already exhausted their budget.
    """
    now = _now().timestamp()
    window = _rate_limits.setdefault(key, [])
    window[:] = [t for t in window if now - t < window_seconds]
    if len(window) >= max_attempts:
        return False
    if record:
        window.append(now)
    return True


class AuthService:
    def __init__(self, store: AuthStore | None = None):
        self.store = store or AuthStore()
        self._google_client = GoogleOAuthClient()

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_username(username: str) -> str:
        return (username or "").strip().lower()

    def validate_username(self, username: str) -> str | None:
        normalized = self.normalize_username(username)
        if not (auth_settings.username_min_length <= len(normalized) <= auth_settings.username_max_length):
            return f"Username must be {auth_settings.username_min_length}-{auth_settings.username_max_length} characters long."
        if not USERNAME_RE.match(normalized):
            return "Username may only contain letters, digits, and underscores."
        if normalized in RESERVED_USERNAMES:
            return "This username is reserved."
        if self.store.username_exists(normalized):
            return "This username is already taken."
        return None

    def check_username(self, username: str) -> dict[str, Any]:
        normalized = self.normalize_username(username)
        error = self.validate_username(username)
        return {"username": normalized, "available": error is None, "error": error}

    # ------------------------------------------------------------------
    # Identity provider discovery
    # ------------------------------------------------------------------

    def identity_providers(self) -> dict[str, Any]:
        providers: list[dict[str, Any]] = [
            {
                "id": "google",
                "name": "Google",
                "configured": auth_settings.google_configured,
            }
        ]
        if not auth_settings.is_production:
            providers.append(
                {
                    "id": "dev",
                    "name": "Local development identity",
                    "configured": True,
                    "development_only": True,
                    "note": "Only available when ETERNIX_AUTH_MODE != production",
                }
            )
        return {
            "providers": providers,
            "google_configured": auth_settings.google_configured,
            "mode": auth_settings.mode,
        }

    # ------------------------------------------------------------------
    # Google OAuth / OIDC
    # ------------------------------------------------------------------

    def google_authorization_url(self, redirect_uri: str) -> dict[str, Any]:
        if not self._google_client.configured:
            raise AuthError("Google identity provider is not configured", "google_not_configured", 503)
        state = GoogleOAuthClient.generate_state()
        nonce = GoogleOAuthClient.generate_nonce()
        verifier = GoogleOAuthClient.generate_code_verifier()
        challenge = GoogleOAuthClient.derive_code_challenge(verifier)
        url = self._google_client.build_authorization_url(state, nonce, challenge)
        self.store.store_registration_attempt(
            state=state,
            nonce=nonce,
            code_verifier=verifier,
            expires_at=_now() + timedelta(seconds=600),
        )
        return {"authorization_url": url, "state": state}

    async def complete_google_signin(self, state: str, code: str, redirect_uri: str) -> dict[str, Any]:
        if not self._google_client.configured:
            raise AuthError("Google identity provider is not configured", "google_not_configured", 503)

        attempt = self.store.consume_registration_attempt(state)
        if attempt is None:
            raise AuthError("Invalid, expired, or already-used OAuth state", "invalid_state", 400)

        try:
            tokens = await self._google_client.exchange_code(code, attempt["code_verifier"])
        except OAuthError as exc:
            raise AuthError(str(exc), "oauth_exchange_failed", 400) from exc

        id_token = tokens.get("id_token")
        if not id_token:
            raise AuthError("Google did not return an identity token", "oauth_exchange_failed", 400)

        try:
            claims = await self._google_client.validate_id_token(
                id_token,
                expected_nonce=attempt["nonce"],
            )
        except OAuthError as exc:
            raise AuthError(str(exc), "identity_validation_failed", 400) from exc

        subject = claims.get("sub")
        email = claims.get("email")
        email_verified = bool(claims.get("email_verified"))

        existing = self.store.get_identity_by_subject(IdentityProvider.GOOGLE, subject)
        if existing:
            user = self.store.get_user(existing["user_id"])
            if user is None:
                raise AuthError("Identity record is invalid", "identity_invalid", 400)
            self._record_login(user, email)
            return self._issue_session_payload(user)

        # First Google sign-in: create a registration-incomplete account
        # linked to the verified Google identity.
        user = self.store.create_user(username=f"user-{uuid.uuid4().hex[:12]}")
        self.store.link_identity(
            user["id"],
            IdentityProvider.GOOGLE,
            subject,
            verified=True,
        )
        user = self.store.update_user(user["id"], google_linked=True)
        if email and email_verified:
            # Google has already verified this contact, so no
            # second OTP challenge is required for it.
            self._ensure_contact(user["id"], email, verified=True)
        elif email:
            self._ensure_contact(user["id"], email, verified=False)
        self.store.record_audit_event(
            event_type="registration_started",
            actor_id=user["id"],
            outcome="success",
            metadata={"provider": "google"},
        )
        self._record_login(user, email)
        return self._issue_session_payload(user)

    # ------------------------------------------------------------------
    # Development-only registration
    # ------------------------------------------------------------------

    def register_dev_identity(self, ip_address: str | None = None) -> dict[str, Any]:
        """Create a development account without Google.

        Refused in production mode. The account still completes the
        full mandatory state machine (username, Argon2id password,
        contact verification, payment eligibility) before any
        protected access is granted.
        """
        if auth_settings.is_production:
            raise AuthError("Development registration is disabled", "dev_disabled", 403)
        user = self.store.create_user(username=f"dev-{uuid.uuid4().hex[:12]}")
        self.store.link_identity(user["id"], IdentityProvider.DEV, user["id"], verified=True)
        self.store.record_audit_event(
            event_type="registration_started",
            actor_id=user["id"],
            outcome="success",
            metadata={"provider": "dev"},
            detail="Development registration",
        )
        return self._issue_session_payload(user)

    # ------------------------------------------------------------------
    # Username + password completion
    # ------------------------------------------------------------------

    def complete_registration(
        self,
        user_id: str,
        username: str,
        password: str,
        email: str | None = None,
    ) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise AuthError("Account not found", "not_found", 404)
        if user["status"] != AccountStatus.REGISTRATION_INCOMPLETE:
            raise AuthError("Registration is already completed", "invalid_state", 409)

        username_error = self.validate_username(username)
        if username_error:
            raise AuthError(username_error, "invalid_username", 400)
        policy_error = password_policy_error(password)
        if policy_error:
            raise AuthError(policy_error, "weak_password", 400)
        if is_common_password(password):
            raise AuthError("This password is too common. Choose a stronger password.", "weak_password", 400)

        user = self.store.update_user(
            user_id,
            username=self.normalize_username(username),
            password_hash=hash_password(password),
            status=AccountStatus.AWAITING_VERIFICATION,
        )
        if email:
            self._ensure_contact(user_id, self.normalize_email(email), verified=False)
        # A contact that is already verified (for example the email
        # asserted by a completed Google sign-in) satisfies the
        # verification prerequisite without a second challenge.
        contact = self._primary_contact(user)
        if contact is not None and contact["verification_status"] == ContactVerificationStatus.VERIFIED:
            user = self.store.update_user(user_id, status=AccountStatus.AWAITING_PAYMENT_METHOD)
        self.store.record_audit_event(
            event_type="registration_credentials_set",
            actor_id=user_id,
            outcome="success",
        )
        return self._issue_session_payload(user)

    # ------------------------------------------------------------------
    # Contact verification
    # ------------------------------------------------------------------

    def request_verification(self, user_id: str, ip_address: str | None = None) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise AuthError("Account not found", "not_found", 404)
        if user["status"] != AccountStatus.AWAITING_VERIFICATION:
            raise AuthError("Verification is not required at this step", "invalid_state", 409)

        contact = self._primary_contact(user)
        if contact is None:
            raise AuthError(
                "No contact method is available. Complete Google sign-in or configure an email provider.",
                "no_contact",
                503,
            )

        if not _check_rate_limit(f"otp:{contact['value']}", auth_settings.otp_max_requests_per_hour, 3600):
            raise AuthError("Too many verification requests. Try again later.", "rate_limited", 429)

        # Resend cooldown: a pending challenge must be old
        # enough before a replacement code is issued.
        pending = self.store.get_pending_otp_challenge(contact["value"], OTPPurpose.REGISTRATION)
        if pending is not None and pending["created_at"] is not None:
            age = (_now() - pending["created_at"]).total_seconds()
            if age < auth_settings.otp_request_cooldown_seconds:
                remaining = int(auth_settings.otp_request_cooldown_seconds - age) + 1
                raise AuthError(
                    f"Please wait {remaining} seconds before requesting another code.",
                    "cooldown",
                    429,
                )

        # Cryptographically secure numeric code generated
        # with the secrets module.
        code = generate_otp()

        # Invalidate previous pending codes so only the
        # most recently issued code can verify.
        self.store.invalidate_otp_challenges(contact["value"], OTPPurpose.REGISTRATION)

        challenge = self.store.create_otp_challenge(
            contact_value=contact["value"],
            channel=OTPChannel.EMAIL if "@" in contact["value"] else OTPChannel.PHONE,
            purpose=OTPPurpose.REGISTRATION,
            code_hash=hash_token(code),
            max_attempts=auth_settings.otp_max_attempts,
            expires_at=_now() + timedelta(seconds=auth_settings.otp_expiry_seconds),
            ip_address=ip_address,
        )

        try:
            delivery = self._deliver_otp(contact["value"], code)
        except AuthError:
            # A failed delivery must not leave a pending
            # challenge that blocks an immediate resend.
            self.store.consume_otp_challenge(challenge["id"])
            self.store.record_audit_event(
                event_type="verification_requested",
                actor_id=user_id,
                outcome="failure",
                ip_address=ip_address,
                detail="delivery failed",
            )
            raise
        self.store.record_audit_event(
            event_type="verification_requested",
            actor_id=user_id,
            outcome="success",
            ip_address=ip_address,
        )
        return {
            "contact": self._mask_contact(contact["value"]),
            "expires_in": auth_settings.otp_expiry_seconds,
            "dev_code": code if delivery == "dev" else None,
            "delivery": delivery,
        }

    def _deliver_otp(self, contact_value: str, code: str) -> str:
        """Deliver an OTP through the configured provider.

        In development mode without a configured delivery
        provider the code is returned to the caller for
        display. This is a development convenience that is
        disabled in production.  Real delivery failures are
        raised so the caller never reports a false success.
        """
        if not auth_settings.is_production and not auth_settings.email_configured:
            return "dev"
        if auth_settings.email_configured and "@" in contact_value:
            self._send_email(contact_value, code)
            return "email"
        raise AuthError(
            "No email delivery provider is configured for this account.",
            "delivery_not_configured",
            503,
        )

    def _send_email(self, to: str, code: str) -> None:
        import smtplib
        from email.mime.text import MIMEText

        if auth_settings.email_provider == "sendgrid":
            import httpx

            response = httpx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {auth_settings.sendgrid_api_key.get_secret_value()}"},
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": auth_settings.smtp_from},
                    "subject": "Your ETERNIX verification code",
                    "content": [{"type": "text/plain", "value": f"Your ETERNIX verification code is {code}"}],
                },
                timeout=20,
            )
            response.raise_for_status()
            return

        if auth_settings.email_provider == "emailjs":
            try:
                send_emailjs_email(to, code)
            except DeliveryError as exc:
                # Log a redacted diagnostic.  The message
                # never contains the code or any credential.
                logger.warning(
                    "Verification email delivery failed via EmailJS for %s: %s",
                    self._mask_contact(to),
                    exc,
                )
                raise AuthError(
                    "The verification email could not be sent. Please try again.",
                    "delivery_failed",
                    502,
                ) from exc
            return

        message = MIMEText(f"Your ETERNIX verification code is {code}")
        message["Subject"] = "Your ETERNIX verification code"
        message["From"] = auth_settings.smtp_from
        message["To"] = to
        with smtplib.SMTP(auth_settings.smtp_host, auth_settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if auth_settings.smtp_username:
                smtp.login(auth_settings.smtp_username, auth_settings.smtp_password.get_secret_value())
            smtp.send_message(message)

    def confirm_verification(self, user_id: str, code: str, ip_address: str | None = None) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise AuthError("Account not found", "not_found", 404)
        if user["status"] != AccountStatus.AWAITING_VERIFICATION:
            raise AuthError("Verification is not required at this step", "invalid_state", 409)

        contact = self._primary_contact(user)
        if contact is None:
            raise AuthError("No contact method on record", "no_contact", 409)

        challenge = self.store.get_pending_otp_challenge(contact["value"], OTPPurpose.REGISTRATION)
        if challenge is None:
            raise AuthError("No pending verification challenge. Request a new code.", "no_challenge", 409)
        if challenge["expires_at"] and challenge["expires_at"] < _now():
            self.store.consume_otp_challenge(challenge["id"])
            raise AuthError("Verification code expired. Request a new code.", "expired", 409)

        attempts = challenge["attempts"] + 1
        if attempts > challenge["max_attempts"]:
            self.store.consume_otp_challenge(challenge["id"])
            raise AuthError("Too many failed attempts. Request a new code.", "max_attempts", 429)

        if hash_token(code) != challenge["code_hash"]:
            self.store.increment_otp_attempts(challenge["id"])
            self.store.record_audit_event(
                event_type="verification_failed",
                actor_id=user_id,
                outcome="failure",
                ip_address=ip_address,
            )
            raise AuthError("Incorrect verification code.", "invalid_code", 400)

        self.store.consume_otp_challenge(challenge["id"])
        self.store.mark_contact_verified(contact["id"])
        user = self.store.update_user(user_id, status=AccountStatus.AWAITING_PAYMENT_METHOD)
        self.store.record_audit_event(
            event_type="verification_completed",
            actor_id=user_id,
            outcome="success",
            ip_address=ip_address,
        )
        return self._issue_session_payload(user)

    # ------------------------------------------------------------------
    # Payment method registration
    # ------------------------------------------------------------------

    def payment_status(self) -> dict[str, Any]:
        return payment_provider_status()

    def create_payment_setup(self, user_id: str) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise AuthError("Account not found", "not_found", 404)
        if user["status"] not in (
            AccountStatus.AWAITING_PAYMENT_METHOD,
            AccountStatus.PAYMENT_INELIGIBLE,
        ):
            raise AuthError("Payment setup is not required at this step", "invalid_state", 409)

        try:
            provider = get_payment_provider()
            session: SetupSession = provider.create_setup_session(user_id)
        except PaymentProviderError as exc:
            raise AuthError(str(exc), "payment_not_configured", 503) from exc

        self.store.upsert_payment_record(
            user_id,
            provider=PaymentProviderKind(provider.name.upper() if provider.name != "sandbox" else "sandbox"),
            eligibility=PaymentEligibility.PENDING,
            metadata={"setup_id": session.setup_id},
        )
        return {
            "provider": provider.name,
            "setup_id": session.setup_id,
            "status": session.status,
            "url": session.url,
            "client_secret": session.client_secret,
            "sandbox": provider.name == "sandbox",
        }

    def confirm_payment_setup(self, user_id: str, setup_id: str) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise AuthError("Account not found", "not_found", 404)
        if user["status"] not in (
            AccountStatus.AWAITING_PAYMENT_METHOD,
            AccountStatus.PAYMENT_INELIGIBLE,
        ):
            raise AuthError("Payment setup is not required at this step", "invalid_state", 409)

        try:
            provider = get_payment_provider()
            verified = provider.verify_setup(setup_id, user_id)
            session = provider.confirm_setup(setup_id, user_id)
        except PaymentProviderError as exc:
            raise AuthError(str(exc), "payment_not_configured", 503) from exc

        if not verified:
            self.store.upsert_payment_record(
                user_id,
                provider=PaymentProviderKind.SANDBOX if provider.name == "sandbox" else PaymentProviderKind.STRIPE,
                eligibility=PaymentEligibility.INELIGIBLE,
                metadata={"setup_id": setup_id, "status": session.status},
            )
            user = self.store.update_user(user_id, status=AccountStatus.PAYMENT_INELIGIBLE)
            self.store.record_audit_event(
                event_type="payment_method_rejected",
                actor_id=user_id,
                outcome="failure",
                metadata={"provider": provider.name},
            )
            raise AuthError(
                "The payment method could not be confirmed. Try again or use a different method.",
                "payment_failed",
                400,
            )

        self.store.upsert_payment_record(
            user_id,
            provider=PaymentProviderKind.SANDBOX if provider.name == "sandbox" else PaymentProviderKind.STRIPE,
            provider_payment_method_ref=setup_id,
            eligibility=PaymentEligibility.ELIGIBLE,
            metadata={"setup_id": setup_id, "status": session.status},
        )
        self.store.grant_entitlement(user_id, entitlement="paid", source="payment_registration")
        # All prerequisites (identity, credentials, verification,
        # payment eligibility) are now satisfied.
        user = self.store.update_user(user_id, status=AccountStatus.ACTIVE)
        self.store.record_audit_event(
            event_type="payment_eligibility_granted",
            actor_id=user_id,
            outcome="success",
            metadata={"provider": provider.name, "sandbox": provider.name == "sandbox"},
        )
        self.store.record_audit_event(event_type="account_activated", actor_id=user_id, outcome="success")
        return self._issue_session_payload(user)

    # ------------------------------------------------------------------
    # Login / sessions
    # ------------------------------------------------------------------

    def login(self, username: str, password: str, ip_address: str | None = None, user_agent: str | None = None) -> dict[str, Any]:
        normalized = self.normalize_username(username)
        # Only failed attempts consume the rate-limit budget;
        # successful logins never contribute to lockout.
        if not _check_rate_limit(f"login:{normalized}", auth_settings.login_max_attempts, 900, record=False):
            raise AuthError("Too many failed attempts. Try again in 15 minutes.", "rate_limited", 429)

        user = self.store.get_user_by_username(normalized)
        if user is None or not user.get("password_hash"):
            _check_rate_limit(f"login:{normalized}", auth_settings.login_max_attempts, 900)
            self.store.record_audit_event(
                event_type="login_failed",
                outcome="failure",
                ip_address=ip_address,
                user_agent=user_agent,
                detail="unknown user",
            )
            raise AuthError("Invalid username or password.", "invalid_credentials", 401)

        if user["locked_until"] and user["locked_until"] > _now():
            raise AuthError("Account is temporarily locked due to failed attempts.", "locked", 423)

        if not verify_password(password, user["password_hash"] or ""):
            _check_rate_limit(f"login:{normalized}", auth_settings.login_max_attempts, 900)
            count = (user["failed_login_count"] or 0) + 1
            locked_until = None
            if count >= auth_settings.login_max_attempts:
                locked_until = _now() + timedelta(seconds=auth_settings.login_lockout_seconds)
            self.store.update_user(
                user["id"],
                failed_login_count=count,
                locked_until=locked_until,
            )
            self.store.record_audit_event(
                event_type="login_failed",
                actor_id=user["id"],
                outcome="failure",
                ip_address=ip_address,
                user_agent=user_agent,
                detail="bad password",
            )
            raise AuthError("Invalid username or password.", "invalid_credentials", 401)

        updates: dict[str, Any] = {"failed_login_count": 0, "locked_until": None, "last_login_at": _now()}
        if needs_rehash(user["password_hash"] or ""):
            updates["password_hash"] = hash_password(password)
        user = self.store.update_user(user["id"], **updates)
        self.store.record_audit_event(
            event_type="login_succeeded",
            actor_id=user["id"],
            outcome="success",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return self._issue_session_payload(user)

    def _issue_session_payload(self, user: dict[str, Any]) -> dict[str, Any]:
        purpose = "access" if user["status"] == AccountStatus.ACTIVE else "onboarding"
        expires_at = _now() + timedelta(seconds=auth_settings.session_ttl_seconds)
        session = self.store.create_session(
            user_id=user["id"],
            token_hash=hash_token(generate_opaque_token()),
            expires_at=expires_at,
        )
        raw_refresh = generate_opaque_token()
        refresh_expires = _now() + timedelta(seconds=auth_settings.refresh_token_ttl_seconds)
        self.store.create_refresh_credential(
            user_id=user["id"],
            session_id=session["id"],
            token_hash=hash_token(raw_refresh),
            expires_at=refresh_expires,
        )
        access_token = create_access_token(
            user["id"],
            lifetime_seconds=auth_settings.access_token_ttl_seconds,
            extra_claims={"sid": session["id"], "purpose": purpose},
        )
        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "Bearer",
            "expires_in": auth_settings.access_token_ttl_seconds,
            "session_id": session["id"],
            "session_purpose": purpose,
            "user": self.user_profile(user),
        }

    def user_profile(self, user: dict[str, Any] | None = None, user_id: str | None = None) -> dict[str, Any]:
        if user is None:
            user = self.store.get_user(user_id or "")
        if user is None:
            raise AuthError("Account not found", "not_found", 404)
        payment = self.store.get_payment_record(user["id"])
        return {
            "id": user["id"],
            "username": user["username"],
            "email": self._primary_email(user),
            "account_state": user["status"].value if isinstance(user["status"], AccountStatus) else user["status"],
            "payment_eligibility": (
                payment["eligibility"].value if payment and isinstance(payment["eligibility"], PaymentEligibility) else PaymentEligibility.UNKNOWN.value
            ),
            "identities": [
                {
                    "provider": i["provider"].value if isinstance(i["provider"], IdentityProvider) else i["provider"],
                    "subject": i["provider_subject"],
                    "verified": i["verified_at"] is not None,
                }
                for i in self.store.identities_for_user(user["id"])
            ],
            "created_at": user["created_at"].isoformat() if user["created_at"] else None,
            "last_login_at": user["last_login_at"].isoformat() if user["last_login_at"] else None,
            "required_steps": self.required_steps(user),
        }

    def required_steps(self, user: dict[str, Any]) -> list[str]:
        steps: list[str] = []
        status = user["status"]
        if status == AccountStatus.ACTIVE:
            return [RegistrationStep.COMPLETE.value]
        if not self.store.identities_for_user(user["id"]):
            steps.append(RegistrationStep.GOOGLE_IDENTITY.value)
        if not user.get("username") or not user.get("password_hash"):
            steps.append(RegistrationStep.USERNAME_PASSWORD.value)
        if status in (AccountStatus.REGISTRATION_INCOMPLETE, AccountStatus.AWAITING_VERIFICATION):
            steps.append(RegistrationStep.CONTACT_VERIFICATION.value)
        if status in (
            AccountStatus.REGISTRATION_INCOMPLETE,
            AccountStatus.AWAITING_VERIFICATION,
            AccountStatus.AWAITING_PAYMENT_METHOD,
            AccountStatus.PAYMENT_INELIGIBLE,
        ):
            steps.append(RegistrationStep.PAYMENT_METHOD.value)
        return steps

    def current_account(self, user_id: str) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise AuthError("Account not found", "not_found", 404)
        profile = self.user_profile(user)
        profile["onboarding_required"] = user["status"] != AccountStatus.ACTIVE
        return profile

    # ------------------------------------------------------------------
    # Token refresh with rotation and reuse detection
    # ------------------------------------------------------------------

    def refresh(self, raw_refresh_token: str, ip_address: str | None = None) -> dict[str, Any]:
        token_hash = hash_token(raw_refresh_token)
        record = self.store.get_refresh_credential_by_hash(token_hash)

        if record is None:
            # A rotated-away credential presented again is reuse.
            rotated = self.store.get_refresh_credential_by_previous_hash(token_hash)
            if rotated is not None:
                self.store.revoke_all_user_sessions(rotated["user_id"])
                self.store.revoke_all_user_refresh_credentials(rotated["user_id"])
                self.store.record_audit_event(
                    event_type="refresh_reuse_detected",
                    actor_id=rotated["user_id"],
                    outcome="failure",
                    ip_address=ip_address,
                    detail="rotated refresh credential presented again",
                )
                raise AuthError(
                    "Refresh credential reuse detected. All sessions were revoked.",
                    "reuse_detected",
                    401,
                )
            raise AuthError("Invalid refresh credential.", "invalid_token", 401)

        if record["revoked"]:
            raise AuthError("Refresh credential revoked.", "revoked", 401)
        if record["expires_at"] and record["expires_at"] < _now():
            raise AuthError("Refresh credential expired.", "expired", 401)

        session = self.store.get_session(record["session_id"])
        user = self.store.get_user(record["user_id"])
        if session is None or user is None or session["revoked"]:
            raise AuthError("Session is no longer valid.", "invalid_session", 401)
        if session["expires_at"] and session["expires_at"] < _now():
            raise AuthError("Session expired.", "expired", 401)

        # Rotate: the same credential row carries the new hash.
        new_raw = generate_opaque_token()
        new_expires = _now() + timedelta(seconds=auth_settings.refresh_token_ttl_seconds)
        self.store.rotate_refresh_credential(record["id"], hash_token(new_raw), new_expires)

        purpose = "access" if user["status"] == AccountStatus.ACTIVE else "onboarding"
        access_token = create_access_token(
            user["id"],
            lifetime_seconds=auth_settings.access_token_ttl_seconds,
            extra_claims={"sid": session["id"], "purpose": purpose},
        )
        self.store.touch_session(session["id"])
        return {
            "access_token": access_token,
            "refresh_token": new_raw,
            "token_type": "Bearer",
            "expires_in": auth_settings.access_token_ttl_seconds,
            "session_id": session["id"],
            "session_purpose": purpose,
        }

    # ------------------------------------------------------------------
    # Logout / revocation
    # ------------------------------------------------------------------

    def logout(self, user_id: str, session_id: str, refresh_token: str | None = None) -> None:
        self.store.revoke_session(session_id)
        self.store.revoke_refresh_credentials_for_session(session_id)
        if refresh_token:
            record = self.store.get_refresh_credential_by_hash(hash_token(refresh_token))
            if record:
                self.store.revoke_refresh_credential(record["id"])
        self.store.record_audit_event(event_type="logout", actor_id=user_id, outcome="success")

    def global_logout(self, user_id: str) -> None:
        self.store.revoke_all_user_sessions(user_id)
        self.store.revoke_all_user_refresh_credentials(user_id)
        self.store.record_audit_event(event_type="global_logout", actor_id=user_id, outcome="success")

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        # Session listing requires a purpose column; expose the
        # persisted session records without token material.
        with self.store.session() as s:
            from eternix.auth.store import SessionORM

            rows = s.scalars(
                __import__("sqlalchemy").select(SessionORM).where(SessionORM.user_id == user_id)
            ).all()
            return [
                {
                    "id": r.id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "last_active_at": r.last_active_at.isoformat() if r.last_active_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "ip_address": r.ip_address,
                    "user_agent": r.user_agent,
                    "revoked": bool(r.revoked),
                }
                for r in rows
            ]

    def revoke_session(self, user_id: str, session_id: str) -> bool:
        session = self.store.get_session(session_id)
        if session is None or session["user_id"] != user_id:
            raise AuthError("Session not found", "not_found", 404)
        self.store.revoke_session(session_id)
        self.store.revoke_refresh_credentials_for_session(session_id)
        self.store.record_audit_event(
            event_type="session_revoked",
            actor_id=user_id,
            target_id=session_id,
            outcome="success",
        )
        return True

    # ------------------------------------------------------------------
    # Password change / recovery
    # ------------------------------------------------------------------

    def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        user = self.store.get_user(user_id)
        if user is None or not user.get("password_hash"):
            raise AuthError("Account not found", "not_found", 404)
        if not verify_password(current_password, user["password_hash"] or ""):
            self.store.record_audit_event(
                event_type="password_change_failed",
                actor_id=user_id,
                outcome="failure",
                detail="current password incorrect",
            )
            raise AuthError("Current password is incorrect.", "invalid_credentials", 401)
        policy_error = password_policy_error(new_password)
        if policy_error:
            raise AuthError(policy_error, "weak_password", 400)
        if is_common_password(new_password):
            raise AuthError("This password is too common. Choose a stronger password.", "weak_password", 400)
        self.store.update_user(user_id, password_hash=hash_password(new_password))
        self.store.revoke_all_user_sessions(user_id)
        self.store.revoke_all_user_refresh_credentials(user_id)
        self.store.record_audit_event(event_type="password_changed", actor_id=user_id, outcome="success")

    def request_password_reset(self, username: str, ip_address: str | None = None) -> dict[str, Any]:
        # Generic response to avoid account enumeration.
        user = self.store.get_user_by_username(self.normalize_username(username or ""))
        if user is None or not user.get("username"):
            return {"status": "if_the_account_exists_a_reset_was_requested"}

        contact = self._primary_contact(user)
        if contact is None or contact["verification_status"].value != "verified":
            return {"status": "if_the_account_exists_a_reset_was_requested"}

        if not _check_rate_limit(f"reset:{user['id']}", 5, 3600):
            raise AuthError("Too many reset requests. Try again later.", "rate_limited", 429)

        raw = generate_opaque_token()
        self.store.create_password_reset_challenge(
            user_id=user["id"],
            contact_value=contact["value"],
            channel=OTPChannel.EMAIL if "@" in contact["value"] else OTPChannel.PHONE,
            code_hash=hash_token(raw),
            max_attempts=auth_settings.otp_max_attempts,
            expires_at=_now() + timedelta(seconds=auth_settings.otp_expiry_seconds * 12),
        )
        delivery = self._deliver_otp(contact["value"], raw)
        self.store.record_audit_event(
            event_type="password_reset_requested",
            actor_id=user["id"],
            outcome="success" if delivery != "failed" else "failure",
            ip_address=ip_address,
        )
        return {
            "status": "if_the_account_exists_a_reset_was_requested",
            "delivery": delivery,
            "dev_code": raw if delivery == "dev" else None,
        }

    def reset_password(self, token: str, new_password: str) -> dict[str, Any]:
        token_hash = hash_token(token)
        # Find the pending reset challenge matching this token hash.
        from eternix.auth.store import PasswordResetChallengeORM

        with self.store.session() as s:
            orm = s.scalars(
                __import__("sqlalchemy").select(PasswordResetChallengeORM).where(
                    PasswordResetChallengeORM.code_hash == token_hash,
                    PasswordResetChallengeORM.consumed == False,
                )
            ).first()
            if orm is None or (orm.expires_at and _as_utc(orm.expires_at) < _now()):
                raise AuthError("Invalid or expired recovery token.", "invalid_token", 400)
            user = self.store.get_user(orm.user_id)
            if user is None:
                raise AuthError("Account not found", "not_found", 404)

            policy_error = password_policy_error(new_password)
            if policy_error:
                raise AuthError(policy_error, "weak_password", 400)
            if is_common_password(new_password):
                raise AuthError("This password is too common. Choose a stronger password.", "weak_password", 400)

            self.store.consume_password_reset_challenge(orm.id)
            self.store.update_user(
                user["id"],
                password_hash=hash_password(new_password),
                failed_login_count=0,
                locked_until=None,
            )
            self.store.revoke_all_user_sessions(user["id"])
            self.store.revoke_all_user_refresh_credentials(user["id"])
            self.store.record_audit_event(
                event_type="password_reset_completed",
                actor_id=user["id"],
                outcome="success",
            )
        return {"status": "password_reset"}

    # ------------------------------------------------------------------
    # Identity linking / unlinking
    # ------------------------------------------------------------------

    async def link_google_identity(self, user_id: str, state: str, code: str, redirect_uri: str) -> dict[str, Any]:
        attempt = self.store.consume_registration_attempt(state)
        if attempt is None:
            raise AuthError("Invalid, expired, or already-used OAuth state", "invalid_state", 400)
        try:
            tokens = await self._google_client.exchange_code(code, attempt["code_verifier"])
            claims = await self._google_client.validate_id_token(
                tokens.get("id_token", ""),
                expected_nonce=attempt["nonce"],
            )
        except OAuthError as exc:
            raise AuthError(str(exc), "identity_validation_failed", 400) from exc

        subject = claims.get("sub")
        if self.store.get_identity_by_subject(IdentityProvider.GOOGLE, subject):
            raise AuthError(
                "This Google account is already linked to another ETERNIX account.",
                "identity_in_use",
                409,
            )

        user = self.store.get_user(user_id)
        if user is None:
            raise AuthError("Account not found", "not_found", 404)

        self.store.link_identity(user_id, IdentityProvider.GOOGLE, subject, verified=True)
        self.store.update_user(user_id, google_linked=True)
        if claims.get("email"):
            self._ensure_contact(
                user_id,
                claims["email"],
                verified=bool(claims.get("email_verified")),
            )
        self.store.record_audit_event(
            event_type="identity_linked",
            actor_id=user_id,
            outcome="success",
            metadata={"provider": "google"},
        )
        return {"status": "linked", "provider": "google"}

    def unlink_google_identity(self, user_id: str) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise AuthError("Account not found", "not_found", 404)
        identities = self.store.identities_for_user(user_id)
        google_identity = next(
            (i for i in identities if i["provider"] == IdentityProvider.GOOGLE),
            None,
        )
        if google_identity is None:
            raise AuthError("No Google identity is linked.", "not_found", 404)

        # Prevent removal of the only usable identity method unless
        # the account has a password credential (recovery route exists).
        if len(identities) == 1 and not user.get("password_hash"):
            raise AuthError(
                "This is the only sign-in method. Set a password first or contact support.",
                "last_identity",
                409,
            )

        self.store.unlink_identity(google_identity["id"])
        self.store.update_user(user_id, google_linked=False)
        self.store.record_audit_event(
            event_type="identity_unlinked",
            actor_id=user_id,
            outcome="success",
            metadata={"provider": "google"},
        )
        return {"status": "unlinked", "provider": "google"}

    # ------------------------------------------------------------------
    # Account administration
    # ------------------------------------------------------------------

    def set_account_state(self, actor_id: str, target_user_id: str, new_state: str) -> dict[str, Any]:
        allowed = {s.value for s in AccountStatus}
        if new_state not in allowed:
            raise AuthError(f"Unknown account state: {new_state}", "invalid_state", 400)
        target = self.store.get_user(target_user_id)
        if target is None:
            raise AuthError("Account not found", "not_found", 404)
        self.store.update_user(target_user_id, status=AccountStatus(new_state))
        self.store.record_audit_event(
            event_type="account_state_changed",
            actor_id=actor_id,
            target_id=target_user_id,
            outcome="success",
            metadata={"new_state": new_state},
        )
        if new_state in (AccountStatus.SUSPENDED.value, AccountStatus.DISABLED.value):
            self.store.revoke_all_user_sessions(target_user_id)
            self.store.revoke_all_user_refresh_credentials(target_user_id)
        return {"status": "updated", "account_state": new_state}

    def delete_account(self, user_id: str) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise AuthError("Account not found", "not_found", 404)
        self.store.revoke_all_user_sessions(user_id)
        self.store.revoke_all_user_refresh_credentials(user_id)
        self.store.update_user(
            user_id,
            status=AccountStatus.DELETION_PENDING,
            username="",
            password_hash="",
        )
        self.store.record_audit_event(
            event_type="account_deletion_requested",
            actor_id=user_id,
            outcome="success",
        )
        return {"status": "deletion_pending"}

    # ------------------------------------------------------------------
    # Security events
    # ------------------------------------------------------------------

    def audit_events(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        events = self.store.audit_events_for_user(user_id, limit=min(max(limit, 1), 200))
        return [
            {
                "id": e["id"],
                "event_type": e["event_type"],
                "outcome": e["outcome"],
                "detail": e.get("detail", ""),
                "metadata": e.get("metadata", {}),
                "created_at": e["created_at"].isoformat() if e.get("created_at") else None,
            }
            for e in events
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_email(email: str) -> str:
        return (email or "").strip().lower()

    def _primary_contact(self, user: dict[str, Any]) -> dict[str, Any] | None:
        contacts = self.store.contacts_for_user(user["id"])
        for contact in contacts:
            if contact["is_primary"]:
                return contact
        return contacts[0] if contacts else None

    def _primary_email(self, user: dict[str, Any]) -> str | None:
        contact = self._primary_contact(user)
        if contact and contact["type"] == ContactType.EMAIL:
            return contact["value"]
        return None

    def _ensure_contact(self, user_id: str, email: str, verified: bool = False) -> dict[str, Any] | None:
        email = self.normalize_email(email)
        if not email:
            return None
        contacts = self.store.contacts_for_user(user_id)
        for contact in contacts:
            if contact["value"] == email:
                if verified and contact["verification_status"] != ContactVerificationStatus.VERIFIED:
                    self.store.mark_contact_verified(contact["id"])
                    return self.store.get_contact(contact["id"])
                return contact
        contact = self.store.add_contact(user_id, ContactType.EMAIL, email, is_primary=True)
        if verified:
            self.store.mark_contact_verified(contact["id"])
            contact = self.store.get_contact(contact["id"])
        return contact

    def _record_login(self, user: dict[str, Any], email: str | None) -> None:
        if email:
            self._ensure_contact(user["id"], email, verified=True)
        self.store.update_user(user["id"], last_login_at=_now())

    @staticmethod
    def _mask_contact(value: str) -> str:
        if "@" in value:
            local, domain = value.split("@", 1)
            masked_local = local[:1] + "***" if len(local) > 1 else "***"
            return f"{masked_local}@{domain}"
        return "***" + value[-2:] if len(value) > 2 else "***"
