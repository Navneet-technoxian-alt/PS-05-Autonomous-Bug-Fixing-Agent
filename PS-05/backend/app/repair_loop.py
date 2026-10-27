"""
repair_loop.py — Bounded Automated Repair Loop Service (Phase 6B)

Orchestrates AI patch generation, validation, application, and isolated Docker
verification in a bounded feedback cycle. Reuses existing Phase 5A/5B/6A
components without duplicating logic.

SAFETY GUARANTEES:
  1. Host-Free Execution:
     All code execution occurs inside existing restricted Docker sandboxes via
     PatchVerifier. Zero subprocess or shell calls on the host.
  2. Managed Sessions Only:
     Resolves session state and workspace_path server-side. Callers cannot
     supply arbitrary filesystem paths.
  3. Pre-Patch Reproduction Evidence Required:
     A session must have an established REPRODUCED outcome before a repair loop
     can start. FIX_VERIFIED is never returned without this evidence.
  4. Bounded Iteration:
     Maximum MAX_REPAIR_ATTEMPTS (3) patch attempts. An overall wall-clock
     budget (OVERALL_TIMEOUT_SECONDS) prevents unbounded runs.
  5. Fail-Closed Security Violations:
     Any BLOCKED verifier outcome, unsafe diff, PatchValidator rejection, or
     session-state inconsistency immediately terminates the loop with BLOCKED.
  6. No Credential Leakage:
     Failure evidence passed back into the provider is size-bounded and scrubbed
     through the existing sanitize_prompt_context helper.
  7. Concurrency Guard:
     A per-session lock prevents duplicate or concurrent repair runs for the
     same session.
  8. No Git Operations:
     No commit, push, pull, merge, or PR creation is performed at any point.
  9. No Silent Overwrite:
     If a patch has already been applied the loop halts rather than stacking
     additional patches onto a partially modified workspace.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.patch_applier import PatchApplier, PatchApplicationResult
from app.patch_provider import (
    BasePatchProvider,
    PatchProviderError,
    get_patch_provider,
    sanitize_prompt_context,
)
from app.patch_validator import is_patch_security_violation
from app.patch_verifier import PatchVerifier, PatchVerificationOutcome, validate_test_command
from app.schemas import (
    LocalizationResult,
    ReproductionOutcome,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_REPAIR_ATTEMPTS: int = 3
OVERALL_TIMEOUT_SECONDS: float = 300.0     # 5-minute wall-clock budget
MAX_CONTEXT_FEEDBACK_CHARS: int = 2_000    # Bound evidence fed back to provider
MAX_DIFF_OUTPUT_CHARS: int = 262_144       # 256 KB — same as patch_provider.py


# ---------------------------------------------------------------------------
# Outcome Enum
# ---------------------------------------------------------------------------

class RepairOutcome(str, Enum):
    """Top-level outcome classification for a bounded repair loop run."""
    FIX_VERIFIED   = "fix_verified"    # Evidence from Phase 5B confirms defect gone
    FIX_INCOMPLETE = "fix_incomplete"  # Attempts exhausted; defect persists
    BLOCKED        = "blocked"         # Safety/config/session issue prevents progress


# ---------------------------------------------------------------------------
# Result Data Model
# ---------------------------------------------------------------------------

@dataclass
class RepairAttempt:
    """Record of a single patch-attempt cycle inside the repair loop."""
    attempt_number: int
    proposal_id: str = ""
    unified_diff: str = ""
    validation_errors: List[str] = field(default_factory=list)
    application_errors: List[str] = field(default_factory=list)
    verification_outcome: Optional[PatchVerificationOutcome] = None
    verification_details: str = ""
    duration_ms: float = 0.0


@dataclass
class RepairLoopResult:
    """Structured outcome of the bounded repair loop."""
    outcome: RepairOutcome
    session_id: str
    attempts: List[RepairAttempt] = field(default_factory=list)
    final_details: str = ""
    total_duration_ms: float = 0.0
    real_ai_call_made: bool = False
    workspace_dirty: bool = False
    workspace_rolled_back: bool = False


# ---------------------------------------------------------------------------
# Per-Session Lock Registry
# ---------------------------------------------------------------------------

_session_locks: Dict[str, threading.Lock] = {}
_session_locks_meta: threading.Lock = threading.Lock()


def _acquire_session_lock(session_id: str) -> Optional[threading.Lock]:
    """Acquire a non-blocking per-session lock to prevent concurrent repairs."""
    with _session_locks_meta:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        lock = _session_locks[session_id]
    acquired = lock.acquire(blocking=False)
    return lock if acquired else None


def _release_session_lock(session_id: str) -> None:
    """Release per-session lock and safely prune inactive dictionary entry."""
    with _session_locks_meta:
        lock = _session_locks.get(session_id)
        if lock and lock.locked():
            try:
                lock.release()
            except RuntimeError:
                pass
        # Only clean up once released and unlocked, under meta lock
        if lock and not lock.locked():
            _session_locks.pop(session_id, None)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RepairLoopError(Exception):
    """Raised for pre-flight validation failures in the repair loop."""
    pass


# ---------------------------------------------------------------------------
# RepairLoopService
# ---------------------------------------------------------------------------

class RepairLoopService:
    """Coordinates bounded AI patch generation, validation, application, and verification.

    CRITICAL RULES (enforced in code):
      - Never execute code on the host.
      - Never weaken Docker restrictions or bypass PatchValidator.
      - Never transmit secrets, credentials, or full repo contents.
      - No Git commit, push, PR creation, or automatic merge.
      - Do not silently overwrite earlier successful evidence.
      - Fail closed on any BLOCKED verifier outcome or security violation.
    """

    def __init__(
        self,
        patch_verifier: Optional[PatchVerifier] = None,
        max_attempts: int = MAX_REPAIR_ATTEMPTS,
        overall_timeout_seconds: float = OVERALL_TIMEOUT_SECONDS,
    ):
        self._patch_verifier = patch_verifier or PatchVerifier()
        self._max_attempts = min(max_attempts, MAX_REPAIR_ATTEMPTS)  # hard cap
        self._overall_timeout = overall_timeout_seconds

    def run(
        self,
        session_id: str,
        workspace_path: str,
        localization: LocalizationResult,
        pre_patch_outcome: ReproductionOutcome,
        test_command: str,
        provider_name: str = "mock",
        expected_failure_pattern: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        test_timeout: int = 60,
        session_is_dirty: bool = False,
    ) -> RepairLoopResult:
        """Execute the bounded repair loop.

        Args:
            session_id:               Managed sandbox session identifier.
            workspace_path:           Absolute path to the isolated workspace (server-resolved).
            localization:             Structured localization evidence from Phase 4.
            pre_patch_outcome:        Must be ReproductionOutcome.REPRODUCED; otherwise BLOCKED.
            test_command:             Allowlisted test command for Docker verification.
            provider_name:            'mock' (default) or 'ai'. Config-gated.
            expected_failure_pattern: Error pattern to check absence of in post-patch output.
            context:                  Optional extra context for the patch provider prompt.
            test_timeout:             Per-Docker-run timeout in seconds (5–300).
            session_is_dirty:         Whether session workspace is modified from an earlier unverified patch.
        """
        start = time.perf_counter()

        # 1. Concurrency guard — prevent duplicate concurrent runs
        lock = _acquire_session_lock(session_id)
        if lock is None:
            return RepairLoopResult(
                outcome=RepairOutcome.BLOCKED,
                session_id=session_id,
                final_details="A repair loop is already running for this session. Concurrent repair runs are not permitted.",
                total_duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )

        try:
            return self._run_guarded(
                session_id=session_id,
                workspace_path=workspace_path,
                localization=localization,
                pre_patch_outcome=pre_patch_outcome,
                test_command=test_command,
                provider_name=provider_name,
                expected_failure_pattern=expected_failure_pattern,
                context=context,
                test_timeout=test_timeout,
                session_is_dirty=session_is_dirty,
                start=start,
            )
        finally:
            _release_session_lock(session_id)

    def _run_guarded(
        self,
        session_id: str,
        workspace_path: str,
        localization: LocalizationResult,
        pre_patch_outcome: ReproductionOutcome,
        test_command: str,
        provider_name: str,
        expected_failure_pattern: Optional[str],
        context: Optional[Dict[str, Any]],
        test_timeout: int,
        session_is_dirty: bool,
        start: float,
    ) -> RepairLoopResult:
        """Core repair loop — called only after concurrency lock is held."""
        real_ai_call_made = False
        attempts: List[RepairAttempt] = []

        # 2. Pre-flight checks (includes command validation & dirty workspace check)
        try:
            self._preflight_check(
                workspace_path=workspace_path,
                pre_patch_outcome=pre_patch_outcome,
                localization=localization,
                test_command=test_command,
                session_is_dirty=session_is_dirty,
            )
        except RepairLoopError as exc:
            return RepairLoopResult(
                outcome=RepairOutcome.BLOCKED,
                session_id=session_id,
                final_details=str(exc),
                total_duration_ms=round((time.perf_counter() - start) * 1000, 2),
                workspace_dirty=session_is_dirty,
            )

        # 3. Instantiate the provider (fails closed if AI provider is not configured)
        try:
            provider: BasePatchProvider = get_patch_provider(provider_name)
        except PatchProviderError as exc:
            return RepairLoopResult(
                outcome=RepairOutcome.BLOCKED,
                session_id=session_id,
                final_details=f"Patch provider configuration error: {exc}",
                total_duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )

        feedback_context: Optional[Dict[str, Any]] = dict(context) if context else {}
        patch_applied = False  # track if any patch has been written to disk
        last_applier: Optional[PatchApplier] = None
        last_snapshot: Optional[Dict[Any, Any]] = None
        rollback_performed = False

        for attempt_num in range(1, self._max_attempts + 1):
            # 4. Enforce overall time budget
            elapsed = time.perf_counter() - start
            if elapsed >= self._overall_timeout:
                return RepairLoopResult(
                    outcome=RepairOutcome.BLOCKED,
                    session_id=session_id,
                    attempts=attempts,
                    final_details=f"Overall time budget of {self._overall_timeout}s exceeded after {attempt_num - 1} attempt(s).",
                    total_duration_ms=round(elapsed * 1000, 2),
                    real_ai_call_made=real_ai_call_made,
                    workspace_dirty=patch_applied,
                )

            # 5. Guard against stacking patches on a modified workspace
            if patch_applied:
                logger.warning(
                    "session=%s attempt=%d: workspace already patched; stopping loop to prevent double-application.",
                    session_id, attempt_num,
                )
                break

            attempt_start = time.perf_counter()
            attempt = RepairAttempt(attempt_number=attempt_num)

            # 6. Generate candidate patch
            try:
                logger.info("session=%s attempt=%d: generating patch via '%s'", session_id, attempt_num, provider_name)
                proposal = provider.propose_patch(localization=localization, context=feedback_context)
                attempt.proposal_id = proposal.proposal_id
                attempt.unified_diff = proposal.unified_diff
                if provider_name.lower() not in ("mock", ""):
                    real_ai_call_made = True
            except PatchProviderError as exc:
                err = str(exc)
                attempt.validation_errors = [f"Provider error: {err}"]
                attempt.duration_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
                attempts.append(attempt)
                logger.warning("session=%s attempt=%d: provider error: %s", session_id, attempt_num, err)
                # Auth errors, config errors, and 403 Forbidden are non-retryable
                if any(kw in err.lower() for kw in (
                    "not configured",
                    "authentication",
                    "unauthorized",
                    "api key",
                    "403",
                    "forbidden",
                    "access denied",
                )):
                    return RepairLoopResult(
                        outcome=RepairOutcome.BLOCKED,
                        session_id=session_id,
                        attempts=attempts,
                        final_details=f"Non-retryable provider error on attempt {attempt_num}: {err}",
                        total_duration_ms=round((time.perf_counter() - start) * 1000, 2),
                        real_ai_call_made=real_ai_call_made,
                    )
                # Timeout — retryable, continue
                feedback_context = self._build_feedback_context(
                    feedback_context, attempt, failure_detail=err
                )
                continue

            # 7. Guard: empty diff is not actionable
            if not attempt.unified_diff or not attempt.unified_diff.strip():
                attempt.validation_errors = ["Provider returned an empty unified diff."]
                attempt.duration_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
                attempts.append(attempt)
                feedback_context = self._build_feedback_context(
                    feedback_context, attempt, failure_detail="Empty diff returned."
                )
                continue

            # 8. Apply the patch via PatchApplier (which revalidates through PatchValidator)
            try:
                applier = PatchApplier(workspace_root=workspace_path)
            except ValueError as exc:
                return RepairLoopResult(
                    outcome=RepairOutcome.BLOCKED,
                    session_id=session_id,
                    attempts=attempts,
                    final_details=f"Workspace path is invalid or unsafe: {exc}",
                    total_duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    real_ai_call_made=real_ai_call_made,
                )

            app_result: PatchApplicationResult = applier.apply(attempt.unified_diff)
            if not app_result.applied:
                attempt.application_errors = list(app_result.errors)
                attempt.duration_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
                attempts.append(attempt)
                logger.warning(
                    "session=%s attempt=%d: patch application failed: %s",
                    session_id, attempt_num, app_result.errors,
                )

                # Security violations from PatchValidator or PatchApplier are non-retryable
                if app_result.is_security_violation or is_patch_security_violation(app_result.errors):
                    return RepairLoopResult(
                        outcome=RepairOutcome.BLOCKED,
                        session_id=session_id,
                        attempts=attempts,
                        final_details=f"Security violation on attempt {attempt_num}: {app_result.errors}",
                        total_duration_ms=round((time.perf_counter() - start) * 1000, 2),
                        real_ai_call_made=real_ai_call_made,
                    )

                feedback_context = self._build_feedback_context(
                    feedback_context, attempt, failure_detail="; ".join(app_result.errors)
                )
                continue

            patch_applied = True
            last_applier = applier
            last_snapshot = app_result.backup_snapshot

            # 9. Verify via PatchVerifier inside restricted Docker sandbox
            # Clamp test timeout to remaining overall wall-clock budget
            elapsed_before_verify = time.perf_counter() - start
            remaining_seconds = self._overall_timeout - elapsed_before_verify
            if remaining_seconds < 5.0:
                logger.warning(
                    "session=%s attempt=%d: insufficient remaining time budget (%.1fs); rolling back and terminating.",
                    session_id, attempt_num, remaining_seconds,
                )
                if last_applier and last_snapshot:
                    last_applier.rollback(last_snapshot)
                    patch_applied = False
                    rollback_performed = True

                return RepairLoopResult(
                    outcome=RepairOutcome.BLOCKED,
                    session_id=session_id,
                    attempts=attempts,
                    final_details=f"Overall time budget exceeded: only {remaining_seconds:.1f}s remaining before Docker verification."
                    + (" [Workspace rolled back to pre-repair state]" if rollback_performed else ""),
                    total_duration_ms=round(elapsed_before_verify * 1000, 2),
                    real_ai_call_made=real_ai_call_made,
                    workspace_dirty=patch_applied,
                    workspace_rolled_back=rollback_performed,
                )

            effective_test_timeout = max(1, min(int(test_timeout), int(remaining_seconds)))

            logger.info(
                "session=%s attempt=%d: verifying patch via Docker (cmd=%r, timeout=%ds)",
                session_id, attempt_num, test_command, effective_test_timeout,
            )
            v_result = self._patch_verifier.verify_patch(
                workspace_path=workspace_path,
                test_command=test_command,
                pre_patch_outcome=pre_patch_outcome,
                expected_failure_pattern=expected_failure_pattern,
                timeout=effective_test_timeout,
            )

            attempt.verification_outcome = v_result.outcome
            attempt.verification_details = v_result.details
            attempt.duration_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
            attempts.append(attempt)

            # 10. Classify outcome & perform safe rollback if verification failed
            if v_result.outcome == PatchVerificationOutcome.FIX_VERIFIED:
                return RepairLoopResult(
                    outcome=RepairOutcome.FIX_VERIFIED,
                    session_id=session_id,
                    attempts=attempts,
                    final_details=v_result.details,
                    total_duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    real_ai_call_made=real_ai_call_made,
                    workspace_dirty=True,  # Fix verified and kept on disk
                    workspace_rolled_back=False,
                )

            # Verification did not confirm fix (BLOCKED, FIX_INCOMPLETE, or NEW_REGRESSION):
            # Safely rollback applied files to guarantee workspace cleanliness
            if last_applier and last_snapshot:
                rb_ok, rb_errs = last_applier.rollback(last_snapshot)
                if rb_ok:
                    logger.info("session=%s attempt=%d: rolled back unverified patch", session_id, attempt_num)
                    patch_applied = False
                    rollback_performed = True
                else:
                    logger.error("session=%s attempt=%d: rollback failed: %s", session_id, attempt_num, rb_errs)
                    rollback_performed = False

            if v_result.outcome == PatchVerificationOutcome.BLOCKED:
                return RepairLoopResult(
                    outcome=RepairOutcome.BLOCKED,
                    session_id=session_id,
                    attempts=attempts,
                    final_details=(
                        f"Docker sandbox blocked on attempt {attempt_num}: {v_result.details}"
                        + (" [Workspace rolled back to pre-repair state]" if rollback_performed else " [WARNING: Rollback failed; workspace is dirty]")
                    ),
                    total_duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    real_ai_call_made=real_ai_call_made,
                    workspace_dirty=patch_applied,
                    workspace_rolled_back=rollback_performed,
                )

            # FIX_INCOMPLETE or NEW_REGRESSION — stop loop to avoid unverified modifications
            break

        total_ms = round((time.perf_counter() - start) * 1000, 2)
        last = attempts[-1] if attempts else None
        details_suffix = " [Workspace rolled back to pre-repair state]" if rollback_performed else ""

        if last and last.verification_outcome in (
            PatchVerificationOutcome.FIX_INCOMPLETE,
            PatchVerificationOutcome.NEW_REGRESSION,
        ):
            return RepairLoopResult(
                outcome=RepairOutcome.FIX_INCOMPLETE,
                session_id=session_id,
                attempts=attempts,
                final_details=(last.verification_details or "Patch applied but defect persists.") + details_suffix,
                total_duration_ms=total_ms,
                real_ai_call_made=real_ai_call_made,
                workspace_dirty=patch_applied,
                workspace_rolled_back=rollback_performed,
            )

        return RepairLoopResult(
            outcome=RepairOutcome.FIX_INCOMPLETE,
            session_id=session_id,
            attempts=attempts,
            final_details=(
                f"All {self._max_attempts} attempt(s) exhausted without a verified fix."
                if not rollback_performed else
                "Patch applied but verification did not confirm defect resolution."
            ) + details_suffix,
            total_duration_ms=total_ms,
            real_ai_call_made=real_ai_call_made,
            workspace_dirty=patch_applied,
            workspace_rolled_back=rollback_performed,
        )

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    @staticmethod
    def _preflight_check(
        workspace_path: str,
        pre_patch_outcome: ReproductionOutcome,
        localization: LocalizationResult,
        test_command: str,
        session_is_dirty: bool = False,
    ) -> None:
        """Validate all preconditions before starting the loop. Raises RepairLoopError."""
        if session_is_dirty:
            raise RepairLoopError(
                "Session workspace is in a dirty/modified state from a prior patch. "
                "Further repair runs are blocked until the workspace is reset."
            )

        import os
        if not workspace_path or not os.path.isdir(workspace_path):
            raise RepairLoopError(
                f"Invalid or missing workspace path: '{workspace_path}'. Session has no active workspace."
            )

        if pre_patch_outcome != ReproductionOutcome.REPRODUCED:
            raise RepairLoopError(
                "Pre-patch defect reproduction evidence is required. "
                f"Got pre_patch_outcome='{pre_patch_outcome}'; must be REPRODUCED. "
                "FIX_VERIFIED cannot be returned without prior reproduction evidence."
            )

        if localization is None or not localization.candidate_locations:
            raise RepairLoopError(
                "Localization result must contain at least one candidate location to guide patch generation."
            )

        # Validate test command allowlisting in preflight before touching files or generating patches
        valid_cmd, cmd_err = validate_test_command(test_command)
        if not valid_cmd:
            raise RepairLoopError(f"Test command rejected during preflight: {cmd_err}")


    @staticmethod
    def _build_feedback_context(
        existing_context: Optional[Dict[str, Any]],
        attempt: RepairAttempt,
        failure_detail: str,
    ) -> Dict[str, Any]:
        """Construct bounded feedback context for the next patch-generation attempt."""
        ctx = dict(existing_context) if existing_context else {}
        # Bound and sanitize failure evidence before feeding back to the provider
        bounded = sanitize_prompt_context(failure_detail, max_chars=MAX_CONTEXT_FEEDBACK_CHARS)
        ctx["previous_attempt_failure"] = (
            f"Attempt {attempt.attempt_number} failed: {bounded}"
        )
        return ctx
