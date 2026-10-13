"""Payment-method registration.

A pluggable provider interface with two implementations:

* ``SandboxPaymentProvider`` - development provider. It never contacts a
  payment network and never charges real money. Setup sessions are
  confirmed locally and only mark the *eligibility prerequisite*
  complete. It is the default in development mode.
* ``StripePaymentProvider`` - production provider using Stripe Setup
  Intents. Only active when STRIPE_SECRET_KEY is configured.

The mandatory payment gate is enforced centrally by
``eternix.auth.service``: an account only becomes eligible after the
provider authoritatively confirms the setup result.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import httpx

from eternix.auth.config import auth_settings


@dataclass
class SetupSession:
    provider: str
    setup_id: str
    status: str
    url: str | None = None
    client_secret: str | None = None
    metadata: dict = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class PaymentProviderError(RuntimeError):
    pass


class SandboxPaymentProvider:
    """Development-only provider. Never touches a payment network."""

    name = "sandbox"

    def create_setup_session(self, user_id: str) -> SetupSession:
        setup_id = str(uuid4())
        return SetupSession(
            provider=self.name,
            setup_id=setup_id,
            status="awaiting_confirmation",
            metadata={
                "user_id": user_id,
                "sandbox": True,
                "note": "Sandbox registration only; no payment method is collected and no charge is possible.",
            },
        )

    def confirm_setup(self, setup_id: str, user_id: str) -> SetupSession:
        # In sandbox mode confirmation is authoritative but simulated:
        # it records eligibility without collecting any payment data.
        return SetupSession(
            provider=self.name,
            setup_id=setup_id,
            status="confirmed",
            metadata={"user_id": user_id, "sandbox": True, "charged": False},
        )

    def verify_setup(self, setup_id: str, user_id: str) -> bool:
        return bool(setup_id)


class StripePaymentProvider:
    """Production provider using Stripe Setup Intents (requires keys)."""

    name = "stripe"

    def __init__(self) -> None:
        self.secret_key = auth_settings.stripe_secret_key.get_secret_value()
        self.webhook_secret = auth_settings.stripe_webhook_secret.get_secret_value()
        if not self.secret_key:
            raise PaymentProviderError("Stripe provider is not configured")

    def create_setup_session(self, user_id: str) -> SetupSession:
        response = httpx.post(
            f"{auth_settings.stripe_api_base}/setup_intents",
            headers={"Authorization": f"Bearer {self.secret_key}"},
            data={"payment_method_types[]": "card", "metadata[eternix_user_id]": user_id},
            timeout=30,
        )
        if response.status_code >= 400:
            raise PaymentProviderError("payment provider unavailable")
        body = response.json()
        return SetupSession(
            provider=self.name,
            setup_id=body.get("id", ""),
            status="awaiting_confirmation",
            client_secret=body.get("client_secret"),
        )

    def confirm_setup(self, setup_id: str, user_id: str) -> SetupSession:
        response = httpx.get(
            f"{auth_settings.stripe_api_base}/setup_intents/{setup_id}",
            headers={"Authorization": f"Bearer {self.secret_key}"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise PaymentProviderError("payment provider unavailable")
        body = response.json()
        status = body.get("status")
        return SetupSession(
            provider=self.name,
            setup_id=setup_id,
            status=status or "unknown",
            metadata={"payment_method": body.get("payment_method")},
        )

    def verify_setup(self, setup_id: str, user_id: str) -> bool:
        session = self.confirm_setup(setup_id, user_id)
        return session.status == "succeeded"


def get_payment_provider() -> SandboxPaymentProvider | StripePaymentProvider:
    """Return the configured payment provider.

    Sandbox is the default in development. It never contacts a payment
    network and never charges real money. In production a real provider
    (Stripe) must be configured; the sandbox may only be selected
    explicitly by the operator.
    """
    provider_name = auth_settings.payment_provider.lower()
    if provider_name == "stripe":
        return StripePaymentProvider()
    if provider_name == "sandbox":
        return SandboxPaymentProvider()
    raise PaymentProviderError(f"Unknown payment provider: {provider_name}")


def payment_provider_status() -> dict:
    """Truthful description of the configured payment provider."""
    name = auth_settings.payment_provider.lower()
    if name == "stripe":
        configured = auth_settings.stripe_configured
        return {
            "provider": "stripe",
            "configured": configured,
            "sandbox": not configured,
            "charges_real_money": configured,
            "message": (
                "Stripe is configured"
                if configured
                else "Stripe keys are not configured; no real charges can occur"
            ),
        }
    if name == "sandbox":
        return {
            "provider": "sandbox",
            "configured": True,
            "sandbox": True,
            "charges_real_money": False,
            "message": "Sandbox payment registration is active; no real payment method is collected and no charge occurs",
        }
    return {
        "provider": "none",
        "configured": False,
        "sandbox": False,
        "charges_real_money": False,
        "message": "No payment provider is configured; payment registration is unavailable",
    }
