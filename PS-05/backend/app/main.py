from fastapi import FastAPI, HTTPException
from app.schemas import (
    IssueAnalyzeRequest,
    IssueAnalyzeResponse,
    LocalizeRequest,
    LocalizeResponse,
    PatchProposeRequest,
    PatchProposeResponse,
    PatchValidateRequest,
    PatchValidateResponse,
    ReproductionRequest,
    SandboxPrepareRequest,
    SandboxSessionResponse,
)
from app.issue_service import IssueService
from app.sandbox_service import SandboxService
from app.phase4_service import Phase4Service

app = FastAPI(
    title="PS-05 Autonomous Bug-Fixing Agent",
    description="Backend API service for autonomous bug detection, reproduction, and fixing.",
    version="0.1.0",
)

issue_service = IssueService()
sandbox_service = SandboxService()
phase4_service = Phase4Service()


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

