from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx

from app.main import app
from app.issue_service import parse_and_validate_issue_url
from app.github_client import GitHubClient

client = TestClient(app)

MOCK_GITHUB_ISSUE_PAYLOAD = {
    "number": 42,
    "title": "Division by zero in calculation engine",
    "body": "When input is zero, the engine crashes without catching ZeroDivisionError.",
    "state": "open",
    "labels": [{"name": "bug"}, {"name": "priority-high"}],
    "user": {"login": "testuser"},
    "html_url": "https://github.com/testorg/testrepo/issues/42",
    "created_at": "2026-10-01T08:30:00Z",
    "updated_at": "2026-10-02T09:15:00Z",
}


# --- URL Parsing & Validation Tests ---

def test_parse_valid_issue_url():
    owner, repo, number = parse_and_validate_issue_url("https://github.com/testorg/testrepo/issues/42")
    assert owner == "testorg"
    assert repo == "testrepo"
    assert number == 42


def test_parse_valid_issue_url_with_trailing_slash():
    owner, repo, number = parse_and_validate_issue_url("https://github.com/psf/requests/issues/1000/")
    assert owner == "psf"
    assert repo == "requests"
    assert number == 1000


def test_reject_insecure_http_url():
    with pytest.raises(HTTPException) as exc:
        parse_and_validate_issue_url("http://github.com/testorg/testrepo/issues/42")
    assert exc.value.status_code == 422
    assert "Only HTTPS URLs are accepted" in exc.value.detail


def test_reject_untrusted_host():
    with pytest.raises(HTTPException) as exc:
        parse_and_validate_issue_url("https://gitlab.com/testorg/testrepo/issues/42")
    assert exc.value.status_code == 422
    assert "Unsupported host" in exc.value.detail


def test_reject_malformed_url():
    with pytest.raises(HTTPException) as exc:
        parse_and_validate_issue_url("not-a-valid-url")
    assert exc.value.status_code == 422


def test_reject_pull_request_url():
    with pytest.raises(HTTPException) as exc:
        parse_and_validate_issue_url("https://github.com/testorg/testrepo/pull/42")
    assert exc.value.status_code == 422
    assert "Pull request URLs are not supported" in exc.value.detail


def test_reject_repo_root_or_non_issue_paths():
    invalid_urls = [
        "https://github.com/testorg/testrepo",
        "https://github.com/testorg/testrepo/issues",
        "https://github.com/testorg/testrepo/issues/not-a-number",
        "https://github.com/testorg/testrepo/actions",
    ]
    for url in invalid_urls:
        with pytest.raises(HTTPException) as exc:
            parse_and_validate_issue_url(url)
        assert exc.value.status_code == 422


# --- API Endpoint POST /issues/analyze Tests ---

def test_analyze_issue_success():
    with patch("app.github_client.GitHubClient.fetch_issue", return_value=MOCK_GITHUB_ISSUE_PAYLOAD):
        response = client.post(
            "/issues/analyze",
            json={"issue_url": "https://github.com/testorg/testrepo/issues/42"},
        )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    issue = res_data["data"]
    assert issue["issue_number"] == 42
    assert issue["title"] == "Division by zero in calculation engine"
    assert issue["body"] == "When input is zero, the engine crashes without catching ZeroDivisionError."
    assert issue["state"] == "open"
    assert issue["labels"] == ["bug", "priority-high"]
    assert issue["author_login"] == "testuser"
    assert issue["repository_full_name"] == "testorg/testrepo"
    assert issue["issue_html_url"] == "https://github.com/testorg/testrepo/issues/42"
    assert issue["created_at"] == "2026-10-01T08:30:00Z"
    assert issue["updated_at"] == "2026-10-02T09:15:00Z"


def test_analyze_issue_rejects_pull_request():
    response = client.post(
        "/issues/analyze",
        json={"issue_url": "https://github.com/testorg/testrepo/pull/42"},
    )
    assert response.status_code == 422
    assert "Pull request URLs are not supported" in response.json()["detail"]


def test_analyze_issue_rejects_untrusted_host():
    response = client.post(
        "/issues/analyze",
        json={"issue_url": "https://attacker.com/testorg/testrepo/issues/42"},
    )
    assert response.status_code == 422
    assert "Unsupported host" in response.json()["detail"]


def test_analyze_issue_rejects_malformed_url():
    response = client.post(
        "/issues/analyze",
        json={"issue_url": "https://github.com/invalid"},
    )
    assert response.status_code == 422


def test_analyze_issue_not_found():
    with patch("httpx.Client.get") as mock_get:
        mock_response = httpx.Response(
            status_code=404,
            request=httpx.Request("GET", "https://api.github.com/repos/testorg/testrepo/issues/999"),
        )
        mock_get.return_value = mock_response

        response = client.post(
            "/issues/analyze",
            json={"issue_url": "https://github.com/testorg/testrepo/issues/999"},
        )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_analyze_issue_rate_limit_exceeded():
    with patch("httpx.Client.get") as mock_get:
        mock_response = httpx.Response(
            status_code=403,
            headers={"x-ratelimit-remaining": "0"},
            request=httpx.Request("GET", "https://api.github.com/repos/testorg/testrepo/issues/42"),
        )
        mock_get.return_value = mock_response

        response = client.post(
            "/issues/analyze",
            json={"issue_url": "https://github.com/testorg/testrepo/issues/42"},
        )
    assert response.status_code == 429
    assert "rate limit exceeded" in response.json()["detail"].lower()


def test_analyze_issue_upstream_error():
    with patch("httpx.Client.get") as mock_get:
        mock_response = httpx.Response(
            status_code=500,
            request=httpx.Request("GET", "https://api.github.com/repos/testorg/testrepo/issues/42"),
        )
        mock_get.return_value = mock_response

        response = client.post(
            "/issues/analyze",
            json={"issue_url": "https://github.com/testorg/testrepo/issues/42"},
        )
    assert response.status_code == 502
    assert "upstream status code 500" in response.json()["detail"].lower()


def test_analyze_issue_timeout():
    with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Connection timed out")):
        response = client.post(
            "/issues/analyze",
            json={"issue_url": "https://github.com/testorg/testrepo/issues/42"},
        )
    assert response.status_code == 504
    assert "timed out" in response.json()["detail"].lower()


def test_analyze_issue_api_returns_pull_request():
    # If URL is /issues/42 but GitHub reveals it is a PR object
    pr_data = dict(MOCK_GITHUB_ISSUE_PAYLOAD)
    pr_data["pull_request"] = {"url": "https://api.github.com/repos/testorg/testrepo/pulls/42"}

    with patch("httpx.Client.get") as mock_get:
        mock_response = httpx.Response(
            status_code=200,
            json=pr_data,
            request=httpx.Request("GET", "https://api.github.com/repos/testorg/testrepo/issues/42"),
        )
        mock_get.return_value = mock_response

        response = client.post(
            "/issues/analyze",
            json={"issue_url": "https://github.com/testorg/testrepo/issues/42"},
        )
    assert response.status_code == 422
    assert "corresponds to a pull request" in response.json()["detail"]
