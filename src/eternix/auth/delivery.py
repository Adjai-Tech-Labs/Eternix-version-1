"""One-time-password delivery for contact verification.

Supports SMTP, SendGrid (email) and Twilio (SMS).  When no delivery
provider is configured the service reports that fact truthfully and
the caller keeps the account restricted.  A fixed development OTP
may be configured for local testing only; it is disabled in
production.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from eternix.auth.config import auth_settings
from eternix.auth.store import AuthStore


class DeliveryError(Exception):
    """Raised when an OTP cannot be delivered."""


def _now() -> datetime:
    return datetime.now(UTC)


def _expires() -> datetime:
    return _now() + timedelta(seconds=auth_settings.otp_expiry_seconds)


def generate_otp() -> str:
    """Generate a numeric OTP of the configured length."""
    if auth_settings.dev_otp_enabled:
        return auth_settings.dev_otp
    return "".join(secrets.choice("0123456789") for _ in range(auth_settings.otp_length))


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# EmailJS delivery
# ---------------------------------------------------------------------------

EMAILJS_SEND_URL = "https://api.emailjs.com/api/v1.0/email/send"


def send_emailjs_email(to: str, code: str) -> None:
    """Send a verification email through the EmailJS API.

    Uses the server-side EmailJS send endpoint with the
    configured service, template and credentials.  Raises
    ``DeliveryError`` for missing configuration, transport
    failures and EmailJS rejections.  Credentials and the
    verification code are never included in error messages.
    """
    import httpx

    service_id = auth_settings.emailjs_service_id
    template_id = auth_settings.emailjs_template_id
    public_key = auth_settings.emailjs_public_key
    if not service_id or not template_id or not public_key:
        raise DeliveryError("EmailJS delivery is not fully configured")

    expires_in_minutes = max(1, round(auth_settings.otp_expiry_seconds / 60))
    payload: dict[str, Any] = {
        "service_id": service_id,
        "template_id": template_id,
        "user_id": public_key,
        "template_params": {
            "to_email": to,
            "verification_code": code,
            "expires_in_minutes": str(expires_in_minutes),
        },
    }
    private_key = auth_settings.emailjs_private_key.get_secret_value()
    if private_key:
        # The private key enables server-side sending with
        # higher delivery limits than the public key alone.
        payload["access_token"] = private_key

    try:
        response = httpx.post(EMAILJS_SEND_URL, json=payload, timeout=20.0)
    except httpx.TimeoutException as exc:
        raise DeliveryError("EmailJS request timed out") from exc
    except httpx.TransportError as exc:
        raise DeliveryError("EmailJS could not be reached") from exc

    if response.status_code >= 400:
        detail = _emailjs_message(response)
        raise DeliveryError(
            f"EmailJS rejected the send request "
            f"(HTTP {response.status_code}"
            + (f": {detail}" if detail else "")
            + ")"
        )

    # EmailJS confirms a successful send with HTTP 200 and
    # {"message": "OK"}.  Anything else is not a confirmed
    # delivery and is treated as a failure.
    if response.status_code != 200 or _emailjs_message(response) != "OK":
        raise DeliveryError("EmailJS did not confirm delivery")


def _emailjs_message(response: Any) -> str:
    """Extract the (redacted) message from an EmailJS response."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        return body["message"]
    return ""


async def deliver_otp(
    store: AuthStore,
    *,
    contact_value: str,
    channel: str,
    purpose: str,
    ip_address: str | None = None,
) -> str:
    """Create an OTP challenge and deliver it via the configured provider.

    Returns the challenge id.  Raises ``DeliveryError`` when no
    provider is configured and no development bypass is available.
    """
    from eternix.auth.models import OTPChannel, OTPPurpose

    code = generate_otp()
    expires_at = _expires()

    challenge = store.create_otp_challenge(
        contact_value=contact_value,
        channel=OTPChannel(channel),
        purpose=OTPPurpose(purpose),
        code_hash=hash_code(code),
        max_attempts=auth_settings.otp_max_attempts,
        expires_at=expires_at,
        ip_address=ip_address,
    )

    if auth_settings.dev_otp_enabled:
        # Development bypass: the code is fixed and not delivered.
        return challenge["id"]

    if channel == OTPChannel.EMAIL.value and auth_settings.email_configured:
        await _deliver_email(contact_value, code)
    elif channel == OTPChannel.PHONE.value and auth_settings.sms_configured:
        await _deliver_sms(contact_value, code)
    else:
        raise DeliveryError(
            f"No {channel} delivery provider is configured for verification"
        )

    return challenge["id"]


async def _deliver_email(to: str, code: str) -> None:
    provider = auth_settings.email_provider
    if provider == "smtp":
        await _send_smtp_email(to, code)
    elif provider == "sendgrid":
        await _send_sendgrid_email(to, code)
    elif provider == "emailjs":
        send_emailjs_email(to, code)
    else:
        raise DeliveryError("Email provider not configured")


async def _send_smtp_email(to: str, code: str) -> None:
    import asyncio

    message = (
        f"Subject: Your ETERNIX verification code\r\n"
        f"From: {auth_settings.smtp_from}\r\n"
        f"To: {to}\r\n\r\n"
        f"Your ETERNIX verification code is: {code}\r\n"
    )
    try:
        _reader, writer = await asyncio.open_connection(
            auth_settings.smtp_host, auth_settings.smtp_port
        )
        writer.write(message.encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    except OSError as exc:
        raise DeliveryError(f"SMTP delivery failed: {exc}") from exc


async def _send_sendgrid_email(to: str, code: str) -> None:
    import httpx

    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": auth_settings.smtp_from},
        "subject": "Your ETERNIX verification code",
        "content": [{"type": "text/plain", "value": f"Your code is: {code}"}],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={"Authorization": f"Bearer {auth_settings.sendgrid_api_key.get_secret_value()}"},
        )
    if response.status_code >= 400:
        raise DeliveryError(f"SendGrid delivery failed: HTTP {response.status_code}")


async def _deliver_sms(to: str, code: str) -> None:
    import httpx

    payload = {
        "To": to,
        "From": auth_settings.twilio_from_number,
        "Body": f"Your ETERNIX verification code is: {code}",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{auth_settings.twilio_account_sid}/Messages.json",
            data=payload,
            auth=(auth_settings.twilio_account_sid, auth_settings.twilio_auth_token.get_secret_value()),
        )
    if response.status_code >= 400:
        raise DeliveryError(f"SMS delivery failed: HTTP {response.status_code}")


def verify_otp(store: AuthStore, challenge_id: str, code: str) -> bool:
    """Verify an OTP against a stored challenge.

    The challenge must be unconsumed, unexpired, and within its
    attempt limit.  Successful verification consumes the challenge.
    """
    challenge = store.get_otp_challenge(challenge_id)
    if not challenge:
        return False
    if challenge["consumed"]:
        return False
    expires_at = challenge["expires_at"]
    if expires_at and expires_at < _now():
        return False
    if challenge["attempts"] >= challenge["max_attempts"]:
        return False

    if hash_code(code) != challenge["code_hash"]:
        store.increment_otp_attempts(challenge_id)
        return False

    store.consume_otp_challenge(challenge_id)
    return True
