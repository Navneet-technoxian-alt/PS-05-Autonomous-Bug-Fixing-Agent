"""
test_ai_patch_provider.py — Comprehensive tests for Phase 6A Patch Providers

Covers:
  - MockPatchProvider determinism and safety controls.
  - AIPatchProvider disabled state when unconfigured.
  - Prompt sanitization and secret defense.
  - Successful mocked AI provider response and code fence parsing.
  - Timeout, network error, and malformed response handling.
  - Oversized output and null byte rejections.
  - Strict PatchValidator integration rejecting unsafe AI-generated diffs.
  - Secret redaction preventing API key leakage in errors.
  - API endpoint /patch/propose provider routing and error handling.
"""

import json
import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
import httpx

from app.main import app
from app.patch_provider import (
    AIPatchProvider,
    AIPatchProviderConfig,
    MockPatchProvider,
    PatchProviderError,
    build_sanitized_patch_prompt,
    get_patch_provider,
    sanitize_prompt_context,
)
from app.schemas import (
    CandidateLocation,
    LocalizationConfidence,
    LocalizationResult,
    PatchProposal,
)

client = TestClient(app)

SAMPLE_LOCALIZATION = LocalizationResult(
    candidate_locations=[
        CandidateLocation(
            file_path="app/calculator.py",
            line_number=10,
            function_name="divide",
            evidence_snippet="return a / b",
            source_type="stack_trace",
            relevance_score=0.95,
            is_hypothesis=True,
        )
    ],
    detected_exceptions=["ZeroDivisionError"],
    confidence=LocalizationConfidence.HIGH,
    confidence_explanation="High confidence: verified stack trace.",
    total_evidence_lines_analyzed=5,
    is_root_cause_proven=False,
)

VALID_AI_DIFF = (
    "--- a/app/calculator.py\n"
    "+++ b/app/calculator.py\n"
    "@@ -10,3 +10,5 @@\n"
    "+    if b == 0:\n"
    "+        raise ValueError('Cannot divide by zero')\n"
    "     return a / b\n"
)


# ---------------------------------------------------------------------------
# 1. Deterministic Mock Provider Tests
# ---------------------------------------------------------------------------

def test_mock_provider_determinism():
    """Verify MockPatchProvider generates deterministic, valid outputs without side effects."""
    provider = MockPatchProvider()
    res1 = provider.propose_patch(SAMPLE_LOCALIZATION)
    res2 = provider.propose_patch(SAMPLE_LOCALIZATION)

    assert isinstance(res1, PatchProposal)
    assert isinstance(res2, PatchProposal)
    assert res1.unified_diff == res2.unified_diff
    assert res1.affected_files == res2.affected_files == ["app/calculator.py"]
    assert res1.rationale == res2.rationale
    assert res1.proposed_regression_tests == res2.proposed_regression_tests
    assert res1.is_applied is False
    assert res2.is_applied is False
    assert "ZeroDivisionError" in res1.unified_diff


def test_mock_provider_empty_candidates():
    """Verify MockPatchProvider gracefully handles empty localization candidates."""
    provider = MockPatchProvider()
    empty_loc = LocalizationResult(
        candidate_locations=[],
        detected_exceptions=[],
        confidence=LocalizationConfidence.NONE,
        confidence_explanation="No locations.",
        total_evidence_lines_analyzed=0,
    )
    res = provider.propose_patch(empty_loc)
    assert res.unified_diff == ""
    assert res.affected_files == []
    assert res.is_applied is False


def test_mock_provider_none_input():
    """Verify MockPatchProvider rejects None localization."""
    provider = MockPatchProvider()
    with pytest.raises(PatchProviderError, match="Localization result must not be None"):
        provider.propose_patch(None)


# ---------------------------------------------------------------------------
# 2. Configuration & Disabled State
# ---------------------------------------------------------------------------

def test_ai_provider_disabled_when_unconfigured(monkeypatch):
    """Verify AIPatchProvider is disabled and rejects calls when API keys are absent."""
    monkeypatch.delenv("AI_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    provider = AIPatchProvider(config=AIPatchProviderConfig.from_env())
    assert provider.is_configured is False

    with pytest.raises(PatchProviderError, match="AI patch provider is not configured"):
        provider.propose_patch(SAMPLE_LOCALIZATION)


def test_ai_provider_no_network_when_unconfigured(monkeypatch):
    """Verify that unconfigured provider makes zero network calls."""
    monkeypatch.delenv("AI_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    provider = AIPatchProvider()
    with patch("httpx.Client") as mock_client:
        with pytest.raises(PatchProviderError):
            provider.propose_patch(SAMPLE_LOCALIZATION)
        mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Input Sanitization & Secret Defense
# ---------------------------------------------------------------------------

def test_sanitize_prompt_context_scrubs_secrets_and_bounds():
    """Verify tokens and secrets are redacted and long input is truncated."""
    raw = "User token: sk-abcdef1234567890abcdef1234567890abcdef12345678 and GitHub ghp_123456789012345678901234567890123456"
    sanitized = sanitize_prompt_context(raw)
    assert "sk-" not in sanitized
    assert "ghp_" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized

    long_str = "x" * 6000
    bounded = sanitize_prompt_context(long_str, max_chars=100)
    assert len(bounded) <= 120
    assert "[TRUNCATED]" in bounded


def test_build_sanitized_prompt_excludes_sensitive_files():
    """Verify sensitive files (.env, credentials, id_rsa) are excluded from AI prompts."""
    loc = LocalizationResult(
        candidate_locations=[
            CandidateLocation(
                file_path=".env",
                line_number=1,
                evidence_snippet="API_KEY=supersecret",
                source_type="stack_trace",
                relevance_score=0.99,
            ),
            CandidateLocation(
                file_path="app/calculator.py",
                line_number=10,
                evidence_snippet="return a / b",
                source_type="stack_trace",
                relevance_score=0.85,
            ),
        ],
        detected_exceptions=["KeyError"],
        confidence=LocalizationConfidence.HIGH,
        confidence_explanation="High confidence.",
        total_evidence_lines_analyzed=10,
    )
    sys_prompt, user_prompt = build_sanitized_patch_prompt(loc)
    assert ".env" not in user_prompt
    assert "supersecret" not in user_prompt
    assert "app/calculator.py" in user_prompt


# ---------------------------------------------------------------------------
# 4. Successful Mocked AI Provider Responses
# ---------------------------------------------------------------------------

def test_ai_provider_successful_proposal():
    """Verify valid model output is correctly parsed into a PatchProposal."""
    config = AIPatchProviderConfig(api_key="mock-test-key")
    provider = AIPatchProvider(config=config)

    model_response_content = json.dumps({
        "unified_diff": VALID_AI_DIFF,
        "rationale": "Add guard clause for zero divisor.",
        "proposed_regression_tests": ["pytest tests/test_calculator.py"],
    })

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": model_response_content}}]
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        proposal = provider.propose_patch(SAMPLE_LOCALIZATION)

        assert isinstance(proposal, PatchProposal)
        assert proposal.unified_diff == VALID_AI_DIFF
        assert proposal.affected_files == ["app/calculator.py"]
        assert proposal.rationale == "Add guard clause for zero divisor."
        assert proposal.proposed_regression_tests == ["pytest tests/test_calculator.py"]
        assert proposal.is_applied is False
        assert proposal.provider_name == "ai-provider-gpt-4o-mini"


def test_ai_provider_strips_markdown_code_fences():
    """Verify model output wrapped in markdown code fences is cleanly stripped."""
    config = AIPatchProviderConfig(api_key="mock-test-key")
    provider = AIPatchProvider(config=config)

    payload = {
        "unified_diff": VALID_AI_DIFF,
        "rationale": "Add guard clause.",
        "proposed_regression_tests": ["pytest tests/test_calc.py"],
    }
    raw_content = f"```json\n{json.dumps(payload)}\n```"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": raw_content}}]
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        proposal = provider.propose_patch(SAMPLE_LOCALIZATION)
        assert proposal.unified_diff == VALID_AI_DIFF
        assert proposal.rationale == "Add guard clause."


# ---------------------------------------------------------------------------
# 5. Error & Malformed Response Handling
# ---------------------------------------------------------------------------

def test_ai_provider_handles_timeout():
    """Verify provider handles HTTP timeouts gracefully with clear error."""
    config = AIPatchProviderConfig(api_key="mock-test-key", timeout_seconds=5.0)
    provider = AIPatchProvider(config=config)

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.side_effect = httpx.TimeoutException("Connection timed out")
        mock_client_cls.return_value = mock_client_instance

        with pytest.raises(PatchProviderError, match="timed out"):
            provider.propose_patch(SAMPLE_LOCALIZATION)


def test_ai_provider_handles_malformed_json():
    """Verify provider rejects non-JSON or malformed model responses."""
    config = AIPatchProviderConfig(api_key="mock-test-key")
    provider = AIPatchProvider(config=config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "Here is your fix: just add if b == 0: return None"}}]
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        with pytest.raises(PatchProviderError, match="valid JSON"):
            provider.propose_patch(SAMPLE_LOCALIZATION)


def test_ai_provider_handles_oversized_diff():
    """Verify provider rejects diffs exceeding maximum output size."""
    config = AIPatchProviderConfig(api_key="mock-test-key")
    provider = AIPatchProvider(config=config)

    huge_diff = "--- a/app/calculator.py\n+++ b/app/calculator.py\n@@ -1,1 +1,1 @@\n+" + ("x" * 300_000)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({"unified_diff": huge_diff, "rationale": "big"})
            }
        }]
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        with pytest.raises(PatchProviderError, match="oversized patch"):
            provider.propose_patch(SAMPLE_LOCALIZATION)


def test_ai_provider_handles_null_bytes():
    """Verify provider rejects model output containing null bytes."""
    config = AIPatchProviderConfig(api_key="mock-test-key")
    provider = AIPatchProvider(config=config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({"unified_diff": "--- a/app/calc.py\n\x00", "rationale": "bad"})
            }
        }]
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        with pytest.raises(PatchProviderError, match="illegal null bytes"):
            provider.propose_patch(SAMPLE_LOCALIZATION)


# ---------------------------------------------------------------------------
# 6. Untrusted Output Validation via PatchValidator
# ---------------------------------------------------------------------------

def test_ai_provider_rejects_path_traversal_diff():
    """Verify model output with directory traversal is rejected by PatchValidator."""
    config = AIPatchProviderConfig(api_key="mock-test-key")
    provider = AIPatchProvider(config=config)

    traversal_diff = (
        "--- a/../../etc/passwd\n"
        "+++ b/../../etc/passwd\n"
        "@@ -1,1 +1,1 @@\n"
        "+evil:x:0:0\n"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({"unified_diff": traversal_diff, "rationale": "hack"})
            }
        }]
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        with pytest.raises(PatchProviderError, match="unsafe or invalid patch"):
            provider.propose_patch(SAMPLE_LOCALIZATION)


def test_ai_provider_rejects_blocked_file_diff():
    """Verify model output attempting to edit blocked files (.env) is rejected."""
    config = AIPatchProviderConfig(api_key="mock-test-key")
    provider = AIPatchProvider(config=config)

    env_diff = (
        "--- a/.env\n"
        "+++ b/.env\n"
        "@@ -1,1 +1,1 @@\n"
        "+SECRET=injected\n"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({"unified_diff": env_diff, "rationale": "env edit"})
            }
        }]
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        with pytest.raises(PatchProviderError, match="unsafe or invalid patch"):
            provider.propose_patch(SAMPLE_LOCALIZATION)


# ---------------------------------------------------------------------------
# 7. Secret Leakage Prevention
# ---------------------------------------------------------------------------

def test_ai_provider_redacts_api_key_in_error_messages():
    """Verify the API key is never leaked in exception messages or HTTP errors."""
    secret_key = "super-secret-key-999888"
    config = AIPatchProviderConfig(api_key=secret_key)
    provider = AIPatchProvider(config=config)

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.side_effect = httpx.RequestError(
            f"Failed to authenticate with key {secret_key} at endpoint"
        )
        mock_client_cls.return_value = mock_client_instance

        with pytest.raises(PatchProviderError) as exc_info:
            provider.propose_patch(SAMPLE_LOCALIZATION)

        err_msg = str(exc_info.value)
        assert secret_key not in err_msg
        assert "[REDACTED_API_KEY]" in err_msg


# ---------------------------------------------------------------------------
# 8. Factory Selection & API Integration
# ---------------------------------------------------------------------------

def test_get_patch_provider_factory():
    """Verify factory returns appropriate provider instances."""
    mock_prov = get_patch_provider("mock")
    assert isinstance(mock_prov, MockPatchProvider)

    none_prov = get_patch_provider(None)
    assert isinstance(none_prov, MockPatchProvider)

    ai_prov = get_patch_provider("ai")
    assert isinstance(ai_prov, AIPatchProvider)

    real_prov = get_patch_provider("real")
    assert isinstance(real_prov, AIPatchProvider)


def test_api_propose_patch_default_mock():
    """Verify POST /patch/propose defaults to mock provider and succeeds."""
    payload = {
        "localization": SAMPLE_LOCALIZATION.model_dump(),
        "context": {"issue_title": "Divide by zero"},
    }
    resp = client.post("/patch/propose", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["proposal"]["provider_name"] == "mock-deterministic-provider"
    assert data["proposal"]["is_applied"] is False


def test_api_propose_patch_explicit_mock():
    """Verify POST /patch/propose with provider='mock' succeeds."""
    payload = {
        "localization": SAMPLE_LOCALIZATION.model_dump(),
        "context": {"issue_title": "Divide by zero"},
        "provider": "mock",
    }
    resp = client.post("/patch/propose", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["proposal"]["provider_name"] == "mock-deterministic-provider"


def test_api_propose_patch_ai_unconfigured(monkeypatch):
    """Verify POST /patch/propose with provider='ai' returns 422 when unconfigured."""
    monkeypatch.delenv("AI_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    payload = {
        "localization": SAMPLE_LOCALIZATION.model_dump(),
        "provider": "ai",
    }
    resp = client.post("/patch/propose", json=payload)
    assert resp.status_code == 422
    assert "AI patch provider is not configured" in resp.json()["detail"]


def test_api_propose_patch_ai_mocked_success(monkeypatch):
    """Verify POST /patch/propose with provider='ai' succeeds with configured mock HTTP client."""
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "test-key-123")

    model_response_content = json.dumps({
        "unified_diff": VALID_AI_DIFF,
        "rationale": "Add guard clause.",
        "proposed_regression_tests": ["pytest tests/test_calc.py"],
    })

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": model_response_content}}]
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__.return_value = mock_client_instance
        mock_client_instance.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        payload = {
            "localization": SAMPLE_LOCALIZATION.model_dump(),
            "provider": "ai",
        }
        resp = client.post("/patch/propose", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "ai-provider" in data["proposal"]["provider_name"]
        assert data["proposal"]["unified_diff"] == VALID_AI_DIFF
        assert data["proposal"]["is_applied"] is False
