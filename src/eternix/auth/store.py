"""Authentication persistence layer.

``AuthStore`` owns the SQLAlchemy ORM objects and the dedicated authentication
database (``data/auth.db`` by default).  It is deliberately separate from the
core ``TaskStore`` so authentication data is isolated and can be managed,
backed up, and secured independently.

All mutating operations run inside a transaction and roll back on error.
Uniqueness is enforced at the database level (username, provider+subject) and
not merely in application code.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import declarative_base, sessionmaker

from eternix.auth.config import auth_settings, ensure_auth_dirs
from eternix.auth.models import (
    AccountStatus,
    ContactType,
    ContactVerificationStatus,
    IdentityProvider,
    OTPChannel,
    OTPPurpose,
    PaymentEligibility,
    PaymentProviderKind,
)

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime read from SQLite to aware UTC.

    SQLite DateTime columns do not preserve timezone
    information, so persisted values come back naive. All
    comparisons in the service layer use aware UTC datetimes.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class UserORM(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(Text, default="")
    status = Column(String(40), nullable=False, default=AccountStatus.REGISTRATION_INCOMPLETE.value)
    entitlement = Column(String(40), default="paid")
    google_linked = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow)
    last_login_at = Column(DateTime, nullable=True)
    failed_login_count = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)


class ExternalIdentityORM(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_identity_provider_subject"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(40), nullable=False)
    provider_subject = Column(String(255), nullable=False)
    verified_at = Column(DateTime, nullable=True)
    linked_at = Column(DateTime, nullable=False, default=_utcnow)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class ContactMethodORM(Base):
    __tablename__ = "contact_methods"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    type = Column(String(20), nullable=False)
    value = Column(String(512), nullable=False)
    verification_status = Column(String(20), nullable=False, default=ContactVerificationStatus.PENDING.value)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    verified_at = Column(DateTime, nullable=True)


class OTPChallengeORM(Base):
    __tablename__ = "otp_challenges"

    id = Column(String(36), primary_key=True)
    contact_value = Column(String(512), nullable=False)
    channel = Column(String(20), nullable=False)
    purpose = Column(String(40), nullable=False)
    code_hash = Column(String(128), nullable=False)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    consumed = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    ip_address = Column(String(64), nullable=True)


class PasswordResetChallengeORM(Base):
    __tablename__ = "password_reset_challenges"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    contact_value = Column(String(512), nullable=False)
    channel = Column(String(20), nullable=False)
    code_hash = Column(String(128), nullable=False)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    consumed = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)


class SessionORM(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    last_active_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    revoked = Column(Boolean, default=False)


class RefreshCredentialORM(Base):
    __tablename__ = "refresh_credentials"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, index=True)
    previous_token_hash = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    revoked = Column(Boolean, default=False)
    rotated_at = Column(DateTime, nullable=True)


class RecoveryTokenORM(Base):
    __tablename__ = "recovery_tokens"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, index=True)
    purpose = Column(String(40), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    consumed = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class PaymentRecordORM(Base):
    __tablename__ = "payment_records"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, unique=True, index=True)
    provider = Column(String(40), nullable=False, default=PaymentProviderKind.NONE.value)
    provider_customer_ref = Column(String(255), default="")
    provider_payment_method_ref = Column(String(255), default="")
    eligibility = Column(String(40), nullable=False, default=PaymentEligibility.UNKNOWN.value)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow)


class RegistrationAttemptORM(Base):
    __tablename__ = "registration_attempts"
    __table_args__ = (UniqueConstraint("state", name="uq_registration_state"),)

    id = Column(String(36), primary_key=True)
    state = Column(String(128), unique=True, nullable=False, index=True)
    nonce = Column(String(255), nullable=False)
    code_verifier = Column(String(512), nullable=False)
    provider_subject = Column(String(255), nullable=True)
    user_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=False)


class AuditEventORM(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_actor", "actor_id"),)

    id = Column(String(36), primary_key=True)
    actor_id = Column(String(36), nullable=True)
    target_id = Column(String(36), nullable=True)
    event_type = Column(String(80), nullable=False, index=True)
    outcome = Column(String(20), nullable=False, default="success")
    detail = Column(Text, default="")
    metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class EntitlementRecordORM(Base):
    __tablename__ = "entitlement_records"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    entitlement = Column(String(40), default="paid")
    granted_at = Column(DateTime, nullable=False, default=_utcnow)
    source = Column(String(80), default="registration")
    metadata = Column(JSON, default=dict)


def hash_token(token: str) -> str:
    """Return a stable, non-reversible hash for an opaque token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthStore:
    """Transactional persistence for authentication state."""

    def __init__(self, db_path: str | Path | None = None):
        ensure_auth_dirs()
        path = Path(db_path) if db_path else auth_settings.auth_db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        self.engine = create_engine(f"sqlite:///{path}", echo=False)
        # expire_on_commit=False keeps loaded attributes readable
        # after the transaction commits, so objects serialized
        # outside the session context do not detach-expire.
        self.Session = sessionmaker(
            bind=self.engine, expire_on_commit=False
        )
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self):
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    def create_user(
        self,
        username: str,
        password_hash: str = "",
        status: AccountStatus = AccountStatus.REGISTRATION_INCOMPLETE,
    ) -> dict:
        user_id = str(uuid4())
        with self.session() as s:
            orm = UserORM(
                id=user_id,
                username=username,
                password_hash=password_hash,
                status=status.value,
                entitlement="paid",
            )
            s.add(orm)
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> dict | None:
        with self.session() as s:
            orm = s.get(UserORM, user_id)
            return self._user_dict(orm) if orm else None

    def get_user_by_username(self, username: str) -> dict | None:
        with self.session() as s:
            orm = s.scalars(select(UserORM).where(UserORM.username == username)).first()
            return self._user_dict(orm) if orm else None

    def update_user(self, user_id: str, **fields) -> dict | None:
        with self.session() as s:
            orm = s.get(UserORM, user_id)
            if not orm:
                return None
            for key, value in fields.items():
                if hasattr(orm, key):
                    if key == "status" and isinstance(value, AccountStatus):
                        value = value.value
                    setattr(orm, key, value)
            orm.updated_at = _utcnow()
        return self.get_user(user_id)

    def username_exists(self, username: str) -> bool:
        with self.session() as s:
            return (
                s.scalars(select(UserORM.id).where(UserORM.username == username)).first()
                is not None
            )

    # ------------------------------------------------------------------
    # External identities
    # ------------------------------------------------------------------
    def link_identity(
        self,
        user_id: str,
        provider: IdentityProvider,
        provider_subject: str,
        verified: bool = True,
    ) -> dict:
        identity_id = str(uuid4())
        with self.session() as s:
            orm = ExternalIdentityORM(
                id=identity_id,
                user_id=user_id,
                provider=provider.value,
                provider_subject=provider_subject,
                verified_at=_utcnow() if verified else None,
            )
            s.add(orm)
        return self.get_identity(identity_id)

    def get_identity(self, identity_id: str) -> dict | None:
        with self.session() as s:
            orm = s.get(ExternalIdentityORM, identity_id)
            return self._identity_dict(orm) if orm else None

    def get_identity_by_subject(self, provider: IdentityProvider, subject: str) -> dict | None:
        with self.session() as s:
            orm = s.scalars(
                select(ExternalIdentityORM).where(
                    ExternalIdentityORM.provider == provider.value,
                    ExternalIdentityORM.provider_subject == subject,
                )
            ).first()
            return self._identity_dict(orm) if orm else None

    def identities_for_user(self, user_id: str) -> list[dict]:
        with self.session() as s:
            rows = s.scalars(
                select(ExternalIdentityORM).where(ExternalIdentityORM.user_id == user_id)
            ).all()
            return [self._identity_dict(r) for r in rows]

    def unlink_identity(self, identity_id: str) -> bool:
        with self.session() as s:
            orm = s.get(ExternalIdentityORM, identity_id)
            if not orm:
                return False
            s.delete(orm)
            return True

    # ------------------------------------------------------------------
    # Contact methods
    # ------------------------------------------------------------------
    def add_contact(
        self,
        user_id: str,
        contact_type: ContactType,
        value: str,
        is_primary: bool = True,
    ) -> dict:
        contact_id = str(uuid4())
        with self.session() as s:
            orm = ContactMethodORM(
                id=contact_id,
                user_id=user_id,
                type=contact_type.value,
                value=value,
                verification_status=ContactVerificationStatus.PENDING.value,
                is_primary=is_primary,
            )
            s.add(orm)
        return self.get_contact(contact_id)

    def get_contact(self, contact_id: str) -> dict | None:
        with self.session() as s:
            orm = s.get(ContactMethodORM, contact_id)
            return self._contact_dict(orm) if orm else None

    def contacts_for_user(self, user_id: str) -> list[dict]:
        with self.session() as s:
            rows = s.scalars(
                select(ContactMethodORM).where(ContactMethodORM.user_id == user_id)
            ).all()
            return [self._contact_dict(r) for r in rows]

    def mark_contact_verified(self, contact_id: str) -> dict | None:
        with self.session() as s:
            orm = s.get(ContactMethodORM, contact_id)
            if not orm:
                return None
            orm.verification_status = ContactVerificationStatus.VERIFIED.value
            orm.verified_at = _utcnow()
        return self.get_contact(contact_id)

    def get_contact_by_value(self, value: str) -> dict | None:
        with self.session() as s:
            orm = s.scalars(
                select(ContactMethodORM).where(ContactMethodORM.value == value)
            ).first()
            return self._contact_dict(orm) if orm else None

    # ------------------------------------------------------------------
    # Challenges
    # ------------------------------------------------------------------
    def create_otp_challenge(self, *, contact_value, channel, purpose, code_hash, max_attempts=5, expires_at=None, ip_address=None) -> dict:
        challenge_id = str(uuid4())
        with self.session() as s:
            orm = OTPChallengeORM(
                id=challenge_id,
                contact_value=contact_value,
                channel=channel.value,
                purpose=purpose.value,
                code_hash=code_hash,
                max_attempts=max_attempts,
                expires_at=expires_at,
                ip_address=ip_address,
            )
            s.add(orm)
        return self._otp_dict(orm)

    def get_otp_challenge(self, challenge_id: str) -> dict | None:
        with self.session() as s:
            orm = s.get(OTPChallengeORM, challenge_id)
            return self._otp_dict(orm) if orm else None

    def invalidate_otp_challenges(self, contact_value: str, purpose: OTPPurpose) -> None:
        """Invalidate all pending challenges for a contact and purpose.

        Used when a new code is issued so that only the
        most recently issued code can verify.
        """
        with self.session() as s:
            rows = s.scalars(
                select(OTPChallengeORM).where(
                    OTPChallengeORM.contact_value == contact_value,
                    OTPChallengeORM.purpose == purpose.value,
                    OTPChallengeORM.consumed == False,
                )
            ).all()
            for row in rows:
                row.consumed = True

    def consume_otp_challenge(self, challenge_id: str) -> None:
        with self.session() as s:
            orm = s.get(OTPChallengeORM, challenge_id)
            if orm:
                orm.consumed = True

    def increment_otp_attempts(self, challenge_id: str) -> None:
        with self.session() as s:
            orm = s.get(OTPChallengeORM, challenge_id)
            if orm:
                orm.attempts += 1

    def get_pending_otp_challenge(self, contact_value: str, purpose: OTPPurpose) -> dict | None:
        with self.session() as s:
            rows = s.scalars(
                select(OTPChallengeORM)
                .where(
                    OTPChallengeORM.contact_value == contact_value,
                    OTPChallengeORM.purpose == purpose.value,
                    OTPChallengeORM.consumed == False,
                )
                .order_by(OTPChallengeORM.created_at.desc())
            ).all()
            for row in rows:
                expires_at = _as_utc(row.expires_at)
                if expires_at and expires_at < _utcnow():
                    continue
                return self._otp_dict(row)
            return None

    def create_password_reset_challenge(self, *, user_id, contact_value, channel, code_hash, max_attempts=5, expires_at=None) -> dict:
        challenge_id = str(uuid4())
        with self.session() as s:
            orm = PasswordResetChallengeORM(
                id=challenge_id,
                user_id=user_id,
                contact_value=contact_value,
                channel=channel.value,
                code_hash=code_hash,
                max_attempts=max_attempts,
                expires_at=expires_at,
            )
            s.add(orm)
        return self._password_reset_dict(orm)

    def get_password_reset_challenge(self, challenge_id: str) -> dict | None:
        with self.session() as s:
            orm = s.get(PasswordResetChallengeORM, challenge_id)
            return self._password_reset_dict(orm) if orm else None

    def consume_password_reset_challenge(self, challenge_id: str) -> None:
        with self.session() as s:
            orm = s.get(PasswordResetChallengeORM, challenge_id)
            if orm:
                orm.consumed = True

    def increment_password_reset_attempts(self, challenge_id: str) -> None:
        with self.session() as s:
            orm = s.get(PasswordResetChallengeORM, challenge_id)
            if orm:
                orm.attempts += 1

    def get_pending_password_reset_challenge(self, user_id: str) -> dict | None:
        with self.session() as s:
            rows = s.scalars(
                select(PasswordResetChallengeORM)
                .where(
                    PasswordResetChallengeORM.user_id == user_id,
                    PasswordResetChallengeORM.consumed == False,
                )
                .order_by(PasswordResetChallengeORM.created_at.desc())
            ).all()
            for row in rows:
                expires_at = _as_utc(row.expires_at)
                if expires_at and expires_at < _utcnow():
                    continue
                return self._password_reset_dict(row)
            return None

    # ------------------------------------------------------------------
    # Sessions & refresh credentials
    # ------------------------------------------------------------------
    def create_session(self, *, user_id, token_hash, expires_at=None, ip_address=None, user_agent=None) -> dict:
        session_id = str(uuid4())
        with self.session() as s:
            orm = SessionORM(
                id=session_id,
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            s.add(orm)
            s.flush()
            result = self._session_dict(orm)
        return result

    def get_session(self, session_id: str) -> dict | None:
        with self.session() as s:
            orm = s.get(SessionORM, session_id)
            return self._session_dict(orm) if orm else None

    def touch_session(self, session_id: str) -> None:
        with self.session() as s:
            orm = s.get(SessionORM, session_id)
            if orm:
                orm.last_active_at = _utcnow()

    def revoke_session(self, session_id: str) -> bool:
        with self.session() as s:
            orm = s.get(SessionORM, session_id)
            if not orm:
                return False
            orm.revoked = True
        return True

    def revoke_all_user_sessions(self, user_id: str, except_session_id: str | None = None) -> int:
        with self.session() as s:
            rows = s.scalars(
                select(SessionORM).where(SessionORM.user_id == user_id)
            ).all()
            count = 0
            for row in rows:
                if except_session_id and row.id == except_session_id:
                    continue
                if not row.revoked:
                    row.revoked = True
                    count += 1
            return count

    def create_refresh_credential(self, *, user_id, session_id, token_hash, expires_at=None, previous_token_hash=None) -> dict:
        credential_id = str(uuid4())
        with self.session() as s:
            orm = RefreshCredentialORM(
                id=credential_id,
                user_id=user_id,
                session_id=session_id,
                token_hash=token_hash,
                previous_token_hash=previous_token_hash,
                expires_at=expires_at,
            )
            s.add(orm)
            s.flush()
            result = self._refresh_dict(orm)
        return result

    def get_refresh_credential_by_hash(self, token_hash: str) -> dict | None:
        with self.session() as s:
            orm = s.scalars(
                select(RefreshCredentialORM).where(RefreshCredentialORM.token_hash == token_hash)
            ).first()
            return self._refresh_dict(orm) if orm else None

    def get_refresh_credential_by_previous_hash(self, token_hash: str) -> dict | None:
        """Find a credential whose rotated-away hash matches.

        A match here means an already-rotated refresh credential
        was presented again: reuse of a revoked credential.
        """
        with self.session() as s:
            orm = s.scalars(
                select(RefreshCredentialORM).where(RefreshCredentialORM.previous_token_hash == token_hash)
            ).first()
            return self._refresh_dict(orm) if orm else None

    def rotate_refresh_credential(self, credential_id: str, new_token_hash: str, expires_at=None) -> dict | None:
        with self.session() as s:
            orm = s.get(RefreshCredentialORM, credential_id)
            if not orm:
                return None
            orm.previous_token_hash = orm.token_hash
            orm.token_hash = new_token_hash
            orm.rotated_at = _utcnow()
            orm.expires_at = expires_at
        return self.get_refresh_credential_by_hash(new_token_hash)

    def revoke_refresh_credential(self, credential_id: str) -> bool:
        with self.session() as s:
            orm = s.get(RefreshCredentialORM, credential_id)
            if not orm:
                return False
            orm.revoked = True
        return True

    def revoke_refresh_credentials_for_session(self, session_id: str) -> int:
        with self.session() as s:
            rows = s.scalars(
                select(RefreshCredentialORM).where(RefreshCredentialORM.session_id == session_id)
            ).all()
            count = 0
            for row in rows:
                if not row.revoked:
                    row.revoked = True
                    count += 1
            return count

    def revoke_all_user_refresh_credentials(self, user_id: str) -> int:
        with self.session() as s:
            rows = s.scalars(
                select(RefreshCredentialORM).where(RefreshCredentialORM.user_id == user_id)
            ).all()
            count = 0
            for row in rows:
                if not row.revoked:
                    row.revoked = True
                    count += 1
            return count

    # ------------------------------------------------------------------
    # Recovery tokens
    # ------------------------------------------------------------------
    def create_recovery_token(self, *, user_id, purpose, token_hash, expires_at=None) -> dict:
        token_id = str(uuid4())
        with self.session() as s:
            orm = RecoveryTokenORM(
                id=token_id,
                user_id=user_id,
                purpose=purpose,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            s.add(orm)
        return self._recovery_dict(orm)

    def get_recovery_token_by_hash(self, token_hash: str) -> dict | None:
        with self.session() as s:
            orm = s.scalars(
                select(RecoveryTokenORM).where(RecoveryTokenORM.token_hash == token_hash)
            ).first()
            return self._recovery_dict(orm) if orm else None

    def consume_recovery_token(self, token_id: str) -> None:
        with self.session() as s:
            orm = s.get(RecoveryTokenORM, token_id)
            if orm:
                orm.consumed = True

    # ------------------------------------------------------------------
    # Payment records
    # ------------------------------------------------------------------
    def upsert_payment_record(self, user_id: str, provider: PaymentProviderKind, **fields) -> dict:
        with self.session() as s:
            orm = s.scalars(
                select(PaymentRecordORM).where(PaymentRecordORM.user_id == user_id)
            ).first()
            if not orm:
                orm = PaymentRecordORM(id=str(uuid4()), user_id=user_id, provider=provider.value)
                s.add(orm)
            for key, value in fields.items():
                if key == "eligibility" and isinstance(value, PaymentEligibility):
                    value = value.value
                if hasattr(orm, key):
                    setattr(orm, key, value)
            orm.updated_at = _utcnow()
        return self.get_payment_record(user_id)

    def get_payment_record(self, user_id: str) -> dict | None:
        with self.session() as s:
            orm = s.scalars(
                select(PaymentRecordORM).where(PaymentRecordORM.user_id == user_id)
            ).first()
            return self._payment_dict(orm) if orm else None

    # ------------------------------------------------------------------
    # Registration attempts (PKCE state tracking)
    # ------------------------------------------------------------------
    def create_registration_attempt(self, *, state, nonce, code_verifier, expires_at) -> dict:
        attempt_id = str(uuid4())
        with self.session() as s:
            orm = RegistrationAttemptORM(
                id=attempt_id,
                state=state,
                nonce=nonce,
                code_verifier=code_verifier,
                expires_at=expires_at,
            )
            s.add(orm)
        return self.get_registration_attempt_by_state(state)

    def get_registration_attempt_by_state(self, state: str) -> dict | None:
        with self.session() as s:
            orm = s.scalars(
                select(RegistrationAttemptORM).where(RegistrationAttemptORM.state == state)
            ).first()
            return self._registration_attempt_dict(orm) if orm else None

    def update_registration_attempt(self, state: str, **fields) -> dict | None:
        with self.session() as s:
            orm = s.scalars(
                select(RegistrationAttemptORM).where(RegistrationAttemptORM.state == state)
            ).first()
            if not orm:
                return None
            for key, value in fields.items():
                if hasattr(orm, key):
                    setattr(orm, key, value)
        return self.get_registration_attempt_by_state(state)

    def delete_registration_attempt(self, state: str) -> bool:
        with self.session() as s:
            orm = s.scalars(
                select(RegistrationAttemptORM).where(RegistrationAttemptORM.state == state)
            ).first()
            if not orm:
                return False
            s.delete(orm)
            return True

    # ------------------------------------------------------------------
    # Audit events
    # ------------------------------------------------------------------
    def record_audit_event(
        self,
        *,
        event_type,
        actor_id=None,
        target_id=None,
        outcome="success",
        detail="",
        metadata=None,
        ip_address=None,
        user_agent=None,
    ) -> dict:
        event_id = str(uuid4())
        record_metadata = dict(metadata or {})
        if ip_address:
            record_metadata["ip_address"] = ip_address
        if user_agent:
            record_metadata["user_agent"] = user_agent
        with self.session() as s:
            orm = AuditEventORM(
                id=event_id,
                actor_id=actor_id,
                target_id=target_id,
                event_type=event_type,
                outcome=outcome,
                detail=detail,
                metadata=record_metadata,
            )
            s.add(orm)
        return {"id": event_id, "event_type": event_type}

    def audit_events_for_user(self, user_id: str, limit: int = 50) -> list[dict]:
        with self.session() as s:
            rows = s.scalars(
                select(AuditEventORM)
                .where((AuditEventORM.actor_id == user_id) | (AuditEventORM.target_id == user_id))
                .order_by(AuditEventORM.created_at.desc())
                .limit(limit)
            ).all()
            return [self._audit_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Entitlements
    # ------------------------------------------------------------------
    def grant_entitlement(self, user_id: str, entitlement: str = "paid", source: str = "registration", metadata=None) -> dict:
        record_id = str(uuid4())
        with self.session() as s:
            orm = EntitlementRecordORM(
                id=record_id,
                user_id=user_id,
                entitlement=entitlement,
                source=source,
                metadata=metadata or {},
            )
            s.add(orm)
        return {"id": record_id}

    # ------------------------------------------------------------------
    # OAuth / registration attempts
    # ------------------------------------------------------------------
    def store_registration_attempt(
        self,
        *,
        state: str,
        nonce: str,
        code_verifier: str,
        expires_at,
        provider_subject: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        attempt_id = str(uuid4())
        with self.session() as s:
            orm = RegistrationAttemptORM(
                id=attempt_id,
                state=state,
                nonce=nonce,
                code_verifier=code_verifier,
                provider_subject=provider_subject,
                user_id=user_id,
                expires_at=expires_at,
            )
            s.add(orm)
        return {"id": attempt_id, "state": state}

    def get_registration_attempt(self, state: str) -> dict | None:
        with self.session() as s:
            orm = s.scalars(
                select(RegistrationAttemptORM).where(RegistrationAttemptORM.state == state)
            ).first()
            if not orm:
                return None
            return {
                "id": orm.id,
                "state": orm.state,
                "nonce": orm.nonce,
                "code_verifier": orm.code_verifier,
                "provider_subject": orm.provider_subject,
                "user_id": orm.user_id,
                "created_at": orm.created_at,
                "expires_at": orm.expires_at,
            }

    def consume_registration_attempt(self, state: str) -> dict | None:
        attempt = self.get_registration_attempt(state)
        if attempt is None:
            return None
        if attempt["expires_at"] and attempt["expires_at"] < _utcnow():
            return None
        with self.session() as s:
            orm = s.get(RegistrationAttemptORM, attempt["id"])
            if orm:
                s.delete(orm)
        return attempt

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    def cleanup_expired(self) -> int:
        now = _utcnow()
        deleted = 0
        with self.session() as s:
            for model, expires_col in (
                (OTPChallengeORM, OTPChallengeORM.expires_at),
                (PasswordResetChallengeORM, PasswordResetChallengeORM.expires_at),
                (RecoveryTokenORM, RecoveryTokenORM.expires_at),
                (RefreshCredentialORM, RefreshCredentialORM.expires_at),
                (RegistrationAttemptORM, RegistrationAttemptORM.expires_at),
            ):
                rows = s.scalars(select(model).where(expires_col != None, expires_col < now)).all()
                for row in rows:
                    s.delete(row)
                    deleted += 1
        return deleted

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    def _user_dict(self, orm: UserORM) -> dict:
        return {
            "id": orm.id,
            "username": orm.username,
            "password_hash": orm.password_hash,
            "status": AccountStatus(orm.status),
            "entitlement": orm.entitlement,
            "google_linked": bool(orm.google_linked),
            "created_at": _as_utc(orm.created_at),
            "updated_at": _as_utc(orm.updated_at),
            "last_login_at": _as_utc(orm.last_login_at),
            "failed_login_count": orm.failed_login_count,
            "locked_until": _as_utc(orm.locked_until),
        }

    def _identity_dict(self, orm: ExternalIdentityORM) -> dict:
        return {
            "id": orm.id,
            "user_id": orm.user_id,
            "provider": IdentityProvider(orm.provider),
            "provider_subject": orm.provider_subject,
            "verified_at": _as_utc(orm.verified_at),
            "linked_at": _as_utc(orm.linked_at),
            "created_at": _as_utc(orm.created_at),
        }

    def _contact_dict(self, orm: ContactMethodORM) -> dict:
        return {
            "id": orm.id,
            "user_id": orm.user_id,
            "type": ContactType(orm.type),
            "value": orm.value,
            "verification_status": ContactVerificationStatus(orm.verification_status),
            "is_primary": bool(orm.is_primary),
            "created_at": _as_utc(orm.created_at),
            "verified_at": _as_utc(orm.verified_at),
        }

    def _otp_dict(self, orm: OTPChallengeORM) -> dict:
        return {
            "id": orm.id,
            "contact_value": orm.contact_value,
            "channel": OTPChannel(orm.channel),
            "purpose": OTPPurpose(orm.purpose),
            "code_hash": orm.code_hash,
            "attempts": orm.attempts,
            "max_attempts": orm.max_attempts,
            "consumed": bool(orm.consumed),
            "created_at": _as_utc(orm.created_at),
            "expires_at": _as_utc(orm.expires_at),
            "ip_address": orm.ip_address,
        }

    def _password_reset_dict(self, orm: PasswordResetChallengeORM) -> dict:
        return {
            "id": orm.id,
            "user_id": orm.user_id,
            "contact_value": orm.contact_value,
            "channel": OTPChannel(orm.channel),
            "code_hash": orm.code_hash,
            "attempts": orm.attempts,
            "max_attempts": orm.max_attempts,
            "consumed": bool(orm.consumed),
            "created_at": _as_utc(orm.created_at),
            "expires_at": _as_utc(orm.expires_at),
        }

    def _session_dict(self, orm: SessionORM) -> dict:
        return {
            "id": orm.id,
            "user_id": orm.user_id,
            "token_hash": orm.token_hash,
            "created_at": _as_utc(orm.created_at),
            "last_active_at": _as_utc(orm.last_active_at),
            "expires_at": _as_utc(orm.expires_at),
            "ip_address": orm.ip_address,
            "user_agent": orm.user_agent,
            "revoked": bool(orm.revoked),
        }

    def _refresh_dict(self, orm: RefreshCredentialORM) -> dict:
        return {
            "id": orm.id,
            "user_id": orm.user_id,
            "session_id": orm.session_id,
            "token_hash": orm.token_hash,
            "previous_token_hash": orm.previous_token_hash,
            "created_at": _as_utc(orm.created_at),
            "expires_at": _as_utc(orm.expires_at),
            "revoked": bool(orm.revoked),
            "rotated_at": _as_utc(orm.rotated_at),
        }

    def _recovery_dict(self, orm: RecoveryTokenORM) -> dict:
        return {
            "id": orm.id,
            "user_id": orm.user_id,
            "purpose": orm.purpose,
            "token_hash": orm.token_hash,
            "expires_at": _as_utc(orm.expires_at),
            "consumed": bool(orm.consumed),
            "created_at": _as_utc(orm.created_at),
        }

    def _registration_attempt_dict(self, orm: RegistrationAttemptORM) -> dict:
        return {
            "id": orm.id,
            "state": orm.state,
            "nonce": orm.nonce,
            "code_verifier": orm.code_verifier,
            "provider_subject": orm.provider_subject,
            "user_id": orm.user_id,
            "created_at": _as_utc(orm.created_at),
            "expires_at": _as_utc(orm.expires_at),
        }

    def _payment_dict(self, orm: PaymentRecordORM) -> dict:
        return {
            "id": orm.id,
            "user_id": orm.user_id,
            "provider": PaymentProviderKind(orm.provider),
            "provider_customer_ref": orm.provider_customer_ref,
            "provider_payment_method_ref": orm.provider_payment_method_ref,
            "eligibility": PaymentEligibility(orm.eligibility),
            "created_at": _as_utc(orm.created_at),
            "updated_at": _as_utc(orm.updated_at),
        }

    def _audit_dict(self, orm: AuditEventORM) -> dict:
        return {
            "id": orm.id,
            "actor_id": orm.actor_id,
            "target_id": orm.target_id,
            "event_type": orm.event_type,
            "outcome": orm.outcome,
            "detail": orm.detail,
            "metadata": orm.metadata or {},
            "created_at": _as_utc(orm.created_at),
        }
