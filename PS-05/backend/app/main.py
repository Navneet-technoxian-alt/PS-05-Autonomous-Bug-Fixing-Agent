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
    ReproductionRequest,
    SandboxPrepareRequest,
    SandboxSessionResponse,
)
from app.issue_service import IssueService
from app.sandbox_service import SandboxService
from app.phase4_service import Phase4Service
from app.patch_applier import apply_patch
from app.patch_verifier import PatchVerifier

app = FastAPI(
    title="PS-05 Autonomous Bug-Fixing Agent",
    description="Backend API service for autonomous bug detection, reproduction, and fixing.",
    version="0.1.0",
)

issue_service = IssueService()
sandbox_service = SandboxService()
phase4_service = Phase4Service()
patch_verifier = PatchVerifier(sandbox_service.sandbox_controller)



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

    Uses the mock deterministic provider. No files are written, applied, or committed.
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

