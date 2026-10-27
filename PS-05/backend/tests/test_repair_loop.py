"""
test_repair_loop.py — Comprehensive tests for Phase 6B Bounded Repair Loop

Covers:
  1. Successful verified repair (mock provider + mocked verifier -> FIX_VERIFIED)
  2. Invalid AI patch (validation/application errors -> FIX_INCOMPLETE after exhaustion)
  3. AI provider not configured (BLOCKED immediately)
  4. AI provider timeout (retryable; eventually FIX_INCOMPLETE)
  5. Original failure persists (FIX_INCOMPLETE)
  6. Retry limit exhausted (FIX_INCOMPLETE)
  7. BLOCKED Docker/invalid session
  8. Duplicate/concurrent repair prevention
  9. Secret redaction in feedback context
 10. Evidence size bounding
 11. No host execution (no subprocess.run calls except through PatchVerifier)
 12. Pre-patch reproduction evidence required
 13. Security violation stops loop immediately (BLOCKED)
 14. API endpoint: /patch/repair-loop (session not found, no workspace, no repro, success)
 15. No real AI API calls in any test
"""

import os
import uuid
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app, sandbox_service
from app.patch_provider import MockPatchProvider, PatchProviderError
from app.patch_verifier import PatchVerificationOutcome, PatchVerificationResult
from app.repair_loop import (
    MAX_REPAIR_ATTEMPTS,
    RepairLoopError,
    RepairLoopService,
    RepairOutcome,
    _acquire_session_lock,
    _release_session_lock,
    _session_locks,
    _session_locks_meta,
)
from app.sandbox_service import SandboxSessionData
from app.schemas import (
    CandidateLocation,
    LocalizationConfidence,
    LocalizationResult,
    ReproductionOutcome,
    ReproductionResult,
    SandboxState,
)

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared Fixtures
# ---------------------------------------------------------------------------

SAMPLE_LOCALIZATION = LocalizationResult(
    candidate_locations=[
        CandidateLocation(
            file_path="app/calculator.py",
            line_number=10,
            function_name="divide",
            evidence_snippet="return a / b",
            source_type="stack_trace",
            relevance_score=0.95,
        )
    ],
    detected_exceptions=["ZeroDivisionError"],
    confidence=LocalizationConfidence.HIGH,
    confidence_explanation="High confidence: verified stack trace.",
    total_evidence_lines_analyzed=5,
)

VALID_DIFF = (
    "--- a/app/calculator.py\n"
    "+++ b/app/calculator.py\n"
    "@@ -10,3 +10,5 @@\n"
    "+    if b == 0:\n"
    "+        raise ValueError('Cannot divide by zero')\n"
    "     return a / b\n"
)


def _mk_verifier_result(outcome: PatchVerificationOutcome, details: str = "ok") -> PatchVerificationResult:
    return PatchVerificationResult(
        outcome=outcome,
        exit_code=0 if outcome == PatchVerificationOutcome.FIX_VERIFIED else 1,
        timed_out=False,
        stdout="",
        stderr="",
        duration_ms=100.0,
        test_command="pytest",
        pre_patch_observed=True,
        details=details,
    )


def _register_session(tmp_path: Path, repro_outcome: ReproductionOutcome = ReproductionOutcome.REPRODUCED) -> str:
    """Register a fake sandbox session with the given reproduction outcome."""
    session_id = uuid.uuid4().hex[:8]
    session = SandboxSessionData(
        session_id=session_id,
        repo_url="https://github.com/testorg/repo",
        issue_url="https://github.com/testorg/repo/issues/1",
    )
    session.state = SandboxState.COMPLETED
    session.workspace_path = str(tmp_path)
    session.reproduction_result = ReproductionResult(
        outcome=repro_outcome,
        command="pytest",
        exit_code=0 if repro_outcome != ReproductionOutcome.REPRODUCED else 1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
        details="Reproduced" if repro_outcome == ReproductionOutcome.REPRODUCED else "Not reproduced",
    )
    sandbox_service.sessions[session_id] = session
    return session_id


# ---------------------------------------------------------------------------
# 1. Successful Verified Repair
# ---------------------------------------------------------------------------

def test_repair_loop_fix_verified(tmp_path: Path):
    """Full successful repair: mock provider generates valid diff, verifier returns FIX_VERIFIED."""
    # Create the target file the diff expects to patch
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    mock_verifier = MagicMock()
    mock_verifier.verify_patch.return_value = _mk_verifier_result(PatchVerificationOutcome.FIX_VERIFIED)

    provider = MockPatchProvider(custom_diff=VALID_DIFF)

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=mock_verifier)
        result = svc.run(
            session_id="test-session",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )

    assert result.outcome == RepairOutcome.FIX_VERIFIED
    assert len(result.attempts) == 1
    assert result.attempts[0].verification_outcome == PatchVerificationOutcome.FIX_VERIFIED
    assert result.real_ai_call_made is False


# ---------------------------------------------------------------------------
# 2. Invalid AI Patch (unsafe diff rejected by PatchApplier)
# ---------------------------------------------------------------------------

def test_repair_loop_invalid_patch_exhausts_attempts(tmp_path: Path):
    """Unsafe diffs from provider (traversal) are rejected by PatchValidator; loop BLOCKED."""
    traversal_diff = (
        "--- a/../../etc/passwd\n"
        "+++ b/../../etc/passwd\n"
        "@@ -1,1 +1,1 @@\n"
        "+evil\n"
    )
    provider = MockPatchProvider(custom_diff=traversal_diff)

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=MagicMock())
        result = svc.run(
            session_id="test-session",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )

    # Traversal is a security violation -> BLOCKED immediately
    assert result.outcome == RepairOutcome.BLOCKED
    # Final details should mention security violation or traversal
    assert (
        "security violation" in result.final_details.lower()
        or "traversal" in result.final_details.lower()
        or "forbidden" in result.final_details.lower()
    )


# ---------------------------------------------------------------------------
# 3. AI Provider Not Configured
# ---------------------------------------------------------------------------

def test_repair_loop_ai_provider_not_configured(tmp_path: Path, monkeypatch):
    """When AI provider is requested but not configured, BLOCKED immediately, no network call."""
    monkeypatch.delenv("AI_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    svc = RepairLoopService(patch_verifier=MagicMock())
    with patch("httpx.Client") as mock_client:
        result = svc.run(
            session_id="test-session",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
            provider_name="ai",
        )
        mock_client.assert_not_called()

    assert result.outcome == RepairOutcome.BLOCKED
    assert "not configured" in result.final_details.lower() or len(result.attempts) > 0


# ---------------------------------------------------------------------------
# 4. AI Provider Timeout (retryable; exhausts attempts -> FIX_INCOMPLETE)
# ---------------------------------------------------------------------------

def test_repair_loop_provider_timeout_retries_then_incomplete(tmp_path: Path):
    """Timeouts are retryable; after exhausting attempts, FIX_INCOMPLETE is returned."""
    provider = MagicMock()
    provider.propose_patch.side_effect = PatchProviderError(
        "AI provider request timed out after 30 seconds."
    )

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=MagicMock())
        result = svc.run(
            session_id="test-session",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
            provider_name="mock",
        )

    # All MAX_REPAIR_ATTEMPTS tried, each timed out
    assert result.outcome == RepairOutcome.FIX_INCOMPLETE
    assert len(result.attempts) == MAX_REPAIR_ATTEMPTS
    for a in result.attempts:
        assert "timed out" in a.validation_errors[0].lower() or "provider error" in a.validation_errors[0].lower()


# ---------------------------------------------------------------------------
# 5. Original Failure Persists
# ---------------------------------------------------------------------------

def test_repair_loop_original_failure_persists(tmp_path: Path):
    """When verifier returns FIX_INCOMPLETE, repair loop yields FIX_INCOMPLETE."""
    # Create the target file the diff expects to patch
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    provider = MockPatchProvider(custom_diff=VALID_DIFF)
    mock_verifier = MagicMock()
    mock_verifier.verify_patch.return_value = _mk_verifier_result(
        PatchVerificationOutcome.FIX_INCOMPLETE, "Original defect still observed."
    )

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=mock_verifier)
        result = svc.run(
            session_id="test-session",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )

    assert result.outcome == RepairOutcome.FIX_INCOMPLETE
    assert "persists" in result.final_details.lower() or "defect" in result.final_details.lower()


# ---------------------------------------------------------------------------
# 6. Retry Limit Exhausted (all attempts produce empty diff -> FIX_INCOMPLETE)
# ---------------------------------------------------------------------------

def test_repair_loop_retry_limit_exhausted(tmp_path: Path):
    """When every attempt produces an empty diff, all 3 are tried and FIX_INCOMPLETE returned."""
    provider = MockPatchProvider(custom_diff="")

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=MagicMock())
        result = svc.run(
            session_id="test-session",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )

    assert result.outcome == RepairOutcome.FIX_INCOMPLETE
    assert len(result.attempts) == MAX_REPAIR_ATTEMPTS
    assert all("empty" in a.validation_errors[0].lower() for a in result.attempts)


# ---------------------------------------------------------------------------
# 7. BLOCKED: Docker unavailable
# ---------------------------------------------------------------------------

def test_repair_loop_docker_blocked(tmp_path: Path):
    """When Docker is unavailable, verifier returns BLOCKED, loop halts immediately."""
    # Create the target file so patch application succeeds before verification
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    provider = MockPatchProvider(custom_diff=VALID_DIFF)
    mock_verifier = MagicMock()
    mock_verifier.verify_patch.return_value = _mk_verifier_result(
        PatchVerificationOutcome.BLOCKED, "Docker is not installed or daemon is unreachable."
    )

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=mock_verifier)
        result = svc.run(
            session_id="test-session",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )

    assert result.outcome == RepairOutcome.BLOCKED
    assert "blocked" in result.final_details.lower() or "docker" in result.final_details.lower()
    # Should only have made 1 attempt — BLOCKED stops the loop
    assert len(result.attempts) == 1


# ---------------------------------------------------------------------------
# 8. Duplicate / Concurrent Repair Prevention
# ---------------------------------------------------------------------------

def test_repair_loop_concurrent_prevention(tmp_path: Path):
    """A second concurrent repair loop call for the same session is immediately BLOCKED."""
    session_id = "concurrent-test-session"

    lock = _acquire_session_lock(session_id)
    assert lock is not None, "First acquire should succeed"

    try:
        svc = RepairLoopService(patch_verifier=MagicMock())
        result = svc.run(
            session_id=session_id,
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )
        assert result.outcome == RepairOutcome.BLOCKED
        assert "already running" in result.final_details.lower() or "concurrent" in result.final_details.lower()
    finally:
        _release_session_lock(session_id)


# ---------------------------------------------------------------------------
# 9. Secret Redaction in Feedback Context
# ---------------------------------------------------------------------------

def test_repair_loop_feedback_context_redacts_secrets(tmp_path: Path):
    """Secret tokens are scrubbed from evidence before being passed back to the provider."""
    from app.repair_loop import RepairLoopService, RepairAttempt

    attempt = RepairAttempt(attempt_number=1)
    failure_detail = "Auth failed: sk-supersecretkey12345678901234567890 was rejected"
    ctx = RepairLoopService._build_feedback_context({}, attempt, failure_detail)
    feedback = ctx.get("previous_attempt_failure", "")
    assert "sk-supersecretkey12345678901234567890" not in feedback
    assert "[REDACTED_SECRET]" in feedback


# ---------------------------------------------------------------------------
# 10. Evidence Size Bounding
# ---------------------------------------------------------------------------

def test_repair_loop_evidence_bounded(tmp_path: Path):
    """Feedback context fed back to provider is bounded by MAX_CONTEXT_FEEDBACK_CHARS."""
    from app.repair_loop import MAX_CONTEXT_FEEDBACK_CHARS, RepairLoopService, RepairAttempt

    attempt = RepairAttempt(attempt_number=1)
    giant_failure = "x" * 10_000
    ctx = RepairLoopService._build_feedback_context({}, attempt, giant_failure)
    feedback = ctx.get("previous_attempt_failure", "")
    assert len(feedback) <= MAX_CONTEXT_FEEDBACK_CHARS + 200  # small overhead for prefix text
    assert "[TRUNCATED]" in feedback


# ---------------------------------------------------------------------------
# 11. No Host Execution: patch application uses PatchApplier, not subprocess
# ---------------------------------------------------------------------------

def test_repair_loop_no_host_subprocess(tmp_path: Path):
    """Verify no subprocess.run or subprocess.Popen is called during the repair loop itself."""
    # Create the target file so patch application succeeds
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    provider = MockPatchProvider(custom_diff=VALID_DIFF)
    mock_verifier = MagicMock()
    mock_verifier.verify_patch.return_value = _mk_verifier_result(PatchVerificationOutcome.FIX_VERIFIED)

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        with patch("subprocess.run") as mock_subprocess_run:
            with patch("subprocess.Popen") as mock_popen:
                svc = RepairLoopService(patch_verifier=mock_verifier)
                result = svc.run(
                    session_id="test-no-host",
                    workspace_path=str(tmp_path),
                    localization=SAMPLE_LOCALIZATION,
                    pre_patch_outcome=ReproductionOutcome.REPRODUCED,
                    test_command="pytest",
                )
                # repair_loop.py itself never calls subprocess — Docker calls go through mock_verifier
                mock_subprocess_run.assert_not_called()
                mock_popen.assert_not_called()

    assert result.outcome == RepairOutcome.FIX_VERIFIED


# ---------------------------------------------------------------------------
# 12. Pre-Patch Reproduction Evidence Required
# ---------------------------------------------------------------------------

def test_repair_loop_requires_reproduced_evidence(tmp_path: Path):
    """BLOCKED if pre_patch_outcome is not REPRODUCED."""
    svc = RepairLoopService(patch_verifier=MagicMock())

    for bad_outcome in (ReproductionOutcome.NOT_REPRODUCED, ReproductionOutcome.BLOCKED, None):
        result = svc.run(
            session_id="test-no-evidence",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=bad_outcome,
            test_command="pytest",
        )
        assert result.outcome == RepairOutcome.BLOCKED
        assert "reproduction evidence" in result.final_details.lower() or "reproduced" in result.final_details.lower()


# ---------------------------------------------------------------------------
# 13. Invalid workspace path -> BLOCKED
# ---------------------------------------------------------------------------

def test_repair_loop_invalid_workspace():
    """BLOCKED when workspace_path does not exist."""
    svc = RepairLoopService(patch_verifier=MagicMock())
    result = svc.run(
        session_id="test-bad-ws",
        workspace_path="/nonexistent/path/xyz",
        localization=SAMPLE_LOCALIZATION,
        pre_patch_outcome=ReproductionOutcome.REPRODUCED,
        test_command="pytest",
    )
    assert result.outcome == RepairOutcome.BLOCKED
    assert "workspace" in result.final_details.lower()


# ---------------------------------------------------------------------------
# 14. Empty localization -> BLOCKED
# ---------------------------------------------------------------------------

def test_repair_loop_empty_localization(tmp_path: Path):
    """BLOCKED when localization has no candidate locations."""
    from app.schemas import LocalizationConfidence, LocalizationResult

    empty_loc = LocalizationResult(
        candidate_locations=[],
        detected_exceptions=[],
        confidence=LocalizationConfidence.NONE,
        confidence_explanation="No candidates.",
        total_evidence_lines_analyzed=0,
    )
    svc = RepairLoopService(patch_verifier=MagicMock())
    result = svc.run(
        session_id="test-empty-loc",
        workspace_path=str(tmp_path),
        localization=empty_loc,
        pre_patch_outcome=ReproductionOutcome.REPRODUCED,
        test_command="pytest",
    )
    assert result.outcome == RepairOutcome.BLOCKED
    assert "candidate" in result.final_details.lower()


# ---------------------------------------------------------------------------
# 15. Missing test command -> BLOCKED
# ---------------------------------------------------------------------------

def test_repair_loop_missing_test_command(tmp_path: Path):
    """BLOCKED when no test command is provided."""
    svc = RepairLoopService(patch_verifier=MagicMock())
    result = svc.run(
        session_id="test-no-cmd",
        workspace_path=str(tmp_path),
        localization=SAMPLE_LOCALIZATION,
        pre_patch_outcome=ReproductionOutcome.REPRODUCED,
        test_command="",
    )
    assert result.outcome == RepairOutcome.BLOCKED
    assert "test command" in result.final_details.lower()


# ---------------------------------------------------------------------------
# 16. Hard cap on max_attempts
# ---------------------------------------------------------------------------

def test_repair_loop_max_attempts_hard_cap():
    """RepairLoopService.max_attempts cannot exceed MAX_REPAIR_ATTEMPTS."""
    svc = RepairLoopService(max_attempts=100)
    assert svc._max_attempts == MAX_REPAIR_ATTEMPTS


# ---------------------------------------------------------------------------
# 17. FIX_VERIFIED not returned from exit code 0 alone
# ---------------------------------------------------------------------------

def test_repair_loop_no_fix_verified_from_exit_code_alone(tmp_path: Path):
    """FIX_VERIFIED is only returned when PatchVerifier (Phase 5B) supplies the evidence."""
    provider = MockPatchProvider(custom_diff=VALID_DIFF)
    # Simulate verifier returning FIX_INCOMPLETE despite exit_code=0
    mock_verifier = MagicMock()
    mock_verifier.verify_patch.return_value = PatchVerificationResult(
        outcome=PatchVerificationOutcome.FIX_INCOMPLETE,
        exit_code=0,
        timed_out=False,
        stdout="",
        stderr="",
        duration_ms=50.0,
        test_command="pytest",
        pre_patch_observed=True,
        details="Original defect pattern still present.",
    )

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=mock_verifier)
        result = svc.run(
            session_id="test-no-fix",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )

    # Should NOT be FIX_VERIFIED even though exit_code==0
    assert result.outcome != RepairOutcome.FIX_VERIFIED
    assert result.outcome == RepairOutcome.FIX_INCOMPLETE


# ---------------------------------------------------------------------------
# 18. API Endpoint Tests
# ---------------------------------------------------------------------------

def test_api_repair_loop_session_not_found():
    """POST /patch/repair-loop returns 404 for unknown session."""
    payload = {
        "session_id": "nonexistent-session",
        "localization": SAMPLE_LOCALIZATION.model_dump(),
        "test_command": "pytest",
    }
    resp = client.post("/patch/repair-loop", json=payload)
    assert resp.status_code == 404


def test_api_repair_loop_no_workspace(tmp_path: Path):
    """POST /patch/repair-loop returns 422 when session has no workspace."""
    session_id = uuid.uuid4().hex[:8]
    session = SandboxSessionData(
        session_id=session_id,
        repo_url="https://github.com/testorg/repo",
        issue_url="https://github.com/testorg/repo/issues/1",
    )
    session.state = SandboxState.READY
    session.workspace_path = None
    sandbox_service.sessions[session_id] = session
    try:
        payload = {
            "session_id": session_id,
            "localization": SAMPLE_LOCALIZATION.model_dump(),
            "test_command": "pytest",
        }
        resp = client.post("/patch/repair-loop", json=payload)
        assert resp.status_code == 422
    finally:
        sandbox_service.sessions.pop(session_id, None)


def test_api_repair_loop_blocked_no_reproduced(tmp_path: Path):
    """POST /patch/repair-loop returns BLOCKED when no reproduction evidence exists."""
    session_id = _register_session(tmp_path, repro_outcome=ReproductionOutcome.NOT_REPRODUCED)
    try:
        payload = {
            "session_id": session_id,
            "localization": SAMPLE_LOCALIZATION.model_dump(),
            "test_command": "pytest",
        }
        resp = client.post("/patch/repair-loop", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "blocked"
        assert data["success"] is True
    finally:
        sandbox_service.sessions.pop(session_id, None)


def test_api_repair_loop_fix_verified(tmp_path: Path):
    """POST /patch/repair-loop returns fix_verified with valid mock provider and mocked verifier."""
    # Create target file so PatchApplier can apply the diff
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    session_id = _register_session(tmp_path, repro_outcome=ReproductionOutcome.REPRODUCED)

    provider = MockPatchProvider(custom_diff=VALID_DIFF)
    mock_verifier_result = _mk_verifier_result(PatchVerificationOutcome.FIX_VERIFIED)

    with patch("app.main.repair_loop_service._patch_verifier") as mv:
        mv.verify_patch.return_value = mock_verifier_result
        with patch("app.repair_loop.get_patch_provider", return_value=provider):
            payload = {
                "session_id": session_id,
                "localization": SAMPLE_LOCALIZATION.model_dump(),
                "test_command": "pytest",
                "provider": "mock",
            }
            resp = client.post("/patch/repair-loop", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["outcome"] == "fix_verified"
    assert data["real_ai_call_made"] is False
    assert len(data["attempts"]) == 1
    assert data["attempts"][0]["verification_outcome"] == "fix_verified"

    sandbox_service.sessions.pop(session_id, None)


def test_api_repair_loop_no_real_ai_calls(tmp_path: Path):
    """Verify that no real network calls are made during repair loop tests."""
    session_id = _register_session(tmp_path, repro_outcome=ReproductionOutcome.REPRODUCED)

    with patch("httpx.Client") as mock_client_cls:
        payload = {
            "session_id": session_id,
            "localization": SAMPLE_LOCALIZATION.model_dump(),
            "test_command": "pytest",
            "provider": "mock",
        }
        client.post("/patch/repair-loop", json=payload)
        mock_client_cls.assert_not_called()

    sandbox_service.sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# 19. SEC-01: Dirty Workspace Reuse Prevention & Rollback Tests
# ---------------------------------------------------------------------------

def test_repair_loop_rollback_on_incomplete_verification(tmp_path: Path):
    """When verification returns FIX_INCOMPLETE, the applied patch is safely rolled back."""
    calc_file = tmp_path / "app" / "calculator.py"
    calc_file.parent.mkdir(parents=True, exist_ok=True)
    orig_content = "def divide(a, b):\n    return a / b\n"
    calc_file.write_text(orig_content, encoding="utf-8")

    provider = MockPatchProvider(custom_diff=VALID_DIFF)
    mock_verifier = MagicMock()
    mock_verifier.verify_patch.return_value = _mk_verifier_result(
        PatchVerificationOutcome.FIX_INCOMPLETE, "Tests still failing."
    )

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=mock_verifier)
        result = svc.run(
            session_id="test-rollback",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )

    assert result.outcome == RepairOutcome.FIX_INCOMPLETE
    assert result.workspace_rolled_back is True
    assert result.workspace_dirty is False
    # File must be restored to original pre-repair state
    assert calc_file.read_text(encoding="utf-8") == orig_content


def test_repair_loop_blocks_dirty_session(tmp_path: Path):
    """When a session is marked dirty, repair loop immediately returns BLOCKED."""
    svc = RepairLoopService(patch_verifier=MagicMock())
    result = svc.run(
        session_id="test-dirty-session",
        workspace_path=str(tmp_path),
        localization=SAMPLE_LOCALIZATION,
        pre_patch_outcome=ReproductionOutcome.REPRODUCED,
        test_command="pytest",
        session_is_dirty=True,
    )
    assert result.outcome == RepairOutcome.BLOCKED
    assert "dirty" in result.final_details.lower()


def test_api_repair_loop_blocks_repeated_run_on_dirty_workspace(tmp_path: Path):
    """A session marked dirty (e.g. from /patch/apply) is rejected by POST /patch/repair-loop."""
    session_id = _register_session(tmp_path, repro_outcome=ReproductionOutcome.REPRODUCED)
    session = sandbox_service.sessions[session_id]
    session.is_dirty = True

    payload = {
        "session_id": session_id,
        "localization": SAMPLE_LOCALIZATION.model_dump(),
        "test_command": "pytest",
    }
    resp = client.post("/patch/repair-loop", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "blocked"
    assert "dirty" in data["final_details"].lower()

    # Reset dirty state via endpoint
    reset_resp = client.post("/patch/reset-dirty", json={"session_id": session_id})
    assert reset_resp.status_code == 200
    assert reset_resp.json()["is_dirty"] is False
    assert session.is_dirty is False

    sandbox_service.sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# 20. SEC-02: Security Violation Classification (.env, .git, .sh)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("blocked_diff,expected_kw", [
    (
        "--- a/.env\n+++ b/.env\n@@ -1,1 +1,1 @@\n+SECRET=injected\n",
        "sensitive file",
    ),
    (
        "--- a/.git/config\n+++ b/.git/config\n@@ -1,1 +1,1 @@\n+[core]\n",
        "protected repository directory",
    ),
    (
        "--- /dev/null\n+++ b/exploit.sh\n@@ -0,0 +1,1 @@\n+#!/bin/sh\n",
        "blocked",
    ),
])
def test_repair_loop_security_violations_terminate_immediately(tmp_path: Path, blocked_diff: str, expected_kw: str):
    """Blocked sensitive files (.env), directories (.git), and extensions (.sh) return BLOCKED with no retry."""
    provider = MockPatchProvider(custom_diff=blocked_diff)

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=MagicMock())
        result = svc.run(
            session_id="sec-violation-test",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )

    assert result.outcome == RepairOutcome.BLOCKED
    assert len(result.attempts) == 1  # Non-retryable: halted immediately on attempt 1
    assert "security violation" in result.final_details.lower()
    assert expected_kw in result.final_details.lower() or "security" in result.final_details.lower()


# ---------------------------------------------------------------------------
# 21. SEC-03: Preflight Test Command Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_cmd", [
    "pytest; rm -rf /",
    "pytest && cat /etc/passwd",
    "invalid_runner test",
    "pytest ../../escaping_dir",
])
def test_repair_loop_preflight_command_validation(tmp_path: Path, bad_cmd: str):
    """Invalid or shell-chained test commands are rejected in preflight before provider or applier run."""
    calc_file = tmp_path / "app" / "calculator.py"
    calc_file.parent.mkdir(parents=True, exist_ok=True)
    orig_content = "def add(a, b):\n    return a + b\n"
    calc_file.write_text(orig_content, encoding="utf-8")

    mock_provider = MagicMock()
    with patch("app.repair_loop.get_patch_provider", return_value=mock_provider):
        svc = RepairLoopService(patch_verifier=MagicMock())
        result = svc.run(
            session_id="bad-cmd-test",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command=bad_cmd,
        )

    assert result.outcome == RepairOutcome.BLOCKED
    assert "preflight" in result.final_details.lower() or "rejected" in result.final_details.lower()
    # Provider must NOT have been called
    mock_provider.propose_patch.assert_not_called()
    # Workspace files must be completely untouched
    assert calc_file.read_text(encoding="utf-8") == orig_content


# ---------------------------------------------------------------------------
# 22. SEC-05: Overall Wall-Clock Deadline Clamping
# ---------------------------------------------------------------------------

def test_repair_loop_clamps_verification_timeout_to_remaining_budget(tmp_path: Path):
    """The Docker test timeout is clamped to the remaining overall wall-clock budget."""
    calc_file = tmp_path / "app" / "calculator.py"
    calc_file.parent.mkdir(parents=True, exist_ok=True)
    calc_file.write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    provider = MockPatchProvider(custom_diff=VALID_DIFF)
    mock_verifier = MagicMock()
    mock_verifier.verify_patch.return_value = _mk_verifier_result(PatchVerificationOutcome.FIX_VERIFIED)

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        # Set overall timeout to 15 seconds, and test_timeout to 60 seconds
        svc = RepairLoopService(patch_verifier=mock_verifier, overall_timeout_seconds=15.0)
        svc.run(
            session_id="timeout-clamp-test",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
            test_timeout=60,
        )

    # verify_patch must have been called with timeout clamped to <= 15 seconds
    call_kwargs = mock_verifier.verify_patch.call_args.kwargs
    assert call_kwargs["timeout"] <= 15


# ---------------------------------------------------------------------------
# 23. SEC-06: HTTP 403 Forbidden & Lock Cleanup
# ---------------------------------------------------------------------------

def test_repair_loop_http_403_non_retryable(tmp_path: Path):
    """HTTP 403 Forbidden from provider is non-retryable and produces BLOCKED on attempt 1."""
    provider = MagicMock()
    provider.propose_patch.side_effect = PatchProviderError("AI provider returned HTTP 403: Forbidden access")

    with patch("app.repair_loop.get_patch_provider", return_value=provider):
        svc = RepairLoopService(patch_verifier=MagicMock())
        result = svc.run(
            session_id="http-403-test",
            workspace_path=str(tmp_path),
            localization=SAMPLE_LOCALIZATION,
            pre_patch_outcome=ReproductionOutcome.REPRODUCED,
            test_command="pytest",
        )

    assert result.outcome == RepairOutcome.BLOCKED
    assert len(result.attempts) == 1  # Did not retry
    assert "403" in result.final_details or "forbidden" in result.final_details.lower()


def test_repair_loop_lock_cleanup():
    """Verify session lock is cleaned up from the registry once released."""
    session_id = "lock-cleanup-test"

    lock = _acquire_session_lock(session_id)
    assert lock is not None
    assert session_id in _session_locks

    _release_session_lock(session_id)
    # Registry entry should be pruned
    assert session_id not in _session_locks
