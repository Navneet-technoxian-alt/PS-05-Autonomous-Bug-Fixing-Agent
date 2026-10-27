import os
from typing import Any, Dict
from fastapi import HTTPException, status
import httpx


GITHUB_API_BASE_URL = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 10.0


class GitHubClient:
    """Client for interacting with the public GitHub REST API."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "PS-05-Autonomous-Bug-Fixing-Agent",
        }
        # Optional token support if provided via environment; secrets are never hardcoded
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def fetch_issue(self, owner: str, repo: str, issue_number: int) -> Dict[str, Any]:
        """Fetch raw issue data from GitHub REST API.
        
        Raises:
            HTTPException: 404 if not found, 429 if rate limited, 504 on timeout,
                           422 if item is a pull request, or 502 for upstream failures.
        """
        api_url = f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/issues/{issue_number}"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(api_url, headers=self._get_headers())
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Request to GitHub API timed out. Please try again later.",
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Network error communicating with GitHub API: {str(exc)}",
            )

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            # GitHub's issues endpoint returns pull requests as issues with a "pull_request" object
            if "pull_request" in data:
                raise HTTPException(
                    status_code=422,
                    detail="The provided URL corresponds to a pull request, not an issue.",
                )
            return data

        if response.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"GitHub issue #{issue_number} not found in repository '{owner}/{repo}'.",
            )

        if response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_429_TOO_MANY_REQUESTS):
            rate_limit_remaining = response.headers.get("x-ratelimit-remaining", "0")
            if rate_limit_remaining == "0" or response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="GitHub API rate limit exceeded. Please try again later.",
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access to GitHub repository issue was forbidden.",
            )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API returned upstream status code {response.status_code}.",
        )
