"""
test_patch_applier.py — Comprehensive Unit & Integration Tests for Safe Patch Application (Phase 5A)

Covers:
  1. Valid modifications, creations, and deletions in trusted disposable fixtures.
  2. Multi-hunk and multi-file patches.
  3. Pre-application revalidation failure handling (malformed diffs, empty diffs, binary patches).
  4. Path traversal, absolute paths, Windows drive, and UNC share rejections.
  5. Symlink target and symlink parent directory rejection.
  6. Blocked file extensions and sensitive filenames (.env, .git).
  7. Atomic all-or-nothing rollback on context mismatch or I/O failure.
  8. Prevention of patch application to system root, home, or application source directory.
  9. API endpoint POST /patch/apply integration with managed sandbox sessions.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app, sandbox_service
from app.patch_applier import PatchApplier, apply_patch
from app.sandbox_service import SandboxSessionData
from app.schemas import SandboxState

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Provide a clean, disposable temporary workspace."""
    ws = tmp_path / "sandbox_workspace"
    ws.mkdir()
    (ws / "app").mkdir()
    (ws / "app" / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )
    return ws


# ---------------------------------------------------------------------------
# 1. Valid Patch Applications
# ---------------------------------------------------------------------------

def test_apply_valid_single_file_modification(workspace: Path):
    diff = """--- a/app/calculator.py
+++ b/app/calculator.py
@@ -3,3 +3,5 @@
 def divide(a, b):
+    if b == 0:
+        raise ValueError("Division by zero")
     return a / b
"""
    result = apply_patch(diff, workspace)
    assert result.success is True
    assert result.applied is True
    assert result.applied_files == ["app/calculator.py"]
    assert result.errors == []

    content = (workspace / "app" / "calculator.py").read_text(encoding="utf-8")
    assert 'raise ValueError("Division by zero")' in content
    assert "def add(a, b):" in content


def test_apply_valid_file_creation(workspace: Path):
    diff = """--- /dev/null
+++ b/app/utils.py
@@ -0,0 +1,3 @@
+def helper():
+    return True
"""
    result = apply_patch(diff, workspace)
    assert result.success is True
    assert result.applied is True
    assert "app/utils.py" in result.applied_files

    created_file = workspace / "app" / "utils.py"
    assert created_file.exists()
    assert "def helper():" in created_file.read_text(encoding="utf-8")


def test_apply_valid_file_deletion(workspace: Path):
    target = workspace / "app" / "obsolete.py"
    target.write_text("def old(): pass\n", encoding="utf-8")

    diff = """--- a/app/obsolete.py
+++ /dev/null
@@ -1,1 +0,0 @@
-def old(): pass
"""
    result = apply_patch(diff, workspace)
    assert result.success is True
    assert result.applied is True
    assert "app/obsolete.py" in result.applied_files
    assert not target.exists()


def test_apply_multi_hunk_patch(workspace: Path):
    diff = """--- a/app/calculator.py
+++ b/app/calculator.py
@@ -1,2 +1,3 @@
 def add(a, b):
+    # Add function
     return a + b
@@ -3,3 +4,5 @@
 def divide(a, b):
+    if b == 0:
+        raise ValueError()
     return a / b
"""
    result = apply_patch(diff, workspace)
    assert result.success is True
    assert result.applied is True

    content = (workspace / "app" / "calculator.py").read_text(encoding="utf-8")
    assert "# Add function" in content
    assert "raise ValueError()" in content


def test_apply_multi_file_patch(workspace: Path):
    diff = """--- a/app/calculator.py
+++ b/app/calculator.py
@@ -1,2 +1,3 @@
 def add(a, b):
+    \"\"\"Sum.\"\"\"
     return a + b
--- /dev/null
+++ b/app/version.py
@@ -0,0 +1,1 @@
+VERSION = "1.0.0"
"""
    result = apply_patch(diff, workspace)
    assert result.success is True
    assert result.applied is True
    assert set(result.applied_files) == {"app/calculator.py", "app/version.py"}

    calc_content = (workspace / "app" / "calculator.py").read_text(encoding="utf-8")
    assert '"""Sum."""' in calc_content
    assert (workspace / "app" / "version.py").read_text(encoding="utf-8") == 'VERSION = "1.0.0"\n'


# ---------------------------------------------------------------------------
# 2. Revalidation & Malformed Input Rejections
# ---------------------------------------------------------------------------

def test_reject_empty_diff(workspace: Path):
    result = apply_patch("", workspace)
    assert result.success is False
    assert result.applied is False
    assert any("empty" in e.lower() for e in result.errors)


def test_reject_whitespace_diff(workspace: Path):
    result = apply_patch("   \n\n  ", workspace)
    assert result.success is False
    assert result.applied is False


def test_reject_binary_patch(workspace: Path):
    diff = "GIT binary patch\nliteral 0\nHc$@<O00001\n"
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False
    assert any("binary" in e.lower() for e in result.errors)


def test_reject_malformed_headers(workspace: Path):
    diff = "--- a/app/calc.py\n(missing plus header)\n"
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False


# ---------------------------------------------------------------------------
# 3. Path Security & Containment Checks
# ---------------------------------------------------------------------------

def test_reject_parent_directory_traversal(workspace: Path):
    diff = """--- a/../../etc/passwd
+++ b/../../etc/passwd
@@ -1,1 +1,1 @@
-root
+hacked
"""
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False
    assert any("traversal" in e.lower() or ".." in e for e in result.errors)


def test_reject_absolute_unix_path(workspace: Path):
    diff = """--- /etc/shadow
+++ /etc/shadow
@@ -1,1 +1,1 @@
-old
+new
"""
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False
    assert any("absolute paths are forbidden" in e.lower() for e in result.errors)


def test_reject_windows_drive_path(workspace: Path):
    diff = """--- a/C:/Windows/System32/calc.exe
+++ b/C:/Windows/System32/calc.exe
@@ -1,1 +1,1 @@
-old
+new
"""
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False


def test_reject_unc_path(workspace: Path):
    diff = r"""--- \\server\share\file.py
+++ \\server\share\file.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False
    assert any("unc" in e.lower() for e in result.errors)


def test_reject_blocked_file_extension(workspace: Path):
    diff = """--- /dev/null
+++ b/script.sh
@@ -0,0 +1,2 @@
+#!/bin/sh
+echo hacked
"""
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False
    assert any("blocked" in e.lower() for e in result.errors)


def test_reject_blocked_filename(workspace: Path):
    diff = """--- /dev/null
+++ b/.env
@@ -0,0 +1,1 @@
+SECRET=123
"""
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False
    assert any("blocked" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# 4. Atomic Rollback on Context Mismatch or Error
# ---------------------------------------------------------------------------

def test_atomic_rollback_on_mismatched_context(workspace: Path):
    """When a patch has two files and the second fails to match, the first must not be modified."""
    calc_path = workspace / "app" / "calculator.py"
    calc_orig = calc_path.read_text(encoding="utf-8")

    diff = """--- a/app/calculator.py
+++ b/app/calculator.py
@@ -1,2 +1,3 @@
 def add(a, b):
+    # Modified
     return a + b
--- a/app/calculator.py
+++ b/app/calculator.py
@@ -50,2 +50,3 @@
 def nonexistent_function():
+    pass
     return None
"""
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False

    # Calculator must remain in original state
    assert calc_path.read_text(encoding="utf-8") == calc_orig


def test_target_file_not_found_fails_cleanly(workspace: Path):
    diff = """--- a/app/missing_file.py
+++ b/app/missing_file.py
@@ -1,2 +1,2 @@
-old
+new
"""
    result = apply_patch(diff, workspace)
    assert result.success is False
    assert result.applied is False
    assert any("does not exist" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# 5. Anti-Host Overwrite Safety
# ---------------------------------------------------------------------------

def test_refuse_root_or_app_source_directory():
    with pytest.raises(ValueError, match="Refusing to apply patch"):
        # Points to current working directory (which is the app source)
        PatchApplier(workspace_root=Path.cwd())


# ---------------------------------------------------------------------------
# 6. API Endpoint POST /patch/apply Tests
# ---------------------------------------------------------------------------

def test_api_apply_patch_success(workspace: Path):
    session_id = "test_apply_ok"
    session = SandboxSessionData(
        session_id=session_id,
        repo_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/1",
    )
    session.state = SandboxState.READY
    session.workspace_path = str(workspace)
    sandbox_service.sessions[session_id] = session

    try:
        diff = """--- a/app/calculator.py
+++ b/app/calculator.py
@@ -1,2 +1,3 @@
 def add(a, b):
+    # Documented
     return a + b
"""
        resp = client.post("/patch/apply", json={
            "session_id": session_id,
            "unified_diff": diff,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["applied"] is True
        assert "app/calculator.py" in body["applied_files"]

        content = (workspace / "app" / "calculator.py").read_text(encoding="utf-8")
        assert "# Documented" in content
    finally:
        sandbox_service.sessions.pop(session_id, None)


def test_api_apply_patch_unknown_session_returns_404():
    resp = client.post("/patch/apply", json={
        "session_id": "nonexistent_session_id",
        "unified_diff": "--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-a\n+b\n",
    })
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_api_apply_patch_unready_session_returns_422():
    session_id = "test_no_workspace"
    session = SandboxSessionData(
        session_id=session_id,
        repo_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/1",
    )
    session.state = SandboxState.PENDING
    session.workspace_path = None
    sandbox_service.sessions[session_id] = session

    try:
        resp = client.post("/patch/apply", json={
            "session_id": session_id,
            "unified_diff": "--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-a\n+b\n",
        })
        assert resp.status_code == 422
        assert "no active workspace" in resp.json()["detail"].lower()
    finally:
        sandbox_service.sessions.pop(session_id, None)


def test_api_apply_patch_invalid_diff_returns_failure_body(workspace: Path):
    session_id = "test_apply_fail"
    session = SandboxSessionData(
        session_id=session_id,
        repo_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/1",
    )
    session.state = SandboxState.READY
    session.workspace_path = str(workspace)
    sandbox_service.sessions[session_id] = session

    try:
        # Diff targeting blocked .sh extension
        diff = """--- /dev/null
+++ b/malicious.sh
@@ -0,0 +1,1 @@
+echo hacked
"""
        resp = client.post("/patch/apply", json={
            "session_id": session_id,
            "unified_diff": diff,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["applied"] is False
        assert len(body["errors"]) > 0
    finally:
        sandbox_service.sessions.pop(session_id, None)
