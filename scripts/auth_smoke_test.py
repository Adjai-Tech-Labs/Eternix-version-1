"""End-to-end smoke test of the mandatory registration state machine."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eternix.auth.service import AuthError, AuthService
from eternix.auth.store import AuthStore
from eternix.auth.tokens import decode_access_token

DB = Path(__file__).resolve().parents[1] / "data" / "auth-smoke.db"
DB.parent.mkdir(parents=True, exist_ok=True)
if DB.exists():
    DB.unlink()

failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


async def main() -> None:
    store = AuthStore(db_path=DB)
    service = AuthService(store)

    # 1. Dev registration
    payload = service.register_dev_identity(ip_address="127.0.0.1")
    user_id = payload["user"]["id"]
    check("dev registration returns onboarding session", payload["session_purpose"] == "onboarding")
    check("dev registration creates registration_incomplete account",
          payload["user"]["account_state"] == "registration_incomplete")

    # 2. Complete registration with username, password, email
    payload = service.complete_registration(
        user_id, "smoketester", "Sup3rSecret!", email="smoke@example.com"
    )
    check("complete_registration advances to awaiting_verification",
          payload["user"]["account_state"] == "awaiting_verification")
    check("username recorded", payload["user"]["username"] == "smoketester")

    # Username uniqueness enforced
    payload2 = service.register_dev_identity()
    try:
        service.complete_registration(payload2["user"]["id"], "smoketester", "Sup3rSecret!")
        check("duplicate username rejected", False)
    except AuthError as exc:
        check("duplicate username rejected", exc.code == "invalid_username")

    # Weak password rejected
    try:
        service.complete_registration(payload2["user"]["id"], "smoketester2", "weak")
        check("weak password rejected", False)
    except AuthError as exc:
        check("weak password rejected", exc.code == "weak_password")

    # 3. Contact verification
    info = service.request_verification(user_id, ip_address="127.0.0.1")
    code = info.get("dev_code")
    check("verification code delivered in dev mode", bool(code), f"info={info}")
    check("contact masked in response", info["contact"] == "s***@example.com", info["contact"])

    try:
        service.confirm_verification(user_id, "000000")
        check("wrong OTP rejected", False)
    except AuthError as exc:
        check("wrong OTP rejected", exc.code == "invalid_code")

    payload = service.confirm_verification(user_id, code)
    check("verification completes to awaiting_payment_method",
          payload["user"]["account_state"] == "awaiting_payment_method")

    # 4. Payment registration (sandbox provider)
    setup = service.create_payment_setup(user_id)
    check("payment setup returns sandbox session",
          setup["provider"] == "sandbox" and bool(setup["setup_id"]))
    payload = service.confirm_payment_setup(user_id, setup["setup_id"])
    check("payment confirmation activates account",
          payload["user"]["account_state"] == "active")
    check("payment eligibility recorded", payload["user"]["payment_eligibility"] == "eligible")
    check("active account issues access session", payload["session_purpose"] == "access")

    claims = decode_access_token(payload["access_token"])
    check("access token carries session + purpose",
          claims.get("purpose") == "access" and bool(claims.get("sid")))

    # 5. Login
    login = service.login("smoketester", "Sup3rSecret!", ip_address="127.0.0.1")
    check("login succeeds with issued credentials", login["session_purpose"] == "access")

    try:
        service.login("smoketester", "wrong-password")
        check("wrong password rejected", False)
    except AuthError as exc:
        check("wrong password rejected", exc.code == "invalid_credentials")

    # 6. Refresh rotation + reuse detection
    refresh = service.refresh(login["refresh_token"])
    check("refresh rotates credentials", refresh["access_token"] != login["access_token"])

    try:
        service.refresh(login["refresh_token"])
        check("refresh reuse detected", False)
    except AuthError as exc:
        check("refresh reuse detected", exc.code == "reuse_detected")

    events = [e["event_type"] for e in store.audit_events_for_user(user_id, limit=200)]
    check("reuse event audited", "refresh_reuse_detected" in events)

    # 7. Password change revokes sessions
    service.login("smoketester", "Sup3rSecret!")
    service.change_password(user_id, "Sup3rSecret!", "N3wSecret!Long")
    try:
        service.login("smoketester", "Sup3rSecret!")
        check("old password rejected after change", False)
    except AuthError:
        check("old password rejected after change", True)
    login3 = service.login("smoketester", "N3wSecret!Long")
    check("new password accepted", login3["session_purpose"] == "access")

    # 8. Password reset flow
    reset = service.request_password_reset("smoketester")
    check("password reset requested generically",
          reset["status"] == "if_the_account_exists_a_reset_was_requested")
    dev_token = reset.get("dev_code")
    check("reset token delivered in dev mode", bool(dev_token))
    result = service.reset_password(dev_token, "ResetPass!9")
    check("password reset completes", result["status"] == "password_reset")
    login4 = service.login("smoketester", "ResetPass!9")
    check("reset password accepted", login4["session_purpose"] == "access")

    # 9. Rate limiting on login
    for _ in range(10):
        try:
            service.login("smoketester", "definitely-wrong")
        except AuthError:
            pass
    try:
        service.login("smoketester", "ResetPass!9")
        check("login lockout enforced", False)
    except AuthError as exc:
        check("login lockout enforced", exc.code in ("locked", "rate_limited"), exc.code)

    # 10. Logout revokes the session
    service.logout(user_id, login4["session_id"], login4["refresh_token"])
    session = store.get_session(login4["session_id"])
    check("logout revokes session", session["revoked"] is True)

    # 11. Account deletion
    result = service.delete_account(user_id)
    check("account deletion requested", result["status"] == "deletion_pending")
    user = store.get_user(user_id)
    check("account marked deletion_pending", user["status"].value == "deletion_pending")

    # 12. Audit trail
    events = [e["event_type"] for e in store.audit_events_for_user(user_id, limit=200)]
    expected = [
        "registration_started",
        "registration_credentials_set",
        "verification_requested",
        "verification_completed",
        "payment_eligibility_granted",
        "account_activated",
        "login_succeeded",
    ]
    missing = [e for e in expected if e not in events]
    check("audit trail records lifecycle events", not missing, f"missing={missing}")

    store.cleanup_expired()
    print()
    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        sys.exit(1)
    print("ALL SMOKE TESTS PASSED")


asyncio.run(main())
