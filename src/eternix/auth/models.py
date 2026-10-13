"""Authentication data models (Pydantic) and account-state enumerations.

These models describe the API-facing shape of authentication records.  The
persistence layer (``eternix.auth.store``) owns the corresponding SQLAlchemy
ORM objects.  Nothing in this module performs I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AccountStatus(str, Enum):
    """Lifecycle state of an ETERNIX account.

    The registration state machine (see ``AuthService``) transitions accounts
    through these states.  An account may only access protected resources when
    it is ``ACTIVE``.
    """

    REGISTRATION_INCOMPLETE = "registration_incomplete"
    AWAITING_VERIFICATION = "awaiting_verification"
    AWAITING_PAYMENT_METHOD = "awaiting_payment_method"
    ACTIVE = "active"
    PAYMENT_INELIGIBLE = "payment_ineligible"
    SUSPENDED = "suspended"
    DISABLED = "disabled"
    DELETION_PENDING = "deletion_pending"


class RegistrationStep(str, Enum):
    """Ordered steps of the mandatory registration flow."""

    GOOGLE_IDENTITY = "google_identity"
    USERNAME_PASSWORD = "username_password"
    CONTACT_VERIFICATION = "contact_verification"
    PAYMENT_METHOD = "payment_method"
    COMPLETE = "complete"


class IdentityProvider(str, Enum):
    GOOGLE = "google"
    ETERNIX = "eternix"
    DEV = "dev"  # development-only, never available in production


class ContactType(str, Enum):
    EMAIL = "email"
    PHONE = "phone"


class ContactVerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class Entitlement(str, Enum):
    """Entitlement kinds.  There is deliberately no free-access tier."""

    PAID = "paid"


class OTPChannel(str, Enum):
    EMAIL = "email"
    PHONE = "phone"


class OTPPurpose(str, Enum):
    REGISTRATION = "registration"
    PASSWORD_RESET = "password_reset"


class PaymentEligibility(str, Enum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NOT_CONFIGURED = "not_configured"


class PaymentProviderKind(str, Enum):
    STRIPE = "stripe"
    SANDBOX = "sandbox"
    NONE = "none"


class SecurityEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str | None = None
    event_type: str
    ip_address: str | None = None
    user_agent: str | None = None
    success: bool = True
    detail: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class User(BaseModel):
    id: str
    username: str
    password_hash: str = ""
    status: AccountStatus = AccountStatus.REGISTRATION_INCOMPLETE
    entitlement: str = Entitlement.PAID.value
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    last_login_at: datetime | None = None
    failed_login_count: int = 0
    locked_until: datetime | None = None
    google_linked: bool = False


class ExternalIdentity(BaseModel):
    id: str
    user_id: str
    provider: IdentityProvider
    provider_subject: str
    verified_at: datetime | None = None
    linked_at: datetime = Field(default_factory=_utcnow)
    created_at: datetime = Field(default_factory=_utcnow)


class ContactMethod(BaseModel):
    id: str
    user_id: str | None = None
    type: ContactType
    value: str
    verified: bool = False
    verification_status: ContactVerificationStatus = ContactVerificationStatus.PENDING
    is_primary: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    verified_at: datetime | None = None


class OTPChallenge(BaseModel):
    id: str
    contact_value: str
    channel: OTPChannel
    purpose: OTPPurpose
    code_hash: str
    attempts: int = 0
    max_attempts: int = 5
    consumed: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None
    ip_address: str | None = None


class PasswordResetChallenge(BaseModel):
    id: str
    user_id: str
    contact_value: str
    channel: OTPChannel
    code_hash: str
    attempts: int = 0
    max_attempts: int = 5
    consumed: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None


class Session(BaseModel):
    id: str
    user_id: str
    token_hash: str
    created_at: datetime = Field(default_factory=_utcnow)
    last_active_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    revoked: bool = False


class RefreshCredential(BaseModel):
    id: str
    user_id: str
    session_id: str
    token_hash: str
    previous_token_hash: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None
    revoked: bool = False
    rotated_at: datetime | None = None


class RecoveryToken(BaseModel):
    id: str
    user_id: str
    token_hash: str
    purpose: str
    expires_at: datetime | None = None
    consumed: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class PaymentRecord(BaseModel):
    id: str
    user_id: str
    provider: PaymentProviderKind
    provider_customer_ref: str = ""
    provider_payment_method_ref: str = ""
    eligibility: PaymentEligibility = PaymentEligibility.UNKNOWN
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class EntitlementRecord(BaseModel):
    id: str
    user_id: str
    entitlement: str = Entitlement.PAID.value
    granted_at: datetime = Field(default_factory=_utcnow)
    source: str = "registration"
    metadata: dict[str, Any] = Field(default_factory=dict)
