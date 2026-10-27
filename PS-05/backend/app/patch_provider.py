"""
patch_provider.py — Patch Proposal Generation Service (Phase 4 & Phase 6A)

Provides code patch proposals based on localization evidence and repository context.

SAFETY GUARANTEES:
  1. No Code Execution:
     A patch provider ONLY generates proposed unified diff strings. It NEVER
     executes code, applies patches to disk, or runs tests.
  2. Input Sanitization & Secret Defense:
     Input context sent to external providers is strictly bounded and scrubbed of
     sensitive filenames (.env, id_rsa, credentials). Raw workspaces and host
     directories are never transmitted.
  3. Strict Model Output Validation:
     Model output is treated as untrusted data. Every proposed unified diff is
     validated through PatchValidator before being returned. Malformed, oversized,
     binary, or path-escaping diffs are rejected immediately.
  4. Credential Hygiene:
     API keys are read exclusively from environment variables (AI_PROVIDER_API_KEY,
     OPENAI_API_KEY). Credentials are never hardcoded, printed to logs, or exposed
     in exception messages.
  5. Deterministic Offline Fallback:
     MockPatchProvider is always available for offline development and testing.
     AIPatchProvider is disabled unless explicitly configured with valid credentials.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.patch_validator import PatchValidator, PatchValidatorConfig, validate_patch
from app.schemas import LocalizationResult, PatchProposal

logger = logging.getLogger(__name__)

# Constants
MAX_PROMPT_INPUT_CHARS = 4_000
MAX_DIFF_OUTPUT_CHARS = 262_144  # 256 KB
DEFAULT_TIMEOUT_SECONDS = 30.0

# Sensitive path patterns that must never be included in prompts
SENSITIVE_PATTERNS = re.compile(
    r"(\.env|credentials|secret|id_rsa|id_ed25519|passwd|shadow|\.aws|\.ssh)",
    re.IGNORECASE,
)


class PatchProviderError(Exception):
    """Raised when patch proposal generation encounters invalid input or provider errors."""
    pass


class BasePatchProvider(ABC):
    """Abstract interface for proposing code patches based on bug localization results.
    
    CRITICAL SAFETY RULES:
    1. A provider ONLY proposes code diffs; it NEVER applies them to any working repository.
    2. A provider NEVER executes proposed code or executes Git commit/push actions.
    3. No credentials, tokens, or API keys may be hard-coded.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider implementation."""
        pass

    @abstractmethod
    def propose_patch(
        self,
        localization: LocalizationResult,
        context: Optional[Dict[str, Any]] = None,
    ) -> PatchProposal:
        """Generate a patch proposal for the localized bug."""
        pass


class MockPatchProvider(BasePatchProvider):
    """Deterministic mock patch provider for offline testing and verification.
    
    Generates predictable, syntactically valid unified diffs without network calls or LLM dependencies.
    """

    def __init__(
        self,
        custom_diff: Optional[str] = None,
        custom_rationale: Optional[str] = None,
        custom_tests: Optional[List[str]] = None,
    ):
        self._custom_diff = custom_diff
        self._custom_rationale = custom_rationale
        self._custom_tests = custom_tests

    @property
    def provider_name(self) -> str:
        return "mock-deterministic-provider"

    def propose_patch(
        self,
        localization: LocalizationResult,
        context: Optional[Dict[str, Any]] = None,
    ) -> PatchProposal:
        """Generate a mock patch proposal based on localization findings."""
        if localization is None:
            raise PatchProviderError("Localization result must not be None.")

        if not isinstance(localization, LocalizationResult):
            raise PatchProviderError(
                f"Expected localization of type LocalizationResult, got '{type(localization).__name__}'."
            )

        proposal_id = f"patch-{uuid.uuid4().hex[:8]}"

        # If custom diff was pre-configured (for testing specific scenarios)
        if self._custom_diff is not None:
            return PatchProposal(
                proposal_id=proposal_id,
                provider_name=self.provider_name,
                affected_files=context.get("affected_files", ["app/calculator.py"]) if context else ["app/calculator.py"],
                unified_diff=self._custom_diff,
                rationale=self._custom_rationale or "Custom test patch applied from mock scenario.",
                proposed_regression_tests=self._custom_tests or ["pytest tests/test_patch.py"],
                is_applied=False,
            )

        # Handle empty candidate locations
        if not localization.candidate_locations:
            return PatchProposal(
                proposal_id=proposal_id,
                provider_name=self.provider_name,
                affected_files=[],
                unified_diff="",
                rationale="No candidate locations identified during bug localization; no patch generated.",
                proposed_regression_tests=[],
                is_applied=False,
            )

        # Primary candidate file
        top_candidate = localization.candidate_locations[0]
        target_file = top_candidate.file_path
        target_line = top_candidate.line_number or 1

        exception_type = localization.detected_exceptions[0] if localization.detected_exceptions else "Exception"

        # Generate a standard, clean unified diff template for mock testing
        unified_diff = (
            f"--- a/{target_file}\n"
            f"+++ b/{target_file}\n"
            f"@@ -{target_line},3 +{target_line},5 @@\n"
            f"+    # Guard against {exception_type}\n"
            f"+    if divisor == 0:\n"
            f"+        raise ValueError('Divisor cannot be zero')\n"
            f"     return numerator / divisor\n"
        )

        rationale = (
            f"Added defensive validation in '{target_file}' near line {target_line} to prevent unhandled '{exception_type}'."
        )

        regression_tests = [
            f"pytest tests/test_{target_file.split('/')[-1].replace('.py', '')}.py -k 'test_{exception_type.lower()}'"
        ]

        return PatchProposal(
            proposal_id=proposal_id,
            provider_name=self.provider_name,
            affected_files=[target_file],
            unified_diff=unified_diff,
            rationale=rationale,
            proposed_regression_tests=regression_tests,
            is_applied=False,
        )


@dataclass
class AIPatchProviderConfig:
    """Configuration options for AI-backed patch generation."""
    api_key: Optional[str] = None
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_tokens: int = 2048

    @classmethod
    def from_env(cls) -> "AIPatchProviderConfig":
        """Load configuration from environment variables."""
        api_key = os.environ.get("AI_PROVIDER_API_KEY") or os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("AI_PROVIDER_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("AI_PROVIDER_MODEL", "gpt-4o-mini")
        timeout_raw = os.environ.get("AI_PROVIDER_TIMEOUT")
        timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS

        return cls(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout_seconds=timeout,
        )


def sanitize_prompt_context(text: str, max_chars: int = MAX_PROMPT_INPUT_CHARS) -> str:
    """Scrub potential secrets and bound text length."""
    if not text:
        return ""
    # Redact obvious token/key patterns
    scrubbed = re.sub(
        r"(ghp_[a-zA-Z0-9]{20,}|sk-[a-zA-Z0-9_\-]{20,}|Bearer\s+[a-zA-Z0-9_\-\.]+)",
        "[REDACTED_SECRET]",
        text,
    )
    if len(scrubbed) > max_chars:
        return scrubbed[:max_chars] + "... [TRUNCATED]"
    return scrubbed


def build_sanitized_patch_prompt(
    localization: LocalizationResult,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Construct minimal, safe prompts without sending full workspaces or credentials."""
    system_prompt = (
        "You are an automated software patch generation assistant. "
        "Analyze the bug localization evidence and generate a minimal, syntactically correct unified diff "
        "that addresses the issue.\n\n"
        "STRICT REQUIREMENTS:\n"
        "1. Output must be a single, valid JSON object with exactly these keys:\n"
        "   - 'unified_diff': A valid unified diff string starting with '--- a/' and '+++ b/'.\n"
        "   - 'rationale': A brief explanation of the fix.\n"
        "   - 'proposed_regression_tests': An array of test command strings.\n"
        "2. Do NOT output any markdown formatting or commentary outside the JSON object.\n"
        "3. Only modify the localized target file. Do not touch unrelated files or configuration files."
    )

    candidate_summary = []
    for idx, c in enumerate(localization.candidate_locations[:3]):
        file_path = c.file_path
        # Skip sensitive files
        if SENSITIVE_PATTERNS.search(file_path):
            continue
        snippet = sanitize_prompt_context(c.evidence_snippet or "", max_chars=500)
        candidate_summary.append(
            f"Candidate #{idx + 1}: File: {file_path}, Line: {c.line_number or 'unknown'}, "
            f"Function: {c.function_name or 'unknown'}, Evidence: {snippet}"
        )

    exceptions = ", ".join(localization.detected_exceptions) if localization.detected_exceptions else "None detected"

    issue_info = ""
    if context:
        title = sanitize_prompt_context(context.get("issue_title", ""), max_chars=300)
        repro_err = sanitize_prompt_context(context.get("reproduction_stderr", ""), max_chars=1000)
        if title:
            issue_info += f"\nIssue Title: {title}"
        if repro_err:
            issue_info += f"\nObserved Failure Output:\n{repro_err}"

    user_prompt = (
        f"Localized Bug Evidence:\n"
        f"Detected Exceptions: {exceptions}\n"
        f"Candidate Locations:\n" + "\n".join(candidate_summary) + "\n"
        f"{issue_info}\n\n"
        "Generate the minimal corrective unified diff as JSON."
    )

    return system_prompt, user_prompt


class AIPatchProvider(BasePatchProvider):
    """Real AI-backed patch provider communicating with external LLM APIs over HTTP.

    Treats all model output as untrusted and validates generated diffs through
    PatchValidator before returning them.
    """

    def __init__(self, config: Optional[AIPatchProviderConfig] = None):
        self._config = config or AIPatchProviderConfig.from_env()

    @property
    def provider_name(self) -> str:
        return f"ai-provider-{self._config.model}"

    @property
    def is_configured(self) -> bool:
        """Returns True only when an API key is present."""
        return bool(self._config.api_key and self._config.api_key.strip())

    def propose_patch(
        self,
        localization: LocalizationResult,
        context: Optional[Dict[str, Any]] = None,
    ) -> PatchProposal:
        """Generate a patch proposal via external AI provider."""
        if not self.is_configured:
            raise PatchProviderError(
                "AI patch provider is not configured. Missing required API key environment variable "
                "(AI_PROVIDER_API_KEY or OPENAI_API_KEY)."
            )

        if localization is None:
            raise PatchProviderError("Localization result must not be None.")

        if not localization.candidate_locations:
            return PatchProposal(
                proposal_id=f"patch-{uuid.uuid4().hex[:8]}",
                provider_name=self.provider_name,
                affected_files=[],
                unified_diff="",
                rationale="No candidate locations identified; cannot generate AI patch.",
                proposed_regression_tests=[],
                is_applied=False,
            )

        # 1. Build bounded prompt
        system_prompt, user_prompt = build_sanitized_patch_prompt(localization, context)

        # 2. Call external AI endpoint
        raw_response_text = self._call_model_api(system_prompt, user_prompt)

        # 3. Parse structured JSON from model
        parsed_data = self._parse_model_output(raw_response_text)

        unified_diff = parsed_data.get("unified_diff", "")
        rationale = parsed_data.get("rationale", "AI generated fix.")
        regression_tests = parsed_data.get("proposed_regression_tests", [])

        # 4. Strict untrusted output validation
        if not isinstance(unified_diff, str) or not unified_diff.strip():
            raise PatchProviderError("Model response did not contain a valid unified_diff string.")

        if len(unified_diff.encode("utf-8")) > MAX_DIFF_OUTPUT_CHARS:
            raise PatchProviderError("Model generated an oversized patch exceeding 256 KB.")

        if "\x00" in unified_diff:
            raise PatchProviderError("Model generated a patch containing illegal null bytes.")

        # 5. Validate diff syntax and path safety through PatchValidator
        workspace_path = context.get("workspace_path") if context else None
        self._validate_generated_diff(unified_diff, workspace_path)

        proposal_id = f"patch-{uuid.uuid4().hex[:8]}"
        top_file = localization.candidate_locations[0].file_path

        return PatchProposal(
            proposal_id=proposal_id,
            provider_name=self.provider_name,
            affected_files=[top_file],
            unified_diff=unified_diff,
            rationale=rationale,
            proposed_regression_tests=regression_tests if isinstance(regression_tests, list) else [],
            is_applied=False,
        )

    def _call_model_api(self, system_prompt: str, user_prompt: str) -> str:
        """Execute HTTP request to model provider with strict timeouts."""
        import httpx

        url = f"{self._config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self._config.max_tokens,
            "temperature": 0.1,
        }

        try:
            with httpx.Client(timeout=self._config.timeout_seconds) as http_client:
                resp = http_client.post(url, json=payload, headers=headers)

                if resp.status_code != 200:
                    sanitized_err = self._sanitize_error(resp.text)
                    raise PatchProviderError(
                        f"AI provider returned HTTP {resp.status_code}: {sanitized_err}"
                    )

                data = resp.json()
                return data["choices"][0]["message"]["content"]

        except httpx.TimeoutException:
            raise PatchProviderError(f"AI provider request timed out after {self._config.timeout_seconds} seconds.")
        except httpx.RequestError as req_err:
            sanitized_err = self._sanitize_error(str(req_err))
            raise PatchProviderError(f"Network error communicating with AI provider: {sanitized_err}")
        except KeyError as k_err:
            raise PatchProviderError(f"Unexpected AI provider response format: missing {k_err}")
        except Exception as exc:
            if isinstance(exc, PatchProviderError):
                raise
            sanitized_err = self._sanitize_error(str(exc))
            raise PatchProviderError(f"AI provider call failed: {sanitized_err}")

    def _parse_model_output(self, raw_text: str) -> Dict[str, Any]:
        """Extract and parse JSON from model output, handling markdown code fences."""
        content = raw_text.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
            content = re.sub(r"\s*```$", "", content)

        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise PatchProviderError("Model output JSON is not an object.")
            return parsed
        except json.JSONDecodeError as decode_err:
            raise PatchProviderError(f"Model output could not be parsed as valid JSON: {decode_err}")

    def _validate_generated_diff(self, diff_text: str, workspace_path: Optional[str] = None) -> None:
        """Verify model diff through PatchValidator against containment and syntax rules."""
        if workspace_path and os.path.isdir(workspace_path):
            val_root = Path(workspace_path)
            res = validate_patch(diff_text, workspace_root=val_root)
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                res = validate_patch(diff_text, workspace_root=tmpdir)

        if not res.is_valid:
            error_summary = "; ".join(res.errors)
            raise PatchProviderError(f"Model generated unsafe or invalid patch: {error_summary}")

    def _sanitize_error(self, error_str: str) -> str:
        """Ensure API keys and credentials are never leaked in error messages."""
        if self._config.api_key and self._config.api_key in error_str:
            return error_str.replace(self._config.api_key, "[REDACTED_API_KEY]")
        return error_str


def get_patch_provider(provider_type: Optional[str] = None) -> BasePatchProvider:
    """Factory for selecting between mock and AI patch providers."""
    normalized = (provider_type or "mock").strip().lower()
    if normalized in ("ai", "real", "openai", "gemini"):
        return AIPatchProvider()
    return MockPatchProvider()
