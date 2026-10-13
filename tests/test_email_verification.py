"""Tests for email verification and EmailJS delivery.

The external EmailJS API is mocked in every test: automated
tests never send real email or consume EmailJS quota.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select as sa_select
from sqlalchemy import update as sa_update

from eternix.auth.config import AuthSettings, auth_settings
from eternix.auth.delivery import DeliveryError, send_emailjs_email
from eternix.auth.models import (
    AccountStatus,
    ContactType,
    ContactVerificationStatus,
    OTPChannel,
    OTPPurpose,
)
from eternix.auth.password import hash_password
from eternix.auth.service import AuthError, AuthService
from eternix.auth.store import AuthStore, OTPChallengeORM, hash_token
from eternix.auth.tokens import generate_otp
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return AuthStore(db_path=tmp_path / "email-verification-test.db")


@pytest.fixture
def service(store):
    return AuthService(store=store)


@pytest.fixture
def awaiting_user(service):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    user = service.store.create_user(
        username=f"tester-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Sup3rSecret!"),
        status=AccountStatus.AWAITING_VERIFICATION,
    )
    service._ensure_contact(user["id"], email, verified=False)
    return user


def contact_email(service, user):
    """The primary contact value (email) of a test user."""
    return service._primary_contact(service.store.get_user(user["id"]))["value"]


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


def configure_emailjs(monkeypatch, *, service_id="service_5i21ybi", template_id="template_abc123", public_key="pub_key", private_key=""):
    monkeypatch.setattr(auth_settings, "emailjs_service_id", service_id)
    monkeypatch.setattr(auth_settings, "emailjs_template_id", template_id)
    monkeypatch.setattr(auth_settings, "emailjs_public_key", public_key)
    monkeypatch.setattr(
        auth_settings,
        "emailjs_private_key",
        SecretStr(private_key) if private_key else SecretStr(""),
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestEmailVerificationConfig:
    def test_emailjs_settings_from_prefixed_env(self, monkeypatch):
        monkeypatch.setenv("ETERNIX_AUTH_EMAILJS_SERVICE_ID", "service_abc")
        monkeypatch.setenv("ETERNIX_AUTH_EMAILJS_TEMPLATE_ID", "template_abc")
        monkeypatch.setenv("ETERNIX_AUTH_EMAILJS_PUBLIC_KEY", "public_key")
        monkeypatch.setenv("ETERNIX_AUTH_EMAILJS_PRIVATE_KEY", "private_key")
        monkeypatch.setenv("ETERNIX_AUTH_EMAIL_PROVIDER", "emailjs")
        settings = AuthSettings(_env_file=None)
        assert settings.emailjs_service_id == "service_abc"
        assert settings.emailjs_template_id == "template_abc"
        assert settings.emailjs_public_key == "public_key"
        assert settings.emailjs_private_key.get_secret_value() == "private_key"
        assert settings.email_provider == "emailjs"
        assert settings.emailjs_configured is True
        assert settings.email_configured is True

    def test_emailjs_settings_from_unprefixed_env(self, monkeypatch):
        monkeypatch.setenv("EMAILJS_SERVICE_ID", "service_xyz")
        monkeypatch.setenv("EMAILJS_TEMPLATE_ID", "template_xyz")
        monkeypatch.setenv("EMAILJS_PUBLIC_KEY", "pub")
        settings = AuthSettings(_env_file=None)
        assert settings.emailjs_service_id == "service_xyz"
        assert settings.emailjs_template_id == "template_xyz"
        assert settings.emailjs_public_key == "pub"

    def test_emailjs_not_configured_without_template_or_key(self, monkeypatch):
        monkeypatch.setenv("ETERNIX_AUTH_EMAILJS_TEMPLATE_ID", "")
        monkeypatch.setenv("ETERNIX_AUTH_EMAILJS_PUBLIC_KEY", "")
        settings = AuthSettings(_env_file=None)
        assert settings.emailjs_configured is False
        assert settings.email_configured is False

    def test_email_verification_alias_settings(self, monkeypatch):
        monkeypatch.setenv("EMAIL_VERIFICATION_CODE_TTL_MINUTES", "10")
        monkeypatch.setenv("EMAIL_VERIFICATION_MAX_ATTEMPTS", "3")
        monkeypatch.setenv("EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS", "120")
        settings = AuthSettings(_env_file=None)
        assert settings.otp_expiry_seconds == 600
        assert settings.otp_max_attempts == 3
        assert settings.otp_request_cooldown_seconds == 120

    def test_default_verification_policy(self):
        assert auth_settings.otp_expiry_seconds > 0
        assert auth_settings.otp_max_attempts >= 3
        assert auth_settings.otp_request_cooldown_seconds > 0


# ---------------------------------------------------------------------------
# EmailJS delivery (mocked HTTP)
# ---------------------------------------------------------------------------


class TestEmailJsDelivery:
    def test_request_construction(self, monkeypatch):
        configure_emailjs(monkeypatch)
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeResponse(200, {"message": "OK"})

        monkeypatch.setattr(httpx, "post", fake_post)
        send_emailjs_email("user@example.com", "654321")

        assert captured["url"] == "https://api.emailjs.com/api/v1.0/email/send"
        assert captured["timeout"] == 20.0
        body = captured["json"]
        assert body["service_id"] == "service_5i21ybi"
        assert body["template_id"] == "template_abc123"
        assert body["user_id"] == "pub_key"
        assert "access_token" not in body  # private key unset
        assert body["template_params"]["to_email"] == "user@example.com"
        assert body["template_params"]["verification_code"] == "654321"
        assert body["template_params"]["expires_in_minutes"] == "5"

    def test_private_key_sent_as_access_token(self, monkeypatch):
        configure_emailjs(monkeypatch, private_key="secret_private_key")
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["json"] = json
            return FakeResponse(200, {"message": "OK"})

        monkeypatch.setattr(httpx, "post", fake_post)
        send_emailjs_email("user@example.com", "123456")
        assert captured["json"]["access_token"] == "secret_private_key"

    def test_expires_in_minutes_derived_from_ttl(self, monkeypatch):
        configure_emailjs(monkeypatch)
        monkeypatch.setattr(auth_settings, "otp_expiry_seconds", 600)
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["json"] = json
            return FakeResponse(200, {"message": "OK"})

        monkeypatch.setattr(httpx, "post", fake_post)
        send_emailjs_email("user@example.com", "123456")
        assert captured["json"]["template_params"]["expires_in_minutes"] == "10"

    def test_missing_configuration(self, monkeypatch):
        configure_emailjs(monkeypatch, template_id="", public_key="")
        with pytest.raises(DeliveryError):
            send_emailjs_email("user@example.com", "123456")

    def test_invalid_template_id_rejected(self, monkeypatch):
        configure_emailjs(monkeypatch)
        monkeypatch.setattr(
            httpx, "post",
            lambda url, json=None, timeout=None: FakeResponse(400, {"message": "Invalid template ID"}),
        )
        with pytest.raises(DeliveryError) as exc:
            send_emailjs_email("user@example.com", "123456")
        assert "400" in str(exc.value)

    def test_http_rejection(self, monkeypatch):
        configure_emailjs(monkeypatch)
        monkeypatch.setattr(
            httpx, "post",
            lambda url, json=None, timeout=None: FakeResponse(503, {"message": "Service unavailable"}),
        )
        with pytest.raises(DeliveryError):
            send_emailjs_email("user@example.com", "123456")

    def test_non_ok_success_response_rejected(self, monkeypatch):
        configure_emailjs(monkeypatch)
        monkeypatch.setattr(
            httpx, "post",
            lambda url, json=None, timeout=None: FakeResponse(200, {"message": "Not OK"}),
        )
        with pytest.raises(DeliveryError):
            send_emailjs_email("user@example.com", "123456")

    def test_network_timeout(self, monkeypatch):
        configure_emailjs(monkeypatch)

        def fake_post(url, json=None, timeout=None):
            raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(httpx, "post", fake_post)
        with pytest.raises(DeliveryError):
            send_emailjs_email("user@example.com", "123456")

    def test_connection_failure(self, monkeypatch):
        configure_emailjs(monkeypatch)

        def fake_post(url, json=None, timeout=None):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "post", fake_post)
        with pytest.raises(DeliveryError):
            send_emailjs_email("user@example.com", "123456")

    def test_error_messages_leak_no_secrets_or_code(self, monkeypatch):
        configure_emailjs(monkeypatch, private_key="super_secret_private")
        monkeypatch.setattr(
            httpx, "post",
            lambda url, json=None, timeout=None: FakeResponse(402, {"message": "Monthly limit exceeded"}),
        )
        with pytest.raises(DeliveryError) as exc:
            send_emailjs_email("user@example.com", "987654")
        message = str(exc.value)
        assert "super_secret_private" not in message
        assert "987654" not in message
        assert "pub_key" not in message


# ---------------------------------------------------------------------------
# Code generation and persistence
# ---------------------------------------------------------------------------


class TestVerificationCodes:
    def test_code_is_numeric_and_configured_length(self):
        code = generate_otp()
        assert code.isdigit()
        assert len(code) == auth_settings.otp_length

    def test_codes_are_unpredictable(self):
        codes = {generate_otp() for _ in range(20)}
        assert len(codes) > 1

    def test_request_stores_only_hash(self, service, awaiting_user):
        result = service.request_verification(awaiting_user["id"])
        assert result["dev_code"].isdigit()

        challenge = service.store.get_pending_otp_challenge(
            contact_email(service, awaiting_user), OTPPurpose.REGISTRATION
        )
        assert challenge is not None
        # The plaintext code is never persisted.
        assert challenge["code_hash"] != result["dev_code"]
        # Only the SHA-256 hex digest of the code is stored.
        assert challenge["code_hash"] == hash_token(result["dev_code"])
        assert len(challenge["code_hash"]) == 64

    def test_challenge_metadata(self, service, awaiting_user):
        service.request_verification(awaiting_user["id"])
        challenge = service.store.get_pending_otp_challenge(
            contact_email(service, awaiting_user), OTPPurpose.REGISTRATION
        )
        assert challenge["max_attempts"] == auth_settings.otp_max_attempts
        assert challenge["attempts"] == 0
        assert challenge["consumed"] is False
        assert challenge["expires_at"] is not None
        assert challenge["expires_at"] > datetime.now(UTC)


# ---------------------------------------------------------------------------
# Verification state machine
# ---------------------------------------------------------------------------


class TestVerificationFlow:
    def test_correct_code_accepted(self, service, awaiting_user):
        result = service.request_verification(awaiting_user["id"])
        confirmed = service.confirm_verification(
            awaiting_user["id"], result["dev_code"]
        )
        assert confirmed["user"]["account_state"] == "awaiting_payment_method"
        contact = service._primary_contact(
            service.store.get_user(awaiting_user["id"])
        )
        assert contact["verification_status"] == ContactVerificationStatus.VERIFIED

    def test_successful_verification_is_atomic_and_cannot_replay(
        self, service, awaiting_user
    ):
        result = service.request_verification(awaiting_user["id"])
        service.confirm_verification(awaiting_user["id"], result["dev_code"])
        # Replaying the consumed code is rejected: the
        # account has already left the verification step
        # and no pending challenge remains.
        with pytest.raises(AuthError) as exc:
            service.confirm_verification(awaiting_user["id"], result["dev_code"])
        assert exc.value.code in {"invalid_state", "no_challenge"}

    def test_incorrect_code_rejected(self, service, awaiting_user):
        service.request_verification(awaiting_user["id"])
        with pytest.raises(AuthError) as exc:
            service.confirm_verification(awaiting_user["id"], "000000")
        assert exc.value.code == "invalid_code"
        # The account stays in the verification step.
        user = service.store.get_user(awaiting_user["id"])
        assert user["status"] == AccountStatus.AWAITING_VERIFICATION

    def test_expired_code_rejected(self, service, awaiting_user, store):
        service.request_verification(awaiting_user["id"])
        with store.session() as s:
            s.execute(
                sa_update(OTPChallengeORM).values(
                    expires_at=datetime.now(UTC) - timedelta(seconds=1)
                )
            )
        challenge = service.store.get_pending_otp_challenge(
            contact_email(service, awaiting_user), OTPPurpose.REGISTRATION
        )
        # The expired challenge is no longer served as pending...
        assert challenge is None
        # ...and confirmation is refused.
        with pytest.raises(AuthError) as exc:
            service.confirm_verification(awaiting_user["id"], "123456")
        assert exc.value.code in {"no_challenge", "expired"}

    def test_attempt_limit_enforced(self, service, awaiting_user):
        service.request_verification(awaiting_user["id"])
        for _ in range(auth_settings.otp_max_attempts):
            with pytest.raises(AuthError) as exc:
                service.confirm_verification(awaiting_user["id"], "000000")
            assert exc.value.code == "invalid_code"
        # One more attempt than the limit is refused outright.
        with pytest.raises(AuthError) as exc:
            service.confirm_verification(awaiting_user["id"], "000000")
        assert exc.value.code == "max_attempts"

    def test_resend_cooldown_enforced(self, service, awaiting_user):
        service.request_verification(awaiting_user["id"])
        with pytest.raises(AuthError) as exc:
            service.request_verification(awaiting_user["id"])
        assert exc.value.code == "cooldown"
        assert exc.value.status == 429

    def test_new_code_invalidates_previous_codes(
        self, service, awaiting_user, store
    ):
        first = service.request_verification(awaiting_user["id"])
        # Age the pending challenge past the resend cooldown.
        with store.session() as s:
            s.execute(
                sa_update(OTPChallengeORM).values(
                    created_at=datetime.now(UTC)
                    - timedelta(seconds=auth_settings.otp_request_cooldown_seconds + 10)
                )
            )
        second = service.request_verification(awaiting_user["id"])
        assert first["dev_code"] != second["dev_code"]

        # The first (invalidated) code no longer verifies.
        with pytest.raises(AuthError):
            service.confirm_verification(awaiting_user["id"], first["dev_code"])
        # The most recently issued code does.
        confirmed = service.confirm_verification(awaiting_user["id"], second["dev_code"])
        assert confirmed["user"]["account_state"] == "awaiting_payment_method"

    def test_only_most_recent_code_is_pending(self, service, awaiting_user, store):
        service.request_verification(awaiting_user["id"])
        with store.session() as s:
            s.execute(
                sa_update(OTPChallengeORM).values(
                    created_at=datetime.now(UTC)
                    - timedelta(seconds=auth_settings.otp_request_cooldown_seconds + 10)
                )
            )
        service.request_verification(awaiting_user["id"])
        with store.session() as s:
            rows = s.scalars(
                sa_select(OTPChallengeORM).where(
                    OTPChallengeORM.contact_value == contact_email(service, awaiting_user),
                    OTPChallengeORM.consumed == False,  # noqa: E712
                )
            ).all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Delivery failure handling
# ---------------------------------------------------------------------------


class TestDeliveryFailureHandling:
    def test_delivery_failure_returns_error_not_success(
        self, service, awaiting_user, monkeypatch
    ):
        monkeypatch.setattr(auth_settings, "email_provider", "emailjs")
        configure_emailjs(monkeypatch)

        def failing_send(to, code):
            raise DeliveryError("EmailJS rejected the send request (HTTP 400)")

        monkeypatch.setattr(
            "eternix.auth.service.send_emailjs_email", failing_send
        )
        with pytest.raises(AuthError) as exc:
            service.request_verification(awaiting_user["id"])
        assert exc.value.status == 502
        assert exc.value.code == "delivery_failed"

    def test_delivery_not_configured_in_production(self, service, awaiting_user, monkeypatch):
        monkeypatch.setattr(auth_settings, "mode", "production")
        monkeypatch.setattr(auth_settings, "email_provider", "none")
        with pytest.raises(AuthError) as exc:
            service.request_verification(awaiting_user["id"])
        assert exc.value.code == "delivery_not_configured"
        assert exc.value.status == 503

    def test_dev_fallback_disabled_in_production(self, service, awaiting_user, monkeypatch):
        monkeypatch.setattr(auth_settings, "mode", "production")
        monkeypatch.setattr(auth_settings, "email_provider", "emailjs")
        configure_emailjs(monkeypatch)
        monkeypatch.setattr(
            "eternix.auth.service.send_emailjs_email",
            lambda to, code: (_ for _ in ()).throw(DeliveryError("unreachable")),
        )
        # In production the development code-in-response
        # fallback must never apply; a real delivery
        # failure is surfaced as an error.
        with pytest.raises(AuthError) as exc:
            service.request_verification(awaiting_user["id"])
        assert exc.value.code == "delivery_failed"
        assert exc.value.status == 502

    def test_rate_limit_blocks_excessive_requests(
        self, service, awaiting_user, store
    ):
        # Exhaust the per-hour request budget for this contact.
        for _ in range(auth_settings.otp_max_requests_per_hour):
            service.request_verification(awaiting_user["id"])
            # Age challenges past the resend cooldown so each
            # attempt reaches the rate-limit check.
            with store.session() as s:
                s.execute(
                    sa_update(OTPChallengeORM).values(
                        created_at=datetime.now(UTC)
                        - timedelta(seconds=auth_settings.otp_request_cooldown_seconds + 10)
                    )
                )
        with pytest.raises(AuthError) as exc:
            service.request_verification(awaiting_user["id"])
        assert exc.value.code == "rate_limited"


# ---------------------------------------------------------------------------
# Onboarding policy preserved
# ---------------------------------------------------------------------------


class TestOnboardingPolicy:
    def test_protected_access_requires_full_onboarding(self, service, store):
        # Dev identity -> credentials -> verification -> payment -> active.
        identity = service.register_dev_identity()
        user_id = identity["user"]["id"]

        credentials = service.complete_registration(
            user_id,
            username=f"onboard_{uuid.uuid4().hex[:6]}",
            password="Sup3rSecret!",
            email="onboard@example.com",
        )
        assert credentials["user"]["account_state"] == "awaiting_verification"

        sent = service.request_verification(user_id)
        challenge = store.get_pending_otp_challenge(
            "onboard@example.com", OTPPurpose.REGISTRATION
        )
        assert challenge is not None

        confirmed = service.confirm_verification(user_id, sent["dev_code"])
        assert confirmed["user"]["account_state"] == "awaiting_payment_method"

        # Without an eligible payment method the account is
        # still not active and cannot access protected routes.
        profile = confirmed["user"]
        assert profile["account_state"] != "active"
        assert profile["payment_eligibility"] != "eligible"

    def test_verification_required_state_guards(self, service, awaiting_user):
        # Requesting verification is only valid from the
        # awaiting_verification step.
        user = service.store.get_user(awaiting_user["id"])
        service.store.update_user(user["id"], status=AccountStatus.ACTIVE)
        with pytest.raises(AuthError) as exc:
            service.request_verification(user["id"])
        assert exc.value.code == "invalid_state"


# ---------------------------------------------------------------------------
# Async delivery routing (unused by the registration flow, kept consistent)
# ---------------------------------------------------------------------------


class TestAsyncDeliveryRouting:
    async def test_deliver_otp_routes_emailjs(self, monkeypatch, tmp_path):
        from eternix.auth import delivery as delivery_module
        from eternix.auth.models import OTPChannel, OTPPurpose

        store = AuthStore(db_path=tmp_path / "async-delivery.db")
        monkeypatch.setattr(auth_settings, "email_provider", "emailjs")
        configure_emailjs(monkeypatch)

        captured = {}

        def fake_send(to, code):
            captured["to"] = to
            captured["code"] = code

        monkeypatch.setattr(delivery_module, "send_emailjs_email", fake_send)
        challenge_id = await delivery_module.deliver_otp(
            store,
            contact_value="async@example.com",
            channel=OTPChannel.EMAIL,
            purpose=OTPPurpose.REGISTRATION,
        )
        assert challenge_id
        assert captured["to"] == "async@example.com"
        assert captured["code"].isdigit()
        challenge = store.get_otp_challenge(challenge_id)
        assert challenge is not None
        assert challenge["code_hash"] != captured["code"]
