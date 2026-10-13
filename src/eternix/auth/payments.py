"""Payment-method registration providers.

The payment-method gate is a mandatory part of ETERNIX's account
access policy.  This module defines a provider abstraction with two
implementations:

* ``SandboxPaymentProvider`` — a development-only provider that
  registers a payment method without touching any payment network
  and never charges real money.  It is unavailable in production.
* ``StripePaymentProvider`` — the production provider.  It requires
  the ``stripe`` package and valid API credentials.  When either is
  missing it reports ``not configured`` rather than silently
  succeeding.

A payment method is only marked eligible after the provider
authoritatively confirms it.  The frontend redirect is never
trusted as proof of success.
"""

from __future__ import annotations

import secrets
import uuid
from abc import ABC, abstractmethod

from pydantic import BaseModel

from eternix.auth.config import auth_settings


class PaymentError(Exception):
    """Raised when a payment operation cannot be completed."""


class PaymentSetupSession(BaseModel):
    """A payment-method setup session returned to the frontend."""

    provider: str
    session_id: str
    client_secret: str
    setup_url: str | None = None


class PaymentConfirmation(BaseModel):
    """The authoritative result of a payment-method setup."""

    eligible: bool
    provider_customer_ref: str = ""
    provider_payment_method_ref: str = ""
    reason: str = ""


class PaymentProvider(ABC):
    """Interface for a payment-method registration provider."""

    name: str = "none"

    @abstractmethod
    async def create_setup_session(self, user_id: str) -> PaymentSetupSession:
        """Create a payment-method setup session."""

    @abstractmethod
    async def confirm_setup(
        self,
        session_id: str,
        payment_method_token: str,
    ) -> PaymentConfirmation:
        """Confirm a payment method with the provider.

        Must contact the provider (or verify a signed result) before
        returning ``eligible=True``.
        """

    @abstractmethod
    async def check_eligibility(self, user_id: str) -> PaymentConfirmation:
        """Re-check eligibility for an existing payment method."""


class SandboxPaymentProvider(PaymentProvider):
    """Development-only provider that never charges real money.

    It simulates a hosted setup flow.  It is strictly unavailable in
    production mode so a sandbox can never be mistaken for a real
    payment registration.
    """

    name = "sandbox"

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, str]] = {}

    def _require_dev(self) -> None:
        if auth_settings.is_production:
            raise PaymentError("Sandbox payment provider is unavailable in production")

    async def create_setup_session(self, user_id: str) -> PaymentSetupSession:
        self._require_dev()
        session_id = str(uuid.uuid4())
        client_secret = f"test_setup_secret_{secrets.token_urlsafe(24)}"
        self._sessions[session_id] = {"user_id": user_id, "status": "pending"}
        return PaymentSetupSession(
            provider=self.name,
            session_id=session_id,
            client_secret=client_secret,
            setup_url=None,
        )

    async def confirm_setup(
        self,
        session_id: str,
        payment_method_token: str,
    ) -> PaymentConfirmation:
        self._require_dev()
        session = self._sessions.get(session_id)
        if not session:
            return PaymentConfirmation(eligible=False, reason="Unknown setup session")
        # A sandbox token is any non-empty string prefixed with "test_".
        if not payment_method_token.startswith("test_"):
            return PaymentConfirmation(
                eligible=False,
                reason="Sandbox payment method token must start with 'test_'",
            )
        session["status"] = "confirmed"
        session["payment_method_token"] = payment_method_token
        return PaymentConfirmation(
            eligible=True,
            provider_customer_ref=f"cust_sandbox_{session_id[:12]}",
            provider_payment_method_ref=f"pm_sandbox_{payment_method_token[5:17]}",
        )

    async def check_eligibility(self, user_id: str) -> PaymentConfirmation:
        self._require_dev()
        for session in self._sessions.values():
            if session.get("user_id") == user_id and session.get("status") == "confirmed":
                return PaymentConfirmation(eligible=True)
        return PaymentConfirmation(eligible=False, reason="No confirmed sandbox method")


class StripePaymentProvider(PaymentProvider):
    """Production provider backed by Stripe.

    Requires the ``stripe`` package and valid API credentials.  When
    unavailable it reports a truthful not-configured state.
    """

    name = "stripe"

    def _require_configured(self) -> None:
        if not auth_settings.stripe_configured:
            raise PaymentError("Stripe payment provider is not configured")
        try:
            import stripe  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on env
            raise PaymentError("Stripe package is not installed") from exc

    async def create_setup_session(self, user_id: str) -> PaymentSetupSession:
        self._require_configured()
        # A full implementation would create a Stripe SetupIntent and
        # return its client secret for Stripe.js.  The package is not
        # installed in this environment, so we surface the blocker.
        raise PaymentError("Stripe payment provider is not installed")

    async def confirm_setup(
        self,
        session_id: str,
        payment_method_token: str,
    ) -> PaymentConfirmation:
        self._require_configured()
        raise PaymentError("Stripe payment provider is not installed")

    async def check_eligibility(self, user_id: str) -> PaymentConfirmation:
        self._require_configured()
        raise PaymentError("Stripe payment provider is not installed")


class NotConfiguredPaymentProvider(PaymentProvider):
    """Provider used when no payment provider is configured.

    It truthfully reports that payment registration is unavailable
    and never grants eligibility.
    """

    name = "none"

    async def create_setup_session(self, user_id: str) -> PaymentSetupSession:
        raise PaymentError("No payment provider is configured")

    async def confirm_setup(
        self,
        session_id: str,
        payment_method_token: str,
    ) -> PaymentConfirmation:
        return PaymentConfirmation(eligible=False, reason="No payment provider configured")

    async def check_eligibility(self, user_id: str) -> PaymentConfirmation:
        return PaymentConfirmation(
            eligible=False,
            reason="No payment provider configured",
        )


def get_payment_provider() -> PaymentProvider:
    """Return the payment provider selected by configuration."""
    kind = auth_settings.payment_provider_kind
    if kind == "sandbox" and auth_settings.payment_provider_configured:
        return SandboxPaymentProvider()
    if kind == "stripe" and auth_settings.stripe_configured:
        return StripePaymentProvider()
    return NotConfiguredPaymentProvider()
