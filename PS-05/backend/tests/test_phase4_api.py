"""
test_phase4_api.py — Comprehensive API tests for Phase 4 endpoints.

Covers:
  - POST /localize: valid inputs, missing fields, oversized input, empty evidence
  - POST /patch/propose: valid localization, empty candidates, invalid input
  - POST /patch/validate: valid diff with managed session, unknown session, no workspace,
    traversal attempts, malformed diffs, oversized diffs, filesystem immutability
"""

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, sandbox_service
from app.sandbox_service import SandboxSessionData
from app.schemas import SandboxState


client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_managed_session(tmp_path: Path) -> str:
    """Register a fake sandbox session backed by a real temp directory."""
    session_id = uuid.uuid4().hex[:8]
    session = SandboxSessionData(
        session_id=session_id,
        repo_url="https://github.com/testorg/testrepo",
        issue_url="https://github.com/testorg/testrepo/issues/1",
    )
    session.state = SandboxState.READY
    session.workspace_path = str(tmp_path)
    sandbox_service.sessions[session_id] = session
    return session_id


def _cleanup_session(session_id: str):
    sandbox_service.sessions.pop(session_id, None)


SAMPLE_TRACE = (
    'Traceback (most recent call last):\n'
    '  File "app/calculator.py", line 10, in divide\n'
    '    return a / b\n'
    'ZeroDivisionError: division by zero\n'
)


SAMPLE_LOCALIZATION = {
    "candidate_locations": [
        {
            "file_path": "app/calculator.py",
            "line_number": 10,
            "function_name": "divide",
            "evidence_snippet": 'File "app/calculator.py", line 10, in divide',
            "source_type": "stack_trace",
            "relevance_score": 0.95,
            "is_hypothesis": True,
        }
    ],
    "detected_exceptions": ["ZeroDivisionError"],
    "confidence": "HIGH",
    "confidence_explanation": "High confidence: verified stack trace.",
    "total_evidence_lines_analyzed": 5,
    "is_root_cause_proven": False,
}


VALID_DIFF = (
    "--- a/app/calculator.py\n"
    "+++ b/app/calculator.py\n"
    "@@ -10,1 +10,3 @@\n"
    "+    if b == 0:\n"
    "+        raise ValueError('Divisor cannot be zero')\n"
    "     return a / b\n"
)


# ===========================================================================
# 1. POST /localize tests
# ===========================================================================


class TestLocalizeEndpoint:

    def test_localize_with_stack_trace(self):
        """Valid request with stack trace returns candidates and HIGH confidence."""
        resp = client.post("/localize", json={
            "issue_title": "ZeroDivisionError in calculator divide",
            "stack_trace": SAMPLE_TRACE,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        result = body["result"]
        assert result["confidence"] == "HIGH"
        assert result["is_root_cause_proven"] is False
        assert len(result["candidate_locations"]) >= 1
        top = result["candidate_locations"][0]
        assert top["file_path"] == "app/calculator.py"
        assert top["is_hypothesis"] is True
        assert "ZeroDivisionError" in result["detected_exceptions"]

    def test_localize_title_only(self):
        """Minimal request with only a title returns a result (possibly low confidence)."""
        resp = client.post("/localize", json={
            "issue_title": "Something is broken",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "confidence" in body["result"]

    def test_localize_with_body_and_stderr(self):
        """Request with issue body and reproduction stderr."""
        resp = client.post("/localize", json={
            "issue_title": "TypeError in parser.py",
            "issue_body": "When I run the parser on malformed input, it crashes.\nFile \"parser.py\", line 42, in parse\n",
            "reproduction_stderr": "TypeError: expected str, got NoneType\n",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["result"]["detected_exceptions"]) >= 1

    def test_localize_missing_title_rejected(self):
        """Request without issue_title is rejected by Pydantic validation."""
        resp = client.post("/localize", json={})
        assert resp.status_code == 422

    def test_localize_empty_title_rejected(self):
        """Empty string title is rejected (min_length=1)."""
        resp = client.post("/localize", json={"issue_title": ""})
        assert resp.status_code == 422

    def test_localize_oversized_input_rejected(self):
        """Input exceeding max_length is rejected."""
        oversized = "x" * 60_000
        resp = client.post("/localize", json={
            "issue_title": "bug",
            "issue_body": oversized,
        })
        assert resp.status_code == 422

    def test_localize_no_evidence_returns_none_confidence(self):
        """Title with no file references or exceptions yields NONE confidence."""
        resp = client.post("/localize", json={
            "issue_title": "Something feels wrong somehow",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["confidence"] in ("NONE", "LOW")

    def test_localize_does_not_return_host_paths(self):
        """Response should not leak absolute host filesystem paths."""
        resp = client.post("/localize", json={
            "issue_title": "ZeroDivisionError",
            "stack_trace": SAMPLE_TRACE,
        })
        assert resp.status_code == 200
        raw = resp.text
        assert "C:\\" not in raw
        assert "/home/" not in raw
        assert "/Users/" not in raw


# ===========================================================================
# 2. POST /patch/propose tests
# ===========================================================================


class TestPatchProposeEndpoint:

    def test_propose_with_valid_localization(self):
        """Valid localization returns a proposal with diff, rationale, and is_applied=False."""
        resp = client.post("/patch/propose", json={
            "localization": SAMPLE_LOCALIZATION,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        proposal = body["proposal"]
        assert proposal["is_applied"] is False
        assert proposal["provider_name"] == "mock-deterministic-provider"
        assert len(proposal["unified_diff"]) > 0
        assert len(proposal["affected_files"]) >= 1
        assert len(proposal["rationale"]) > 0
        assert "proposal_id" in proposal

    def test_propose_with_context(self):
        """Context dict is passed through to provider."""
        resp = client.post("/patch/propose", json={
            "localization": SAMPLE_LOCALIZATION,
            "context": {"repo": "testorg/testrepo"},
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_propose_empty_candidates(self):
        """Localization with no candidates returns empty diff proposal."""
        empty_loc = {
            "candidate_locations": [],
            "detected_exceptions": [],
            "confidence": "NONE",
            "confidence_explanation": "No evidence.",
            "total_evidence_lines_analyzed": 0,
            "is_root_cause_proven": False,
        }
        resp = client.post("/patch/propose", json={"localization": empty_loc})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["proposal"]["unified_diff"] == ""
        assert body["proposal"]["affected_files"] == []
        assert body["proposal"]["is_applied"] is False

    def test_propose_missing_localization_rejected(self):
        """Missing localization field is rejected."""
        resp = client.post("/patch/propose", json={})
        assert resp.status_code == 422

    def test_propose_invalid_localization_schema(self):
        """Malformed localization is rejected by Pydantic."""
        resp = client.post("/patch/propose", json={
            "localization": {"not_a_valid_field": True},
        })
        assert resp.status_code == 422

    def test_propose_does_not_apply_patch(self):
        """Proposal always has is_applied=False."""
        resp = client.post("/patch/propose", json={
            "localization": SAMPLE_LOCALIZATION,
        })
        assert resp.status_code == 200
        assert resp.json()["proposal"]["is_applied"] is False


# ===========================================================================
# 3. POST /patch/validate tests
# ===========================================================================


class TestPatchValidateEndpoint:

    def test_validate_valid_diff(self, tmp_path):
        """Valid diff against a managed workspace passes validation."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "calculator.py").write_text(
            "def divide(a, b):\n    return a / b\n", encoding="utf-8"
        )
        session_id = _create_managed_session(tmp_path)
        try:
            resp = client.post("/patch/validate", json={
                "session_id": session_id,
                "unified_diff": VALID_DIFF,
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            assert body["is_valid"] is True
            assert body["errors"] == []
            assert "app/calculator.py" in body["affected_files"]
        finally:
            _cleanup_session(session_id)

    def test_validate_unknown_session_returns_404(self):
        """Unknown session_id returns 404."""
        resp = client.post("/patch/validate", json={
            "session_id": "nonexistent-session",
            "unified_diff": VALID_DIFF,
        })
        assert resp.status_code == 404

    def test_validate_session_without_workspace_returns_422(self):
        """Session with no workspace_path returns 422."""
        session_id = uuid.uuid4().hex[:8]
        session = SandboxSessionData(
            session_id=session_id,
            repo_url="https://github.com/testorg/testrepo",
            issue_url="https://github.com/testorg/testrepo/issues/1",
        )
        session.state = SandboxState.PENDING
        session.workspace_path = None
        sandbox_service.sessions[session_id] = session
        try:
            resp = client.post("/patch/validate", json={
                "session_id": session_id,
                "unified_diff": VALID_DIFF,
            })
            assert resp.status_code == 422
        finally:
            _cleanup_session(session_id)

    def test_validate_traversal_attempt_rejected(self, tmp_path):
        """Diff with path traversal (..) is rejected."""
        session_id = _create_managed_session(tmp_path)
        try:
            traversal_diff = (
                "--- a/../../etc/passwd\n"
                "+++ b/../../etc/passwd\n"
                "@@ -1,1 +1,1 @@\n"
                "-root\n"
                "+hacked\n"
            )
            resp = client.post("/patch/validate", json={
                "session_id": session_id,
                "unified_diff": traversal_diff,
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["is_valid"] is False
            assert any("traversal" in e.lower() or ".." in e for e in body["errors"])
        finally:
            _cleanup_session(session_id)

    def test_validate_absolute_path_rejected(self, tmp_path):
        """Diff with absolute Unix path is rejected."""
        session_id = _create_managed_session(tmp_path)
        try:
            abs_diff = (
                "--- a//etc/shadow\n"
                "+++ b//etc/shadow\n"
                "@@ -1,1 +1,1 @@\n"
                "-old\n"
                "+new\n"
            )
            resp = client.post("/patch/validate", json={
                "session_id": session_id,
                "unified_diff": abs_diff,
            })
            assert resp.status_code == 200
            assert resp.json()["is_valid"] is False
        finally:
            _cleanup_session(session_id)

    def test_validate_malformed_diff_rejected(self, tmp_path):
        """Truncated diff header is rejected."""
        session_id = _create_managed_session(tmp_path)
        try:
            resp = client.post("/patch/validate", json={
                "session_id": session_id,
                "unified_diff": "--- a/some/file.py",
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["is_valid"] is False
            assert len(body["errors"]) > 0
        finally:
            _cleanup_session(session_id)

    def test_validate_empty_diff_rejected(self):
        """Empty unified_diff is rejected by Pydantic (min_length=1)."""
        resp = client.post("/patch/validate", json={
            "session_id": "any",
            "unified_diff": "",
        })
        assert resp.status_code == 422

    def test_validate_missing_fields_rejected(self):
        """Missing required fields are rejected."""
        resp = client.post("/patch/validate", json={})
        assert resp.status_code == 422

    def test_validate_oversized_diff_rejected(self):
        """Diff exceeding max_length is rejected by Pydantic."""
        oversized = "x" * 300_000
        resp = client.post("/patch/validate", json={
            "session_id": "any",
            "unified_diff": oversized,
        })
        assert resp.status_code == 422

    def test_validate_does_not_modify_files(self, tmp_path):
        """Validation is strictly read-only — no files are created or modified."""
        (tmp_path / "app").mkdir()
        original_content = "def divide(a, b):\n    return a / b\n"
        target_file = tmp_path / "app" / "calculator.py"
        target_file.write_text(original_content, encoding="utf-8")

        # Snapshot before
        before_files = set(str(p) for p in tmp_path.rglob("*"))
        before_content = target_file.read_text(encoding="utf-8")

        session_id = _create_managed_session(tmp_path)
        try:
            resp = client.post("/patch/validate", json={
                "session_id": session_id,
                "unified_diff": VALID_DIFF,
            })
            assert resp.status_code == 200

            # Snapshot after
            after_files = set(str(p) for p in tmp_path.rglob("*"))
            after_content = target_file.read_text(encoding="utf-8")

            assert before_files == after_files, "Validation must not create new files"
            assert before_content == after_content, "Validation must not modify existing files"
        finally:
            _cleanup_session(session_id)

    def test_validate_blocked_extension_rejected(self, tmp_path):
        """Diff targeting a blocked extension (.exe) is rejected."""
        session_id = _create_managed_session(tmp_path)
        try:
            blocked_diff = (
                "--- a/malware.exe\n"
                "+++ b/malware.exe\n"
                "@@ -1,1 +1,1 @@\n"
                "-old\n"
                "+new\n"
            )
            resp = client.post("/patch/validate", json={
                "session_id": session_id,
                "unified_diff": blocked_diff,
            })
            assert resp.status_code == 200
            assert resp.json()["is_valid"] is False
        finally:
            _cleanup_session(session_id)


# ===========================================================================
# 4. Cross-cutting: existing endpoints still work
# ===========================================================================


class TestExistingEndpointsUnchanged:

    def test_health_still_works(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["version"] == "0.1.0"

    def test_unknown_route_returns_404(self):
        resp = client.get("/nonexistent")
        assert resp.status_code in (404, 405)
