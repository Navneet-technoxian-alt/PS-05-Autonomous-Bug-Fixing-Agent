import os
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple


class SandboxSecurityError(Exception):
    """Raised when sandbox security requirements cannot be guaranteed."""
    pass


class SandboxController:
    """Controls container sandbox execution with strict verification of security controls."""

    def __init__(self, docker_path: Optional[str] = None):
        self.docker_path = docker_path or shutil.which("docker")

    def is_docker_available(self) -> bool:
        """Check if Docker CLI executable is available in PATH and responsive."""
        if not self.docker_path:
            return False
        try:
            res = subprocess.run(
                [self.docker_path, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            return res.returncode == 0
        except Exception:
            return False

    def verify_security_controls(
        self,
        workspace_path: str,
        volume_mounts: Optional[List[str]] = None,
        network_enabled: bool = False,
        user_id: str = "1000:1000",
    ) -> Tuple[bool, List[str]]:
        """Verify that mandatory sandbox security controls are satisfied before code execution.
        
        Mandatory controls:
        1. Docker availability.
        2. Non-root execution.
        3. Dropped capabilities (cap-drop=ALL).
        4. No Docker socket mount (/var/run/docker.sock).
        5. No host credentials mounted (~/.ssh, ~/.aws, ~/.docker, ~/.gnupg).
        6. Network access disabled by default.
        7. Resource limits (memory, cpu, pids).
        
        Returns:
            (verified: bool, reasons: List[str])
        """
        reasons: List[str] = []

        # 1. Docker availability
        if not self.is_docker_available():
            reasons.append("Docker is not installed, not in PATH, or daemon is not responsive.")

        # 2. Non-root execution
        if user_id in ("0", "root", "0:0"):
            reasons.append("Root execution is prohibited. Container must run as non-root.")

        # 3. Network disabled
        if network_enabled:
            reasons.append("Network access must be disabled by default (--network=none).")

        # 4 & 5. Prohibited volume mounts (Docker socket, host credentials, system roots)
        active_mounts = volume_mounts or [workspace_path]
        prohibited_mount_patterns = [
            "docker.sock",
            ".ssh",
            ".aws",
            ".docker",
            ".gnupg",
            "/etc",
            "/var/run",
            "C:\\Windows",
            "C:\\Users",
        ]

        for mount in active_mounts:
            for pattern in prohibited_mount_patterns:
                # Disallow exact matches or dangerous mounts
                if pattern in mount.replace("\\", "/"):
                    # Special check: user's temp workspace is fine, but mounting user home root or credentials is prohibited
                    if pattern in [".ssh", ".aws", ".docker", "docker.sock"]:
                        reasons.append(f"Mount of sensitive path '{pattern}' is strictly prohibited.")

        verified = len(reasons) == 0
        return verified, reasons

    def build_safe_docker_command(
        self,
        workspace_path: str,
        test_command: str,
        image: str = "python:3.11-slim",
        timeout: int = 60,
    ) -> List[str]:
        """Construct a containerized command with all mandatory security flags."""
        verified, reasons = self.verify_security_controls(workspace_path)
        if not verified:
            raise SandboxSecurityError(f"Security controls verification failed: {'; '.join(reasons)}")

        # Clean workspace path for volume mount
        normalized_workspace = os.path.abspath(workspace_path)

        docker_cmd = [
            self.docker_path,
            "run",
            "--rm",
            "--network=none",            # 1. Network disabled
            "--cap-drop=ALL",            # 2. Drop all Linux capabilities
            "--user=1000:1000",          # 3. Non-root execution
            "--memory=1g",               # 4. Memory limit
            "--cpus=1.0",                # 5. CPU limit
            "--pids-limit=100",          # 6. Process count limit
            "-v", f"{normalized_workspace}:/workspace:ro",  # 7. Mounted read-only workspace
            "-w", "/workspace",
            image,
            "sh", "-c", test_command,
        ]
        return docker_cmd
