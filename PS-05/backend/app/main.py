from fastapi import FastAPI, HTTPException
from app.schemas import (
    IssueAnalyzeRequest,
    IssueAnalyzeResponse,
    LocalizeRequest,
    LocalizeResponse,
    PatchApplyRequest,
    PatchApplyResponse,
    PatchProposeRequest,
    PatchProposeResponse,
    PatchValidateRequest,
    PatchValidateResponse,
    PatchVerifyTestRequest,
    PatchVerifyTestResponse,
    RepairLoopRequest,
    RepairLoopResponse,
    RepairAttemptRecord,
    RepairLoopOutcome,
    ReproductionRequest,
    SandboxPrepareRequest,
    SandboxSessionResponse,
    SessionResetRequest,
)
from app.issue_service import IssueService
from app.sandbox_service import SandboxService
from app.phase4_service import Phase4Service
from app.patch_applier import apply_patch
from app.patch_verifier import PatchVerifier
from app.repair_loop import RepairLoopService, RepairOutcome

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="PS-05 Autonomous Bug-Fixing Agent",
    description="Backend API service for autonomous bug detection, reproduction, and fixing.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

issue_service = IssueService()
sandbox_service = SandboxService()
phase4_service = Phase4Service()
patch_verifier = PatchVerifier(sandbox_service.sandbox_controller)
repair_loop_service = RepairLoopService(patch_verifier=patch_verifier)



@app.get("/health")
def health_check():
    """Health check endpoint to verify backend service operational status."""
    return {
        "status": "healthy",
        "service": "PS-05 Autonomous Bug-Fixing Agent",
        "version": "0.1.0",
    }


@app.post("/issues/analyze", response_model=IssueAnalyzeResponse)
def analyze_issue(payload: IssueAnalyzeRequest):
    """Intake and validate a public GitHub issue URL and return structured issue metadata."""
    return issue_service.analyze_issue(payload.issue_url)


@app.post("/sandbox/prepare", response_model=SandboxSessionResponse)
def prepare_sandbox(payload: SandboxPrepareRequest):
    """Prepare an isolated disposable workspace and inspect candidate test commands."""
    return sandbox_service.prepare_sandbox(payload)


@app.post("/sandbox/reproduce", response_model=SandboxSessionResponse)
def reproduce_bug(payload: ReproductionRequest):
    """Execute reproduction within a verified sandbox and classify outcome."""
    return sandbox_service.reproduce_bug(payload)


@app.get("/sandbox/{session_id}", response_model=SandboxSessionResponse)
def get_sandbox_session(session_id: str):
    """Get status and reproduction outcome of a sandbox session."""
    return sandbox_service.get_session(session_id)


# --- Phase 4 Endpoints ---


@app.post("/localize", response_model=LocalizeResponse)
def localize_bug(payload: LocalizeRequest):
    """Deterministically localize suspected defect locations from issue text and evidence.

    Offline and read-only. No code execution, no repository access.
    """
    return phase4_service.localize(payload)


@app.post("/patch/propose", response_model=PatchProposeResponse)
def propose_patch(payload: PatchProposeRequest):
    """Generate a reviewable patch proposal from localization results.

    Uses the mock deterministic provider or real AI provider. No files are written, applied, or committed.
    """
    return phase4_service.propose_patch(payload)


@app.post("/patch/validate", response_model=PatchValidateResponse)
def validate_patch(payload: PatchValidateRequest):
    """Validate a unified diff against a managed sandbox workspace.

    Security: workspace root is resolved server-side from the session_id.
    Callers cannot specify arbitrary filesystem paths.
    Strictly read-only — no files are written, created, or deleted.
    """
    session = sandbox_service.sessions.get(payload.session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Sandbox session '{payload.session_id}' not found.",
        )
    if not session.workspace_path:
        raise HTTPException(
            status_code=422,
            detail=f"Session '{payload.session_id}' has no active workspace.",
        )
    return phase4_service.validate_patch(payload, session.workspace_path)


# --- Phase 5A Endpoints ---


@app.post("/patch/apply", response_model=PatchApplyResponse)
def apply_patch_endpoint(payload: PatchApplyRequest):
    """Safely apply a validated unified diff inside a managed sandbox workspace.

    Security: workspace root is resolved server-side from session_id.
    Caller cannot specify arbitrary paths. The diff is revalidated immediately
    before applying. Changes are applied in-process with atomic rollback.
    """
    session = sandbox_service.sessions.get(payload.session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Sandbox session '{payload.session_id}' not found.",
        )
    if not session.workspace_path:
        raise HTTPException(
            status_code=422,
            detail=f"Session '{payload.session_id}' has no active workspace.",
        )
    result = apply_patch(
        unified_diff=payload.unified_diff,
        workspace_root=session.workspace_path,
    )
    if result.applied:
        session.is_dirty = True

    return PatchApplyResponse(
        success=result.success,
        applied=result.applied,
        applied_files=result.applied_files,
        errors=result.errors,
    )


# --- Phase 5B Endpoints ---


@app.post("/patch/verify-test", response_model=PatchVerifyTestResponse)
def verify_patch_test_endpoint(payload: PatchVerifyTestRequest):
    """Empirically verify that an applied patch resolves the defect inside Docker.

    Security: Workspace root is resolved server-side from session_id.
    Executes strictly inside the restricted Docker sandbox (--network=none,
    --cap-drop=ALL, non-root user, memory/CPU/PID limits, read-only mount).
    Never executes untrusted code on the host. Requires pre-patch failure
    evidence before claiming FIX_VERIFIED.
    """
    session = sandbox_service.sessions.get(payload.session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Sandbox session '{payload.session_id}' not found.",
        )
    if not session.workspace_path:
        raise HTTPException(
            status_code=422,
            detail=f"Session '{payload.session_id}' has no active workspace.",
        )

    # Determine test command to execute
    test_cmd = payload.test_command
    if not test_cmd and session.candidate_test_commands:
        test_cmd = session.candidate_test_commands[0]

    if not test_cmd:
        raise HTTPException(
            status_code=400,
            detail="No test command provided and no candidate test commands were detected.",
        )

    # Extract pre-patch reproduction evidence
    pre_patch_outcome = None
    if session.reproduction_result:
        pre_patch_outcome = session.reproduction_result.outcome

    expected_pattern = payload.expected_failure_pattern or session.expected_failure_pattern

    result = patch_verifier.verify_patch(
        workspace_path=session.workspace_path,
        test_command=test_cmd,
        pre_patch_outcome=pre_patch_outcome,
        expected_failure_pattern=expected_pattern,
        timeout=payload.timeout or 60,
    )

    return PatchVerifyTestResponse(
        success=True,
        outcome=result.outcome,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_ms=result.duration_ms,
        test_command=result.test_command,
        pre_patch_observed=result.pre_patch_observed,
        details=result.details,
    )


# --- Phase 6B Endpoints ---


@app.post("/patch/repair-loop", response_model=RepairLoopResponse)
def repair_loop_endpoint(payload: RepairLoopRequest):
    """Bounded automated repair loop: generate, validate, apply, and verify a patch inside Docker.

    Security:
      - workspace_path is resolved server-side from session_id; callers cannot specify arbitrary paths.
      - Requires an established REPRODUCED reproduction outcome for the session.
      - All patch execution occurs inside the restricted Docker sandbox.
      - At most 3 attempts; fails closed on security violations or BLOCKED outcomes.
      - FIX_VERIFIED only returned when Phase 5B evidence confirms defect resolved.
      - No Git commit, push, PR creation, or host shell execution.
    """
    session = sandbox_service.sessions.get(payload.session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Sandbox session '{payload.session_id}' not found.",
        )
    if not session.workspace_path:
        raise HTTPException(
            status_code=422,
            detail=f"Session '{payload.session_id}' has no active workspace.",
        )

    # Prevent dirty workspace reuse from prior unverified repair attempts
    if getattr(session, "is_dirty", False):
        return RepairLoopResponse(
            success=True,
            outcome=RepairLoopOutcome.BLOCKED,
            session_id=payload.session_id,
            final_details="Session workspace is in a dirty/modified state from a prior patch. Further repair runs are blocked until the workspace is reset.",
        )

    # Extract pre-patch evidence from session
    pre_patch_outcome = None
    if session.reproduction_result:
        pre_patch_outcome = session.reproduction_result.outcome

    expected_pattern = payload.expected_failure_pattern or session.expected_failure_pattern

    result = repair_loop_service.run(
        session_id=payload.session_id,
        workspace_path=session.workspace_path,
        localization=payload.localization,
        pre_patch_outcome=pre_patch_outcome,
        test_command=payload.test_command,
        provider_name=payload.provider or "mock",
        expected_failure_pattern=expected_pattern,
        context=payload.context,
        test_timeout=payload.test_timeout or 60,
        session_is_dirty=getattr(session, "is_dirty", False),
    )

    # Persist dirty state and last outcome on the session
    session.is_dirty = getattr(result, "workspace_dirty", False)
    session.last_repair_outcome = result.outcome.value

    # Map RepairOutcome -> RepairLoopOutcome (both share same string values)
    outcome_map = {
        RepairOutcome.FIX_VERIFIED:   RepairLoopOutcome.FIX_VERIFIED,
        RepairOutcome.FIX_INCOMPLETE: RepairLoopOutcome.FIX_INCOMPLETE,
        RepairOutcome.BLOCKED:        RepairLoopOutcome.BLOCKED,
    }

    attempt_records = [
        RepairAttemptRecord(
            attempt_number=a.attempt_number,
            proposal_id=a.proposal_id,
            validation_errors=a.validation_errors,
            application_errors=a.application_errors,
            verification_outcome=a.verification_outcome.value if a.verification_outcome else None,
            verification_details=a.verification_details,
            duration_ms=a.duration_ms,
        )
        for a in result.attempts
    ]

    return RepairLoopResponse(
        success=True,
        outcome=outcome_map[result.outcome],
        session_id=result.session_id,
        attempts=attempt_records,
        final_details=result.final_details,
        total_duration_ms=result.total_duration_ms,
        real_ai_call_made=result.real_ai_call_made,
    )


@app.post("/patch/reset-dirty")
def reset_dirty_endpoint(payload: SessionResetRequest):
    """Explicitly reset the dirty state of a sandbox session workspace."""
    session = sandbox_service.sessions.get(payload.session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Sandbox session '{payload.session_id}' not found.",
        )
    session.is_dirty = False
    return {"success": True, "session_id": payload.session_id, "is_dirty": False}

