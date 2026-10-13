"""Authentication configuration.

All secrets come from environment variables (prefix
``ETERNIX_AUTH_``).  In production, missing or insecure defaults
cause the application to refuse to start auth features rather than
silently operating in an insecure mode.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ETERNIX_AUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Mode ---
    # "production" requires real delivery providers and explicit
    # secrets.  "development" allows local conveniences that are
    # disabled in production.
    mode: str = "development"

    # --- Database ---
    auth_db_path: Path = Field(default=REPO_ROOT / "data" / "auth.db")

    # --- Session cookie ---
    session_cookie_name: str = "eternix_session"
    session_ttl_seconds: int = 14 * 24 * 3600  # 14 days
    session_renewal_seconds: int = 24 * 3600  # renew if older than 1 day
    session_same_site: str = "lax"
    session_secure: bool = False
    session_http_only: bool = True
    # Server-side session signer secret (production secret).
    session_signing_key: SecretStr = SecretStr("")

    # --- OTP delivery ---
    otp_length: int = 6
    otp_expiry_seconds: int = 300  # 5 minutes
    otp_max_attempts: int = 5
    otp_request_cooldown_seconds: int = 60
    otp_max_requests_per_hour: int = 10

    # --- Email verification tuning ---
    # Alternative names for the OTP settings above, accepted
    # for configuration convenience.  When set they override
    # the corresponding OTP defaults.
    email_verification_code_ttl_minutes: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ETERNIX_AUTH_EMAIL_VERIFICATION_CODE_TTL_MINUTES",
            "EMAIL_VERIFICATION_CODE_TTL_MINUTES",
        ),
    )
    email_verification_max_attempts: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ETERNIX_AUTH_EMAIL_VERIFICATION_MAX_ATTEMPTS",
            "EMAIL_VERIFICATION_MAX_ATTEMPTS",
        ),
    )
    email_verification_resend_cooldown_seconds: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ETERNIX_AUTH_EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS",
            "EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS",
        ),
    )

    # --- Email (SMTP / SendGrid / EmailJS) ---
    email_provider: str = "none"  # "smtp" | "sendgrid" | "emailjs" | "none"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "noreply@eternix.local"
    sendgrid_api_key: SecretStr = SecretStr("")

    # --- EmailJS (server-side email delivery) ---
    # Template IDs are opaque identifiers issued by the
    # EmailJS dashboard (they look like "template_xxxx").
    # They must never be invented or replaced by a template
    # name; an unset template ID means email delivery is
    # not configured.
    emailjs_service_id: str = Field(
        default="service_5i21ybi",
        validation_alias=AliasChoices(
            "ETERNIX_AUTH_EMAILJS_SERVICE_ID", "EMAILJS_SERVICE_ID"
        ),
    )
    emailjs_template_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ETERNIX_AUTH_EMAILJS_TEMPLATE_ID", "EMAILJS_TEMPLATE_ID"
        ),
    )
    emailjs_public_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ETERNIX_AUTH_EMAILJS_PUBLIC_KEY", "EMAILJS_PUBLIC_KEY"
        ),
    )
    emailjs_private_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "ETERNIX_AUTH_EMAILJS_PRIVATE_KEY", "EMAILJS_PRIVATE_KEY"
        ),
    )
    emailjs_reply_to: str = ""

    # --- SMS (Twilio) ---
    sms_provider: str = "none"  # "twilio" | "none"
    twilio_account_sid: str = ""
    twilio_auth_token: SecretStr = SecretStr("")
    twilio_from_number: str = ""

    # --- Google OAuth / OIDC ---
    # Client credentials come from the environment.  Empty values
    # mean the Google provider is not configured and the flow is
    # disabled with a truthful "not configured" response.
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = "http://127.0.0.1:8080/auth/google/callback"
    google_scopes: str = "openid email profile"

    # --- JWT access tokens ---
    # Short-lived access tokens (documented default: 5 minutes).
    jwt_algorithm: str = "HS256"
    jwt_allowed_algorithms: str = "HS256"
    access_token_ttl_seconds: int = 300
    jwt_issuer: str = "eternix"
    jwt_audience: str = "eternix-api"
    jwt_signing_key: SecretStr = SecretStr("")

    # --- Refresh credentials ---
    # Opaque, cryptographically random refresh credentials with a
    # 14-day lifetime and server-side rotation.
    refresh_token_ttl_seconds: int = 14 * 24 * 3600  # 14 days
    refresh_token_bytes: int = 48

    # --- Payment provider ---
    # "stripe" | "sandbox" | "none".
    # "sandbox" is a development-only provider that never charges
    # real money.  Production requires a real provider (stripe)
    # with valid credentials.
    payment_provider: str = "none"
    stripe_secret_key: SecretStr = SecretStr("")
    stripe_publishable_key: str = ""
    stripe_webhook_secret: SecretStr = SecretStr("")
    stripe_api_base: str = "https://api.stripe.com/v1"

    # --- Password ---
    password_min_length: int = 8
    password_require_digit: bool = True
    password_require_uppercase: bool = True
    password_require_lowercase: bool = True
    password_require_special: bool = False
    argon2_time_cost: int = 2
    argon2_memory_cost: int = 65536  # 64 MiB
    argon2_parallelism: int = 1
    argon2_hash_len: int = 32
    argon2_salt_len: int = 16

    # --- Rate limiting ---
    login_max_attempts: int = 5
    login_lockout_seconds: int = 900  # 15 minutes
    registration_rate_limit: int = 5  # per hour per IP

    # --- Username ---
    username_min_length: int = 3
    username_max_length: int = 32
    username_pattern: str = r"^[a-zA-Z0-9_]+$"

    # --- Origins ---
    allowed_origins: str = "http://127.0.0.1:8080,http://localhost:8080"

    # --- Development-only OTP ---
    # Only used when mode == "development" and explicitly set.
    dev_otp: str = ""

    # --- Entitlement ---
    # There is deliberately no free-access tier.
    default_entitlement: str = "paid"

    @model_validator(mode="after")
    def _apply_email_verification_settings(self) -> AuthSettings:
        """Apply the email-verification alias settings, when set."""
        if self.email_verification_code_ttl_minutes is not None:
            self.otp_expiry_seconds = self.email_verification_code_ttl_minutes * 60
        if self.email_verification_max_attempts is not None:
            self.otp_max_attempts = self.email_verification_max_attempts
        if self.email_verification_resend_cooldown_seconds is not None:
            self.otp_request_cooldown_seconds = self.email_verification_resend_cooldown_seconds
        return self

    @property
    def is_production(self) -> bool:
        return self.mode.lower() == "production"

    @property
    def emailjs_configured(self) -> bool:
        values = (self.emailjs_service_id, self.emailjs_template_id, self.emailjs_public_key)
        # Placeholder values ("<paste ...>") are not credentials.
        return all(v and not (v.startswith("<") and v.endswith(">")) for v in values)

    @property
    def email_configured(self) -> bool:
        if self.email_provider == "emailjs":
            return self.emailjs_configured
        return self.email_provider != "none" and (
            (self.email_provider == "smtp" and self.smtp_from)
            or (self.email_provider == "sendgrid" and bool(self.sendgrid_api_key.get_secret_value()))
        )

    @property
    def sms_configured(self) -> bool:
        return self.sms_provider != "none" and bool(self.twilio_from_number)

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id) and bool(
            self.google_client_secret.get_secret_value()
        )

    @property
    def payment_provider_kind(self) -> str:
        return self.payment_provider

    @property
    def payment_provider_configured(self) -> bool:
        if self.payment_provider == "sandbox":
            # Sandbox is only a development convenience.
            return not self.is_production
        if self.payment_provider == "stripe":
            return bool(self.stripe_secret_key.get_secret_value())
        return False

    @property
    def stripe_configured(self) -> bool:
        return self.payment_provider == "stripe" and bool(
            self.stripe_secret_key.get_secret_value()
        )

    @property
    def dev_otp_enabled(self) -> bool:
        return (not self.is_production) and bool(self.dev_otp)

    def require_production_secrets(self) -> None:
        """Raise if production mode is misconfigured."""
        if not self.is_production:
            return
        if not self.jwt_signing_key.get_secret_value():
            raise RuntimeError("ETERNIX_AUTH_JWT_KEY must be set in production mode")
        if not self.session_signing_key.get_secret_value():
            raise RuntimeError("ETERNIX_AUTH_SESSION_KEY must be set in production mode")
        if not self.google_configured:
            raise RuntimeError("Google OAuth credentials must be configured in production mode")
        if not self.stripe_configured:
            raise RuntimeError("A real payment provider (stripe) must be configured in production mode")
        if not self.email_configured and not self.sms_configured:
            raise RuntimeError(
                "At least one OTP delivery provider (email or SMS) must be "
                "configured in production mode"
            )


auth_settings = AuthSettings()


def ensure_auth_dirs() -> None:
    auth_settings.auth_db_path.parent.mkdir(parents=True, exist_ok=True)
