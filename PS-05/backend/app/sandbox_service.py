import uuid
from typing import Dict, Optional
from fastapi import HTTPException

from app.issue_service import parse_and_validate_issue_url
from app.repo_manager import RepoManager
from app.sandbox_controller import SandboxController
from app.reproduction_runner import ReproductionRunner
from app.schemas import (
    ReproductionOutcome,
    ReproductionRequest,
    ReproductionResult,
    SandboxPrepareRequest,
    SandboxSessionResponse,
    SandboxState,
)


class SandboxSessionData:
    """Internal session state model."""
    def __init__(self, session_id: str, repo_url: str, issue_url: str, commit_sha: Optional[str] = None):
        self.session_id = session_id
        self.repo_url = repo_url
        self.issue_url = issue_url
        self.commit_sha = commit_sha
        self.state = SandboxState.PENDING
        self.workspace_path: Optional[str] = None
        self.candidate_test_commands: list[str] = []
        self.reproduction_result: Optional[ReproductionResult] = None
        self.expected_failure_pattern: Optional[str] = None
        self.error_message: Optional[str] = None



class SandboxService:
    """Orchestrates sandbox lifecycle states, isolated workspace provisioning, and bug reproduction."""

    def __init__(
        self,
        repo_manager: Optional[RepoManager] = None,
        sandbox_controller: Optional[SandboxController] = None,
        reproduction_runner: Optional[ReproductionRunner] = None,
    ):
        self.repo_manager = repo_manager or RepoManager()
        self.sandbox_controller = sandbox_controller or SandboxController()
        self.reproduction_runner = reproduction_runner or ReproductionRunner(self.sandbox_controller)
        self.sessions: Dict[str, SandboxSessionData] = {}

    def prepare_sandbox(self, request: SandboxPrepareRequest) -> SandboxSessionResponse:
        """Provision an isolated workspace for a repository derived from an issue URL."""
        # 1. Accept only validated GitHub URLs derived from the existing issue intake flow
        owner, repo, _ = parse_and_validate_issue_url(request.issue_url)
        repo_url = f"https://github.com/{owner}/{repo}"

        session_id = str(uuid.uuid4())[:8]
        session = SandboxSessionData(
            session_id=session_id,
            repo_url=repo_url,
            issue_url=request.issue_url,
            commit_sha=request.commit_sha,
        )
        self.sessions[session_id] = session

        # 2. State transition: PREPARING
        session.state = SandboxState.PREPARING

        try:
            # 3. Create isolated disposable workspace (never inside source code)
            workspace = self.repo_manager.create_isolated_workspace(session_id)
            session.workspace_path = workspace

            # 4. Clone repository into isolated workspace and pin commit revision
            actual_sha = self.repo_manager.clone_repository(
                repo_url=repo_url,
                workspace_path=workspace,
                commit_sha=request.commit_sha,
            )
            session.commit_sha = actual_sha

            # 5. Inspect repository metadata for candidate test commands without executing code
            session.candidate_test_commands = self.repo_manager.inspect_candidate_test_commands(workspace)

            # 6. State transition: READY
            session.state = SandboxState.READY

        except Exception as exc:
            session.state = SandboxState.FAILED
            session.error_message = str(exc)
            if session.workspace_path:
                self.repo_manager.cleanup_workspace(session.workspace_path)
            raise HTTPException(status_code=500, detail=f"Sandbox preparation failed: {str(exc)}")

        return self.get_session_response(session_id)

    def reproduce_bug(self, request: ReproductionRequest) -> SandboxSessionResponse:
        """Run reproduction inside the prepared sandbox."""
        session = self.sessions.get(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Sandbox session '{request.session_id}' not found.")

        if session.state not in (SandboxState.READY, SandboxState.COMPLETED, SandboxState.FAILED):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot run reproduction in state '{session.state}'. Session must be in 'ready' state.",
            )

        # Determine test command to execute
        test_cmd = request.test_command
        if not test_cmd and session.candidate_test_commands:
            test_cmd = session.candidate_test_commands[0]

        if not test_cmd:
            raise HTTPException(
                status_code=400,
                detail="No test command provided and no candidate test commands were detected in repository metadata.",
            )

        # State transition: RUNNING
        session.state = SandboxState.RUNNING

        # Execute reproduction runner
        result = self.reproduction_runner.run_reproduction(
            workspace_path=session.workspace_path or "",
            test_command=test_cmd,
            expected_failure_pattern=request.expected_failure_pattern,
        )

        session.reproduction_result = result
        session.expected_failure_pattern = request.expected_failure_pattern

        # State transition: COMPLETED
        session.state = SandboxState.COMPLETED


        return self.get_session_response(request.session_id)

    def get_session(self, session_id: str) -> SandboxSessionResponse:
        """Retrieve session status and results."""
        if session_id not in self.sessions:
            raise HTTPException(status_code=404, detail=f"Sandbox session '{session_id}' not found.")
        return self.get_session_response(session_id)

    def get_session_response(self, session_id: str) -> SandboxSessionResponse:
        """Build standard response model from session data."""
        session = self.sessions[session_id]
        docker_ok = self.sandbox_controller.is_docker_available()
        sec_verified = False
        if docker_ok and session.workspace_path:
            sec_verified, _ = self.sandbox_controller.verify_security_controls(session.workspace_path)

        return SandboxSessionResponse(
            session_id=session.session_id,
            repo_url=session.repo_url,
            commit_sha=session.commit_sha,
            state=session.state,
            workspace_isolated=True,
            candidate_test_commands=session.candidate_test_commands,
            docker_available=docker_ok,
            security_controls_verified=sec_verified,
            reproduction_result=session.reproduction_result,
            error_message=session.error_message,
        )

    def cleanup_session(self, session_id: str) -> bool:
        """Clean up disposable workspace and session."""
        session = self.sessions.get(session_id)
        if session and session.workspace_path:
            self.repo_manager.cleanup_workspace(session.workspace_path)
            session.workspace_path = None
            return True
        return False
