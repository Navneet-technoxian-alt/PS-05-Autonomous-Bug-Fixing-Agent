import json
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.repo_manager import RepoManager, validate_github_repo_url
from app.sandbox_controller import SandboxController, SandboxSecurityError
from app.reproduction_runner import ReproductionRunner
from app.schemas import ReproductionOutcome, SandboxState

client = TestClient(app)


# --- 1. Repository URL Validation Tests ---

def test_validate_github_repo_url_valid():
    owner, repo = validate_github_repo_url("https://github.com/testorg/testrepo")
    assert owner == "testorg"
    assert repo == "testrepo"

    owner2, repo2 = validate_github_repo_url("https://github.com/my-org/my-project.git")
    assert owner2 == "my-org"
    assert repo2 == "my-project"


def test_validate_github_repo_url_invalid():
    invalid_urls = [
        "http://github.com/testorg/testrepo",
        "https://gitlab.com/testorg/testrepo",
        "not-a-url",
        "https://github.com/onlyonepart",
    ]
    for url in invalid_urls:
        with pytest.raises(HTTPException) as exc:
            validate_github_repo_url(url)
        assert exc.value.status_code == 422


# --- 2. Workspace Isolation & Cleanup Tests ---

def test_workspace_isolation():
    manager = RepoManager()
    session_id = "test-session-123"
    workspace_path = manager.create_isolated_workspace(session_id)

    try:
        assert os.path.exists(workspace_path)
        # Verify workspace is outside current project directory
        app_cwd = os.path.abspath(os.getcwd())
        assert not workspace_path.startswith(app_cwd), "Workspace must never be created inside application source directory."
    finally:
        cleaned = manager.cleanup_workspace(workspace_path)
        assert cleaned is True
        assert not os.path.exists(workspace_path)


# --- 3. Static Test Command Inspection Tests ---

def test_static_inspection_python(tmp_path):
    manager = RepoManager()
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    candidates = manager.inspect_candidate_test_commands(str(tmp_path))
    assert "pytest" in candidates


def test_static_inspection_nodejs(tmp_path):
    manager = RepoManager()
    pkg_json = {"name": "test-pkg", "scripts": {"test": "jest"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg_json), encoding="utf-8")
    candidates = manager.inspect_candidate_test_commands(str(tmp_path))
    assert "npm test" in candidates


def test_static_inspection_go(tmp_path):
    manager = RepoManager()
    (tmp_path / "go.mod").write_text("module example.com/m\n", encoding="utf-8")
    candidates = manager.inspect_candidate_test_commands(str(tmp_path))
    assert "go test ./..." in candidates


def test_static_inspection_rust(tmp_path):
    manager = RepoManager()
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'test'\n", encoding="utf-8")
    candidates = manager.inspect_candidate_test_commands(str(tmp_path))
    assert "cargo test" in candidates


# --- 4. Sandbox Security Controls Verification Tests ---

def test_security_controls_verify_non_root():
    controller = SandboxController(docker_path="mock_docker")
    with patch.object(controller, "is_docker_available", return_value=True):
        verified, reasons = controller.verify_security_controls(
            workspace_path="/tmp/test",
            user_id="0",
        )
        assert verified is False
        assert any("Root execution is prohibited" in r for r in reasons)


def test_security_controls_verify_network_disabled():
    controller = SandboxController(docker_path="mock_docker")
    with patch.object(controller, "is_docker_available", return_value=True):
        verified, reasons = controller.verify_security_controls(
            workspace_path="/tmp/test",
            network_enabled=True,
        )
        assert verified is False
        assert any("Network access must be disabled" in r for r in reasons)


def test_security_controls_verify_socket_mount_blocked():
    controller = SandboxController(docker_path="mock_docker")
    with patch.object(controller, "is_docker_available", return_value=True):
        verified, reasons = controller.verify_security_controls(
            workspace_path="/tmp/test",
            volume_mounts=["/tmp/test", "/var/run/docker.sock:/var/run/docker.sock"],
        )
        assert verified is False
        assert any("docker.sock" in r for r in reasons)


def test_build_safe_docker_command_flags():
    controller = SandboxController(docker_path="docker")
    with patch.object(controller, "is_docker_available", return_value=True):
        cmd = controller.build_safe_docker_command(
            workspace_path="/tmp/mock_workspace",
            test_command="pytest",
        )
        assert "--network=none" in cmd
        assert "--cap-drop=ALL" in cmd
        assert "--user=1000:1000" in cmd
        assert "--memory=1g" in cmd
        assert "--cpus=1.0" in cmd
        assert "--pids-limit=100" in cmd
        assert "-w" in cmd and "/workspace" in cmd


# --- 5. Reproduction Outcome Classification Tests ---

def test_classify_outcome_reproduced_with_pattern():
    runner = ReproductionRunner()
    outcome, details = runner.classify_outcome(
        exit_code=1,
        timed_out=False,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
        expected_failure_pattern="ZeroDivisionError",
    )
    assert outcome == ReproductionOutcome.REPRODUCED
    assert "successfully reproduced" in details.lower()


def test_classify_outcome_not_reproduced_clean_exit():
    runner = ReproductionRunner()
    outcome, details = runner.classify_outcome(
        exit_code=0,
        timed_out=False,
        stdout="All 10 tests passed.",
        stderr="",
        expected_failure_pattern="ZeroDivisionError",
    )
    # CRITICAL: Clean completion does not equal reproduced!
    assert outcome == ReproductionOutcome.NOT_REPRODUCED
    assert "did not manifest" in details.lower()


def test_classify_outcome_blocked_on_timeout():
    runner = ReproductionRunner()
    outcome, details = runner.classify_outcome(
        exit_code=None,
        timed_out=True,
        stdout="",
        stderr="",
    )
    assert outcome == ReproductionOutcome.BLOCKED
    assert "timed out" in details.lower()


def test_classify_outcome_blocked_when_docker_missing():
    controller = SandboxController(docker_path=None)
    with patch.object(controller, "is_docker_available", return_value=False):
        runner = ReproductionRunner(sandbox_controller=controller)
        res = runner.run_reproduction(workspace_path="/tmp/mock", test_command="pytest")
        assert res.outcome == ReproductionOutcome.BLOCKED
        assert "docker is not installed" in res.details.lower() or "manual docker verification" in res.details.lower()


# --- 6. End-to-End Sandbox Lifecycle State Flow Tests ---

def test_sandbox_prepare_and_reproduce_api_flow(tmp_path):
    mock_sha = "abcdef1234567890abcdef1234567890abcdef12"

    with patch("app.repo_manager.RepoManager.clone_repository", return_value=mock_sha), \
         patch("app.repo_manager.RepoManager.inspect_candidate_test_commands", return_value=["pytest"]), \
         patch("app.sandbox_controller.SandboxController.is_docker_available", return_value=False):

        # 1. Prepare sandbox from validated issue URL
        prepare_res = client.post(
            "/sandbox/prepare",
            json={"issue_url": "https://github.com/testorg/testrepo/issues/42"},
        )
        assert prepare_res.status_code == 200
        data = prepare_res.json()
        session_id = data["session_id"]
        assert data["state"] == SandboxState.READY
        assert data["commit_sha"] == mock_sha
        assert data["candidate_test_commands"] == ["pytest"]
        assert data["docker_available"] is False

        # 2. Trigger reproduction (Docker unavailable -> returns BLOCKED)
        reproduce_res = client.post(
            "/sandbox/reproduce",
            json={
                "session_id": session_id,
                "test_command": "pytest tests/test_bug.py",
                "expected_failure_pattern": "AssertionError",
            },
        )
        assert reproduce_res.status_code == 200
        rep_data = reproduce_res.json()
        assert rep_data["state"] == SandboxState.COMPLETED
        assert rep_data["reproduction_result"]["outcome"] == ReproductionOutcome.BLOCKED
        assert "docker" in rep_data["reproduction_result"]["details"].lower()

        # 3. Retrieve session status
        get_res = client.get(f"/sandbox/{session_id}")
        assert get_res.status_code == 200
        assert get_res.json()["session_id"] == session_id
