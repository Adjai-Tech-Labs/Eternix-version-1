"""End-to-end journey verification against a live ETERNIX server.

Boots a real Uvicorn server on an isolated temporary database and exercises
the complete authenticated path: registration -> contact verification ->
payment eligibility -> protected workspace -> agent objective -> real tool
execution -> conversation persistence -> adversarial/authorization checks.

Uses the sandbox payment provider and development auth mode (no external
services). Performs NO mocking of the backend: the same FastAPI app,
orchestrator, tools, and persistence used in production are exercised over
real HTTP.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(base: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base}/health", timeout=2.0)
            if r.status_code == 200:
                return
            last = f"status={r.status_code}"
        except Exception as exc:  # polling until ready
            last = repr(exc)
        time.sleep(0.5)
    raise RuntimeError(f"server did not become healthy: {last}")


@pytest.fixture(scope="module")
def live_server():
    """Start a real ETERNIX API server on an isolated data dir."""
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="eternix_e2e_")
    env = dict(os.environ)
    # Isolate all persistence so the test never touches real user data.
    env["DATA_DIR"] = tmp
    env["DB_PATH"] = str(Path(tmp) / "eternix.db")
    env["QDRANT_PATH"] = str(Path(tmp) / "qdrant")
    env["ETERNIX_AUTH_AUTH_DB_PATH"] = str(Path(tmp) / "auth.db")
    env["ETERNIX_AUTH_MODE"] = "development"
    env["ETERNIX_AUTH_PAYMENT_PROVIDER"] = "sandbox"
    env["ETERNIX_AUTH_EMAIL_PROVIDER"] = "none"
    env["ETERNIX_AUTH_JWT_KEY"] = "e2e-test-signing-key"
    env["ETERNIX_AUTH_SESSION_KEY"] = "e2e-test-session-key"
    env["API_HOST"] = "127.0.0.1"
    env["API_PORT"] = str(port)

    cmd = [
        sys.executable, "-m", "uvicorn", "eternix.api.server:app",
        "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
    ]
    proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(base)
        yield base, tmp
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _register_and_activate(client: httpx.Client, base: str, tag: str) -> dict:
    """Drive the mandatory onboarding state machine and return credentials."""
    r = client.post(f"{base}/api/auth/register/dev")
    assert r.status_code == 200, r.text
    data = r.json()
    access = data["access_token"]
    user_id = data["user"]["id"]
    assert data["session_purpose"] == "onboarding"
    assert data["user"]["account_state"] == "registration_incomplete"

    headers = {"Authorization": f"Bearer {access}"}
    r = client.post(
        f"{base}/api/auth/register/complete",
        json={"username": f"user_{tag}", "password": "Sup3rSecret!x", "email": f"{tag}@example.com"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    access = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    assert r.json()["user"]["account_state"] == "awaiting_verification"

    r = client.post(f"{base}/api/auth/verify/request", headers=headers)
    assert r.status_code == 200, r.text
    code = r.json().get("dev_code")
    assert code, "dev verification code must be returned in development mode"
    r = client.post(f"{base}/api/auth/verify/confirm", json={"code": code}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["account_state"] == "awaiting_payment_method"

    r = client.post(f"{base}/api/auth/payment/setup", headers=headers)
    assert r.status_code == 200, r.text
    setup_id = r.json()["setup_id"]
    r = client.post(f"{base}/api/auth/payment/confirm", json={"setup_id": setup_id}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["account_state"] == "active"
    assert body["user"]["payment_eligibility"] == "eligible"

    return {
        "access_token": body["access_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user_id": user_id,
        "username": f"user_{tag}",
        "password": "Sup3rSecret!x",
    }



def test_health_reports_version(live_server):
    base, _ = live_server
    r = httpx.get(f"{base}/health", timeout=5)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unauthenticated_request_is_rejected(live_server):
    base, _ = live_server
    with httpx.Client() as client:
        r = client.get(f"{base}/api/conversations")
        assert r.status_code == 401


def test_ineligible_account_cannot_reach_workspace(live_server):
    """An authenticated but unpaid account must be denied protected routes."""
    base, _ = live_server
    with httpx.Client() as client:
        r = client.post(f"{base}/api/auth/register/dev")
        access = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {access}"}
        r = client.get(f"{base}/api/conversations", headers=headers)
        assert r.status_code == 403, r.text


def test_full_journey_and_real_tool_execution(live_server):
    base, tmp = live_server
    with httpx.Client() as client:
        creds = _register_and_activate(client, base, "journey")
        headers = creds["headers"]

        r = client.get(f"{base}/api/conversations", headers=headers)
        assert r.status_code == 200, r.text

        r = client.post(f"{base}/api/workspace/register", json={"path": tmp, "name": "e2e"}, headers=headers)
        assert r.status_code == 200, r.text
        r = client.post(f"{base}/api/workspace/set-active", json={"path": tmp}, headers=headers)
        assert r.status_code == 200, r.text

        # Real tool execution: create a file via the filesystem tool.
        r = client.post(
            f"{base}/api/tools/fs.write/execute",
            json={"path": "hello_e2e.txt", "content": "hello from eternix"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
        assert (Path(tmp) / "hello_e2e.txt").read_text() == "hello from eternix"

        # Real tool execution: read it back.
        r = client.post(f"{base}/api/tools/fs.read/execute", json={"path": "hello_e2e.txt"}, headers=headers)
        assert r.status_code == 200
        assert "hello from eternix" in r.json()["output"]["content"]

        # Agent objective that routes to a real tool via the fallback planner.
        r = client.post(
            f"{base}/api/objectives",
            json={"user_input": "list the files in the current directory"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        objective_id = r.json()["id"]

        r = client.post(f"{base}/api/objectives/{objective_id}/run", headers=headers)
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["details"]["total"] >= 1
        statuses = {t["status"] for t in run["details"]["_tasks"]}
        assert "completed" in statuses, run["details"]["_tasks"]

        # Conversation persistence.
        r = client.post(f"{base}/api/conversations", json={"title": "E2E chat"}, headers=headers)
        assert r.status_code == 200
        conv_id = r.json()["id"]
        client.post(f"{base}/api/conversations/{conv_id}/messages", json={"role": "user", "content": "hi"}, headers=headers)
        client.post(f"{base}/api/conversations/{conv_id}/messages", json={"role": "assistant", "content": "hello"}, headers=headers)
        r = client.get(f"{base}/api/conversations/{conv_id}", headers=headers)
        assert r.status_code == 200
        assert len(r.json()["messages"]) == 2


def test_path_traversal_is_blocked(live_server):
    """Filesystem access must refuse to escape the authorized workspace."""
    base, tmp = live_server
    with httpx.Client() as client:
        creds = _register_and_activate(client, base, "traversal")
        headers = creds["headers"]
        client.post(f"{base}/api/workspace/register", json={"path": tmp, "name": "e2e"}, headers=headers)
        client.post(f"{base}/api/workspace/set-active", json={"path": tmp}, headers=headers)
        r = client.get(f"{base}/api/workspace/read", params={"path": "../../../etc/passwd"}, headers=headers)
        assert r.status_code == 403, r.text


def test_intelligence_endpoints_are_truthful(live_server):
    """Index endpoints must not fabricate a successful background index."""
    base, _ = live_server
    with httpx.Client() as client:
        creds = _register_and_activate(client, base, "intel")
        headers = creds["headers"]
        r = client.post(f"{base}/api/intelligence/index", json={"path": "."}, headers=headers)
        assert r.status_code == 200
        assert r.json()["indexed"] is False
        r = client.get(f"{base}/api/intelligence/status", headers=headers)
        assert r.json()["indexed"] is False




def test_fs_tool_cannot_escape_workspace(live_server):
    """Regression (DEF-005): fs.write must confine to the active workspace.

    Previously fs.* tools resolved paths against the server CWD and could
    write anywhere on the host while still reporting success. The tool must
    now refuse to write outside the authorized workspace and must NOT create
    the file.
    """
    base, tmp = live_server
    with httpx.Client() as client:
        creds = _register_and_activate(client, base, "escape")
        headers = creds["headers"]
        client.post(f"{base}/api/workspace/register", json={"path": tmp, "name": "e2e"}, headers=headers)
        client.post(f"{base}/api/workspace/set-active", json={"path": tmp}, headers=headers)

        outside = Path(tmp).parent / f"eternix_escape_{os.getpid()}.txt"
        if outside.exists():
            outside.unlink()
        try:
            r = client.post(
                f"{base}/api/tools/fs.write/execute",
                json={"path": str(outside), "content": "SHOULD NOT BE WRITTEN"},
                headers=headers,
            )
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is False, body
            assert not outside.exists(), "fs.write escaped the workspace boundary!"
        finally:
            if outside.exists():
                outside.unlink()


def test_fs_write_stays_inside_workspace(live_server):
    """A legitimate in-workspace write must land inside the workspace."""
    base, tmp = live_server
    with httpx.Client() as client:
        creds = _register_and_activate(client, base, "inside")
        headers = creds["headers"]
        client.post(f"{base}/api/workspace/register", json={"path": tmp, "name": "e2e"}, headers=headers)
        client.post(f"{base}/api/workspace/set-active", json={"path": tmp}, headers=headers)
        r = client.post(
            f"{base}/api/tools/fs.write/execute",
            json={"path": "inside_ok.txt", "content": "contained"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert (Path(tmp) / "inside_ok.txt").read_text() == "contained"
