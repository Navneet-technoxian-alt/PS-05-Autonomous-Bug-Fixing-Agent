import subprocess
from typing import Optional, Tuple

from app.schemas import ReproductionOutcome, ReproductionResult
from app.sandbox_controller import SandboxController, SandboxSecurityError

TupleOutcome = Tuple[ReproductionOutcome, str]


class ReproductionRunner:
    """Executes controlled test commands within verified sandboxes and classifies outcomes."""

    def __init__(self, sandbox_controller: Optional[SandboxController] = None):
        self.sandbox_controller = sandbox_controller or SandboxController()

    def classify_outcome(
        self,
        exit_code: Optional[int],
        timed_out: bool,
        stdout: str,
        stderr: str,
        expected_failure_pattern: Optional[str] = None,
        blocked_reason: Optional[str] = None,
    ) -> TupleOutcome:
        """Classify execution into REPRODUCED, NOT_REPRODUCED, or BLOCKED.
        
        CRITICAL RULE:
        Never infer successful reproduction merely because a command completed.
        """
        combined_output = f"{stdout}\n{stderr}"

        # 1. Any execution blocked by controls or environment failures
        if blocked_reason:
            return ReproductionOutcome.BLOCKED, f"Reproduction blocked: {blocked_reason}"

        # 2. Timeout is considered BLOCKED rather than reproduced
        if timed_out:
            return ReproductionOutcome.BLOCKED, "Execution timed out before confirming bug reproduction."

        # 3. If an explicit failure pattern or exception was expected
        if expected_failure_pattern:
            pattern_matched = expected_failure_pattern.lower() in combined_output.lower()
            if pattern_matched:
                return (
                    ReproductionOutcome.REPRODUCED,
                    f"Bug successfully reproduced. Expected error pattern '{expected_failure_pattern}' observed with exit code {exit_code}.",
                )
            if exit_code == 0:
                return (
                    ReproductionOutcome.NOT_REPRODUCED,
                    "Command completed cleanly with exit code 0; expected bug failure did not manifest.",
                )
            # Failed, but with an unexpected error
            return (
                ReproductionOutcome.BLOCKED,
                f"Command exited with code {exit_code}, but expected failure pattern '{expected_failure_pattern}' was not found in output.",
            )

        # 4. Standard test runner evaluation without specific pattern
        if exit_code == 0:
            return (
                ReproductionOutcome.NOT_REPRODUCED,
                "Test suite completed cleanly with exit code 0. Bug was not reproduced.",
            )
        elif exit_code is not None and exit_code > 0:
            return (
                ReproductionOutcome.REPRODUCED,
                f"Test suite failed with exit code {exit_code}, indicating defect reproduction.",
            )

        return ReproductionOutcome.BLOCKED, "Unable to determine reproduction outcome."

    def run_reproduction(
        self,
        workspace_path: str,
        test_command: str,
        expected_failure_pattern: Optional[str] = None,
        timeout: int = 60,
    ) -> ReproductionResult:
        """Execute a reproduction command inside a safe container or block if unsafe."""
        # Verify Docker availability
        if not self.sandbox_controller.is_docker_available():
            outcome, details = self.classify_outcome(
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr="",
                blocked_reason="Docker is not installed or daemon is unavailable. Manual Docker verification required.",
            )
            return ReproductionResult(
                outcome=outcome,
                command=test_command,
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr="Docker executable not found in PATH or daemon not responding.",
                details=details,
            )

        # Build and verify safe Docker command
        try:
            safe_docker_cmd = self.sandbox_controller.build_safe_docker_command(
                workspace_path=workspace_path,
                test_command=test_command,
                timeout=timeout,
            )
        except SandboxSecurityError as sec_err:
            outcome, details = self.classify_outcome(
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr="",
                blocked_reason=str(sec_err),
            )
            return ReproductionResult(
                outcome=outcome,
                command=test_command,
                exit_code=None,
                timed_out=False,
                stdout="",
                stderr=str(sec_err),
                details=details,
            )

        # Execute container command with controlled timeout
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
            stdout_str = proc.stdout
            stderr_str = proc.stderr
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as te:
            timed_out = True
            stdout_str = te.stdout or "" if isinstance(te.stdout, str) else ""
            stderr_str = te.stderr or "" if isinstance(te.stderr, str) else ""

        outcome, details = self.classify_outcome(
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout_str,
            stderr=stderr_str,
            expected_failure_pattern=expected_failure_pattern,
        )

        return ReproductionResult(
            outcome=outcome,
            command=" ".join(safe_docker_cmd),
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout_str,
            stderr=stderr_str,
            details=details,
        )
