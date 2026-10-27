import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple
from fastapi import HTTPException

# Regex for valid GitHub repository URL: https://github.com/<owner>/<repo>
GITHUB_REPO_URL_PATTERN = re.compile(
    r"^https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?/?$"
)


def validate_github_repo_url(repo_url: str) -> Tuple[str, str]:
    """Validate that repository URL is strictly a public HTTPS URL on github.com.
    
    Returns:
        (owner, repo) tuple
        
    Raises:
        HTTPException(422) if invalid or untrusted.
    """
    if not isinstance(repo_url, str) or not repo_url.strip():
        raise HTTPException(status_code=422, detail="Repository URL must be a non-empty string.")

    cleaned_url = repo_url.strip()
    match = GITHUB_REPO_URL_PATTERN.match(cleaned_url)
    if not match:
        raise HTTPException(
            status_code=422,
            detail="Invalid repository URL. Only 'https://github.com/<owner>/<repo>' is accepted.",
        )

    owner, repo = match.groups()
    return owner, repo


class RepoManager:
    """Manages isolated, disposable workspaces and static test command inspection."""

    def __init__(self, base_workspace_dir: Optional[str] = None):
        # Use system temp directory or designated sandbox directory to guarantee isolation
        self.base_workspace_dir = base_workspace_dir or tempfile.gettempdir()

    def create_isolated_workspace(self, session_id: str) -> str:
        """Create an isolated, disposable directory outside of the application source directory."""
        workspace_dir = tempfile.mkdtemp(prefix=f"ps05_sandbox_{session_id}_", dir=self.base_workspace_dir)
        return os.path.abspath(workspace_dir)

    def clone_repository(
        self,
        repo_url: str,
        workspace_path: str,
        commit_sha: Optional[str] = None,
        timeout: int = 120,
    ) -> str:
        """Clone repository into the isolated workspace and record the commit SHA.
        
        Guarantees that cloning never occurs into application source.
        """
        owner, repo = validate_github_repo_url(repo_url)
        clone_url = f"https://github.com/{owner}/{repo}.git"

        # Clone repository into workspace
        clone_cmd = ["git", "clone", clone_url, workspace_path]
        clone_res = subprocess.run(
            clone_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        if clone_res.returncode != 0:
            raise RuntimeError(f"Git clone failed: {clone_res.stderr.strip()}")

        # If a specific commit SHA was requested, checkout that revision
        if commit_sha:
            checkout_cmd = ["git", "-C", workspace_path, "checkout", commit_sha]
            checkout_res = subprocess.run(
                checkout_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            if checkout_res.returncode != 0:
                raise RuntimeError(f"Git checkout '{commit_sha}' failed: {checkout_res.stderr.strip()}")

        # Record exact commit SHA
        rev_cmd = ["git", "-C", workspace_path, "rev-parse", "HEAD"]
        rev_res = subprocess.run(
            rev_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        if rev_res.returncode != 0:
            raise RuntimeError(f"Failed to resolve commit SHA: {rev_res.stderr.strip()}")

        return rev_res.stdout.strip()

    def inspect_candidate_test_commands(self, workspace_path: str) -> List[str]:
        """Inspect repository metadata to identify candidate test commands.
        
        CRITICAL SECURITY REQUIREMENT:
        Performs purely static inspection of files.
        Never executes setup scripts, package lifecycle scripts, Makefiles, or arbitrary code.
        """
        candidates: List[str] = []

        if not os.path.isdir(workspace_path):
            return candidates

        # 1. Python projects
        has_python_tests = any(
            os.path.exists(os.path.join(workspace_path, f))
            for f in ["pytest.ini", "setup.cfg", "pyproject.toml", "tox.ini"]
        ) or os.path.isdir(os.path.join(workspace_path, "tests"))

        if has_python_tests:
            candidates.append("pytest")

        if os.path.exists(os.path.join(workspace_path, "manage.py")):
            candidates.append("python manage.py test")

        # 2. Node.js projects (Inspect package.json statically)
        package_json_path = os.path.join(workspace_path, "package.json")
        if os.path.isfile(package_json_path):
            try:
                with open(package_json_path, "r", encoding="utf-8") as f:
                    pkg_data = json.load(f)
                    scripts = pkg_data.get("scripts", {})
                    if "test" in scripts and scripts["test"].strip():
                        candidates.append("npm test")
            except Exception:
                # Malformed package.json; do not execute anything
                pass

        # 3. Rust projects
        if os.path.isfile(os.path.join(workspace_path, "Cargo.toml")):
            candidates.append("cargo test")

        # 4. Go projects
        if os.path.isfile(os.path.join(workspace_path, "go.mod")):
            candidates.append("go test ./...")

        # Fallback default if tests dir exists but no explicit framework detected
        if not candidates and os.path.isdir(os.path.join(workspace_path, "tests")):
            candidates.append("pytest")

        return candidates

    def cleanup_workspace(self, workspace_path: str) -> bool:
        """Safely delete the isolated disposable workspace."""
        if workspace_path and os.path.exists(workspace_path):
            # Guard against deleting system or application paths
            if workspace_path == "/" or workspace_path == os.getcwd():
                return False
            shutil.rmtree(workspace_path, ignore_errors=True)
            return True
        return False
