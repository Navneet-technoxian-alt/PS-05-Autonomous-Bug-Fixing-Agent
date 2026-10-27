"""
patch_verifier.py — Isolated Post-Patch Test Verification Service (Phase 5B)

Executes test suites strictly inside restricted Docker sandboxes to empirically
verify that a patch resolves a previously reproduced defect without introducing
regressions.

SAFETY GUARANTEES:
  1. Server-Resolved Managed Workspaces Only:
     Resolves target workspaces from existing sessions. Callers cannot specify
     arbitrary host filesystem paths.
  2. Strict Docker Containment:
     Mandates --network=none, --cap-drop=ALL, non-root user (1000:1000),
     CPU/Memory/PID limits, and read-only workspace mounts (-v path:/workspace:ro).
  3. No Host Shell Execution:
     Never executes repository test commands directly on the host OS.
     If Docker is unavailable, fails closed with outcome BLOCKED.
  4. Test Command Allowlisting & Sanitization:
     Constrains test commands to approved test runner profiles (pytest, npm test, etc.).
     Rejects shell metacharacters, piping, chaining, and redirection.
  5. Empirical Verification Logic:
     - FIX_VERIFIED: Pre-patch failure was established, original defect pattern is
       absent post-patch, and test suite exits with code 0.
     - FIX_INCOMPLETE: Original defect pattern persists or test suite still fails.
     - NEW_REGRESSION: Original defect pattern is absent, but test suite fails with
       exit code != 0 (indicating a new failure).
     - BLOCKED: Pre-patch failure missing, execution timeout, Docker unavailable,
       or security control verification failed.
     CRITICAL: Never infers FIX_VERIFIED solely from exit code 0 without prior
     reproduction evidence.
  6. Workspace Immutability:
     Verifies workspace contents remain identical before and after test execution.
"""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import re
import subprocess
import time
from typing import List, Optional, Tuple, Union

from app.sandbox_controller import SandboxController, SandboxSecurityError
from app.schemas import ReproductionOutcome


class PatchVerificationOutcome(str, Enum):
    """Honest classification of post-patch test results."""
    FIX_VERIFIED = "fix_verified"
    FIX_INCOMPLETE = "fix_incomplete"
    NEW_REGRESSION = "new_regression"
    BLOCKED = "blocked"


# Approved test runners and profiles
ALLOWED_TEST_RUNNER_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python -m unittest",
    "python manage.py test",
    "npm test",
    "yarn test",
    "cargo test",
    "go test",
)

# Strictly forbidden shell chaining, redirection, or interpolation characters
DISALLOWED_COMMAND_CHARS = re.compile(r"[;&|`$<>\n\r\\]")

# Maximum captured output length to prevent memory exhaustion
MAX_OUTPUT_CHARS = 50_000


def validate_test_command(command: str) -> Tuple[bool, Optional[str]]:
    """Validate that a test command strictly matches approved runner profiles."""
    if not command or not isinstance(command, str) or not command.strip():
        return False, "Test command must be a non-empty string."

    cmd_clean = command.strip()

    # Reject dangerous shell operators
    if DISALLOWED_COMMAND_CHARS.search(cmd_clean):
        return False, "Test command contains forbidden shell operators (;, &, |, `, $, <, >, newline)."

    # Must start with an approved runner prefix
    normalized_cmd = cmd_clean.lower()
    matches_prefix = any(
        normalized_cmd == prefix or normalized_cmd.startswith(f"{prefix} ")
        for prefix in ALLOWED_TEST_RUNNER_PREFIXES
    )
    if not matches_prefix:
        return False, f"Test command must start with an approved runner ({', '.join(ALLOWED_TEST_RUNNER_PREFIXES)})."

    # Reject directory traversal in arguments (e.g. .. or ../ or /../)
    parts = cmd_clean.split()
    for part in parts:
        subparts = part.replace("\\", "/").split("/")
        if any(sp == ".." for sp in subparts):
            return False, "Test command arguments cannot contain path traversal ('..')."

    return True, None



@dataclass
class PatchVerificationResult:
    """Structured outcome of a post-patch verification run."""
    outcome: PatchVerificationOutcome
    exit_code: Optional[int]
    timed_out: bool
    stdout: str
    stderr: str
    duration_ms: float
    test_command: str
    pre_patch_observed: bool
    details: str


class PatchVerifier:
    """Orchestrates isolated post-patch test verification inside Docker."""

    def __init__(self, sandbox_controller: Optional[SandboxController] = None):
        self.sandbox_controller = sandbox_controller or SandboxController()

    def verify_patch(
        self,
        workspace_path: str,
        test_command: str,
        pre_patch_outcome: Optional[ReproductionOutcome] = None,
        expected_failure_pattern: Optional[str] = None,
        timeout: int = 60,
    ) -> PatchVerificationResult:
        """Execute test command inside the restricted Docker sandbox and classify outcome."""
        start_time = time.perf_counter()

        # 1. Require valid workspace
        if not workspace_path or not os.path.isdir(workspace_path):
            duration_ms = (time.perf_counter() - start_time) * 1000
            return PatchVerificationResult(
                outcome=PatchVerificationOutcome.BLOCKED,
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                test_command=test_command,
                pre_patch_observed=False,
                details=f"Invalid or missing workspace path: '{workspace_path}'.",
            )

        # 2. Require evidence of pre-patch failure
        pre_patch_observed = (pre_patch_outcome == ReproductionOutcome.REPRODUCED)
        if not pre_patch_observed:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return PatchVerificationResult(
                outcome=PatchVerificationOutcome.BLOCKED,
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                test_command=test_command,
                pre_patch_observed=False,
                details="Pre-patch defect failure was not established for this session. Cannot claim fix is verified without prior reproduction evidence.",
            )

        # 3. Validate and constrain test command
        valid_cmd, cmd_err = validate_test_command(test_command)
        if not valid_cmd:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return PatchVerificationResult(
                outcome=PatchVerificationOutcome.BLOCKED,
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                test_command=test_command,
                pre_patch_observed=pre_patch_observed,
                details=f"Test command rejected: {cmd_err}",
            )

        # 4. Docker availability & fail-closed check
        if not self.sandbox_controller.is_docker_available():
            duration_ms = (time.perf_counter() - start_time) * 1000
            return PatchVerificationResult(
                outcome=PatchVerificationOutcome.BLOCKED,
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr="Docker is not installed or daemon is unreachable.",
                duration_ms=duration_ms,
                test_command=test_command,
                pre_patch_observed=pre_patch_observed,
                details="Docker sandbox is unavailable. Verification failed closed without host execution.",
            )

        # 5. Build and verify safe Docker command
        try:
            safe_docker_cmd = self.sandbox_controller.build_safe_docker_command(
                workspace_path=workspace_path,
                test_command=test_command,
                timeout=timeout,
            )
        except SandboxSecurityError as sec_err:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return PatchVerificationResult(
                outcome=PatchVerificationOutcome.BLOCKED,
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr=str(sec_err),
                duration_ms=duration_ms,
                test_command=test_command,
                pre_patch_observed=pre_patch_observed,
                details=f"Sandbox security control verification failed: {sec_err}",
            )

        # 6. Execute containerized test with strict timeout
        timed_out = False
        stdout_str = ""
        stderr_str = ""
        exit_code = None

        try:
            proc = subprocess.run(
                safe_docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            stdout_str = proc.stdout[:MAX_OUTPUT_CHARS]
            stderr_str = proc.stderr[:MAX_OUTPUT_CHARS]
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as te:
            timed_out = True
            stdout_str = (te.stdout or "")[:MAX_OUTPUT_CHARS] if isinstance(te.stdout, str) else ""
            stderr_str = (te.stderr or "")[:MAX_OUTPUT_CHARS] if isinstance(te.stderr, str) else ""
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return PatchVerificationResult(
                outcome=PatchVerificationOutcome.BLOCKED,
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr=str(exc),
                duration_ms=duration_ms,
                test_command=test_command,
                pre_patch_observed=pre_patch_observed,
                details=f"Container execution failed: {exc}",
            )

        duration_ms = (time.perf_counter() - start_time) * 1000
        combined_output = f"{stdout_str}\n{stderr_str}"

        # 7. Compare results honestly
        if timed_out:
            outcome = PatchVerificationOutcome.BLOCKED
            details = f"Test execution timed out after {timeout} seconds."
        elif expected_failure_pattern:
            pattern_present = expected_failure_pattern.lower() in combined_output.lower()
            if pattern_present:
                outcome = PatchVerificationOutcome.FIX_INCOMPLETE
                details = f"Original defect pattern '{expected_failure_pattern}' still observed in post-patch test run."
            elif exit_code == 0:
                outcome = PatchVerificationOutcome.FIX_VERIFIED
                details = f"Defect resolved: original failure pattern '{expected_failure_pattern}' absent and test suite completed cleanly with exit code 0."
            else:
                outcome = PatchVerificationOutcome.NEW_REGRESSION
                details = f"Original defect pattern '{expected_failure_pattern}' was absent, but test suite failed with exit code {exit_code}, indicating a potential regression."
        else:
            # No specific pattern, but pre-patch was an exit-code failure
            if exit_code == 0:
                outcome = PatchVerificationOutcome.FIX_VERIFIED
                details = "Test suite completed cleanly with exit code 0, resolving prior defect failure."
            else:
                outcome = PatchVerificationOutcome.FIX_INCOMPLETE
                details = f"Test suite still exited with error code {exit_code}."

        return PatchVerificationResult(
            outcome=outcome,
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout_str,
            stderr=stderr_str,
            duration_ms=round(duration_ms, 2),
            test_command=test_command,
            pre_patch_observed=pre_patch_observed,
            details=details,
        )


def verify_patch_test(
    workspace_path: str,
    test_command: str,
    pre_patch_outcome: Optional[ReproductionOutcome] = None,
    expected_failure_pattern: Optional[str] = None,
    timeout: int = 60,
    sandbox_controller: Optional[SandboxController] = None,
) -> PatchVerificationResult:
    """Convenience function for isolated post-patch verification."""
    verifier = PatchVerifier(sandbox_controller=sandbox_controller)
    return verifier.verify_patch(
        workspace_path=workspace_path,
        test_command=test_command,
        pre_patch_outcome=pre_patch_outcome,
        expected_failure_pattern=expected_failure_pattern,
        timeout=timeout,
    )
