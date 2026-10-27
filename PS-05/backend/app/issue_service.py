import re
from typing import Tuple
from urllib.parse import urlparse
from fastapi import HTTPException, status

from app.github_client import GitHubClient
from app.schemas import IssueAnalyzeResponse, IssueData

# Matches strictly /<owner>/<repo>/issues/<number>
ISSUE_PATH_PATTERN = re.compile(
    r"^/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/issues/(\d+)/?$"
)


def parse_and_validate_issue_url(url_str: str) -> Tuple[str, str, int]:
    """Validate and parse a GitHub issue URL.
    
    Rules:
    - Must be a valid URL with scheme https.
    - Host must strictly be 'github.com'.
    - Must match /<owner>/<repo>/issues/<issue_number>.
    - Must reject pull requests and arbitrary paths.
    
    Returns:
        Tuple of (owner, repo, issue_number)
        
    Raises:
        HTTPException: status_code=422 if URL is invalid, unallowed host, or a pull request.
    """
    if not isinstance(url_str, str) or not url_str.strip():
        raise HTTPException(
            status_code=422,
            detail="The 'issue_url' field must be a non-empty string.",
        )

    try:
        parsed = urlparse(url_str.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Malformed URL provided: {str(exc)}",
        )

    # Validate scheme
    if parsed.scheme.lower() != "https":
        raise HTTPException(
            status_code=422,
            detail="Only HTTPS URLs are accepted.",
        )

    # Validate host - strictly github.com
    hostname = (parsed.hostname or "").lower()
    if hostname != "github.com":
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported host '{hostname}'. Only 'github.com' is supported.",
        )

    path = parsed.path or ""

    # Reject pull requests explicitly
    if "/pull/" in path.lower() or path.lower().endswith("/pulls"):
        raise HTTPException(
            status_code=422,
            detail="Pull request URLs are not supported. Please supply a repository issue URL.",
        )

    match = ISSUE_PATH_PATTERN.match(path)
    if not match:
        raise HTTPException(
            status_code=422,
            detail="Invalid GitHub issue URL format. Expected: https://github.com/<owner>/<repo>/issues/<number>",
        )

    owner, repo, issue_num_str = match.groups()
    try:
        issue_number = int(issue_num_str)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid issue number in URL.",
        )

    return owner, repo, issue_number


class IssueService:
    """Service to process and analyze GitHub issues."""

    def __init__(self, github_client: GitHubClient = None):
        self.github_client = github_client or GitHubClient()

    def analyze_issue(self, issue_url: str) -> IssueAnalyzeResponse:
        """Validate the URL, fetch issue data via GitHub API, and return structured issue record."""
        owner, repo, issue_number = parse_and_validate_issue_url(issue_url)

        raw_issue = self.github_client.fetch_issue(owner, repo, issue_number)

        labels = [
            label["name"] if isinstance(label, dict) and "name" in label else str(label)
            for label in raw_issue.get("labels", [])
        ]

        user_info = raw_issue.get("user") or {}
        author_login = user_info.get("login", "unknown")

        issue_data = IssueData(
            issue_number=raw_issue.get("number", issue_number),
            title=raw_issue.get("title", ""),
            body=raw_issue.get("body") or "",
            state=raw_issue.get("state", "open"),
            labels=labels,
            author_login=author_login,
            repository_full_name=f"{owner}/{repo}",
            issue_html_url=raw_issue.get("html_url", issue_url),
            created_at=raw_issue.get("created_at", ""),
            updated_at=raw_issue.get("updated_at", ""),
        )

        return IssueAnalyzeResponse(success=True, data=issue_data)
