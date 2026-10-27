from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


# --- Phase 2 Schemas ---

class IssueAnalyzeRequest(BaseModel):
    """Request payload for analyzing a GitHub issue."""
    issue_url: str = Field(
        ...,
        description="Public GitHub issue URL matching https://github.com/owner/repo/issues/number",
        examples=["https://github.com/psf/requests/issues/1234"],
    )


class IssueData(BaseModel):
    """Structured details extracted from a GitHub issue."""
    issue_number: int
    title: str
    body: Optional[str] = None
    state: str
    labels: List[str]
    author_login: str
    repository_full_name: str
    issue_html_url: str
    created_at: str
    updated_at: str


class IssueAnalyzeResponse(BaseModel):
    """Response payload for issue analysis."""
    success: bool
    data: IssueData


# --- Phase 3 Schemas ---

class SandboxState(str, Enum):
    """Explicit lifecycle states for a repository sandbox."""
    PENDING = "pending"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReproductionOutcome(str, Enum):
    """Explicit outcomes for reproduction runs."""
    REPRODUCED = "REPRODUCED"
    NOT_REPRODUCED = "NOT_REPRODUCED"
    BLOCKED = "BLOCKED"


class SandboxPrepareRequest(BaseModel):
    """Request payload to initiate repository sandbox preparation."""
    issue_url: str = Field(
        ...,
        description="Validated GitHub issue URL",
        examples=["https://github.com/testorg/testrepo/issues/42"],
    )
    commit_sha: Optional[str] = Field(
        None,
        description="Optional Git revision or commit SHA to pin",
    )


class ReproductionRequest(BaseModel):
    """Request payload to execute bug reproduction inside a verified sandbox."""
    session_id: str = Field(..., description="ID of prepared sandbox session")
    test_command: Optional[str] = Field(
        None,
        description="Specific test command to run. If omitted, uses primary candidate test command.",
    )
    expected_failure_pattern: Optional[str] = Field(
        None,
        description="Optional string pattern/exception expected to confirm reproduction of the bug.",
    )


class ReproductionResult(BaseModel):
    """Structured outcome of a bug reproduction execution."""
    outcome: ReproductionOutcome
    command: Optional[str] = None
    exit_code: Optional[int] = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    details: str


class SandboxSessionResponse(BaseModel):
    """Summary of sandbox session status, isolated workspace, and reproduction outcome."""
    session_id: str
    repo_url: str
    commit_sha: Optional[str] = None
    state: SandboxState
    workspace_isolated: bool = True
    candidate_test_commands: List[str] = []
    docker_available: bool = False
    security_controls_verified: bool = False
    reproduction_result: Optional[ReproductionResult] = None
    error_message: Optional[str] = None


# --- Phase 4 Schemas ---

class CandidateLocation(BaseModel):
    """A suspected file location inferred from stack traces, issue text, or reproduction output."""
    file_path: str
    line_number: Optional[int] = None
    function_name: Optional[str] = None
    evidence_snippet: str
    source_type: str = Field(..., description="Source of evidence: 'stack_trace', 'reproduction_stderr', 'issue_body', 'issue_title'")
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="Deterministic ranking score between 0.0 and 1.0")
    is_hypothesis: bool = True  # Strictly labeled as hypothesis, never proven root cause


class LocalizationConfidence(str, Enum):
    """Confidence level of deterministic bug localization."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class LocalizationResult(BaseModel):
    """Structured outcome of deterministic bug localization."""
    candidate_locations: List[CandidateLocation] = []
    detected_exceptions: List[str] = []
    confidence: LocalizationConfidence
    confidence_explanation: str
    total_evidence_lines_analyzed: int
    is_root_cause_proven: bool = False  # Guarantees no premature claim of proven root cause


class PatchProposal(BaseModel):
    """A proposed patch with reviewable diff, rationale, and regression tests."""
    proposal_id: str
    provider_name: str
    affected_files: List[str]
    unified_diff: str
    rationale: str
    proposed_regression_tests: List[str] = []
    is_applied: bool = False  # Guarantees patch has not been applied to repository


# --- Phase 4 API Endpoint Schemas ---

# Input size constants (enforced at Pydantic layer)
_MAX_TEXT_INPUT = 50_000
_MAX_DIFF_INPUT = 262_144  # 256 KB

class LocalizeRequest(BaseModel):
    """Request payload for deterministic bug localization."""
    issue_title: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_TEXT_INPUT,
        description="Title of the bug report or issue.",
    )
    issue_body: Optional[str] = Field(
        None,
        max_length=_MAX_TEXT_INPUT,
        description="Full body text of the issue, may include stack traces and code snippets.",
    )
    stack_trace: Optional[str] = Field(
        None,
        max_length=_MAX_TEXT_INPUT,
        description="Standalone stack trace or traceback text.",
    )
    reproduction_stdout: Optional[str] = Field(
        None,
        max_length=_MAX_TEXT_INPUT,
        description="Stdout captured from a reproduction run.",
    )
    reproduction_stderr: Optional[str] = Field(
        None,
        max_length=_MAX_TEXT_INPUT,
        description="Stderr captured from a reproduction run.",
    )


class LocalizeResponse(BaseModel):
    """Response payload for bug localization results."""
    success: bool
    result: LocalizationResult


class PatchProposeRequest(BaseModel):
    """Request payload for generating a reviewable patch proposal via the mock provider."""
    localization: LocalizationResult = Field(
        ...,
        description="Validated localization result containing candidate locations and evidence.",
    )
    context: Optional[dict] = Field(
        None,
        description="Optional context parameters (e.g., repository metadata, issue summary).",
    )


class PatchProposeResponse(BaseModel):
    """Response payload containing a patch proposal for review."""
    success: bool
    proposal: PatchProposal


class PatchValidateRequest(BaseModel):
    """Request payload for validating a unified diff against a managed workspace.

    Security: The session_id is resolved server-side to a managed disposable workspace.
    Callers cannot specify arbitrary filesystem roots.
    """
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="ID of a previously prepared sandbox session whose workspace root will be used for path containment checks.",
    )
    unified_diff: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_DIFF_INPUT,
        description="Unified diff string to validate against the session workspace.",
    )


class PatchValidationError(BaseModel):
    """Individual validation error detail."""
    message: str


class PatchValidateResponse(BaseModel):
    """Response payload for patch validation results."""
    success: bool
    is_valid: bool
    errors: List[str] = []
    affected_files: List[str] = []
    total_files_analyzed: int = 0
    total_hunks_analyzed: int = 0


# --- Phase 5A API Endpoint Schemas ---


class PatchApplyRequest(BaseModel):
    """Request payload for safely applying a unified diff to a managed sandbox workspace.

    Security: The session_id is resolved server-side to an isolated disposable workspace.
    Callers cannot supply arbitrary filesystem paths.
    """
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="ID of a previously prepared sandbox session whose workspace will be patched.",
    )
    unified_diff: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_DIFF_INPUT,
        description="Validated unified diff to apply inside the disposable workspace.",
    )


class PatchApplyResponse(BaseModel):
    """Response payload for patch application results."""
    success: bool
    applied: bool
    applied_files: List[str] = []
    errors: List[str] = []


# --- Phase 5B API Endpoint Schemas ---


class PatchVerificationOutcome(str, Enum):
    """Classification outcome for post-patch test verification."""
    FIX_VERIFIED = "fix_verified"
    FIX_INCOMPLETE = "fix_incomplete"
    NEW_REGRESSION = "new_regression"
    BLOCKED = "blocked"


class PatchVerifyTestRequest(BaseModel):
    """Request payload for executing tests after patch application inside Docker."""
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="ID of a prepared sandbox session whose patched workspace will be tested.",
    )
    test_command: Optional[str] = Field(
        None,
        max_length=1000,
        description="Constrained test command (e.g. 'pytest', 'pytest tests/test_bug.py'). Must match safe profiles.",
    )
    expected_failure_pattern: Optional[str] = Field(
        None,
        max_length=500,
        description="Error or exception pattern previously reproduced, to verify absence of.",
    )
    timeout: Optional[int] = Field(
        60,
        ge=5,
        le=300,
        description="Execution timeout in seconds.",
    )


class PatchVerifyTestResponse(BaseModel):
    """Response payload containing empirical post-patch verification evidence."""
    success: bool
    outcome: PatchVerificationOutcome
    exit_code: Optional[int] = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    duration_ms: Optional[float] = None
    test_command: str = ""
    pre_patch_observed: bool = False
    details: str = ""

