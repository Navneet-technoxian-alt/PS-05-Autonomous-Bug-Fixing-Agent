from abc import ABC, abstractmethod
import uuid
from typing import Any, Dict, List, Optional

from app.schemas import LocalizationResult, PatchProposal


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
        """Generate a patch proposal for the localized bug.
        
        Args:
            localization: Validated localization result containing candidate files and error details.
            context: Optional contextual parameters (e.g., repository metadata, issue summary).
            
        Returns:
            PatchProposal containing unified diff, affected files, rationale, and regression tests.
        """
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
