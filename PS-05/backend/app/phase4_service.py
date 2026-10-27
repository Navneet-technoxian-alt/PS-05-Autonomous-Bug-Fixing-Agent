"""
phase4_service.py — Phase 4 API Service Layer

Orchestrates deterministic bug localization, mock patch proposal generation,
and patch safety validation through the existing engine modules.

SAFETY GUARANTEES:
  - No code execution, no repository cloning, no filesystem writes.
  - No LLM calls or external service dependencies.
  - Workspace roots for patch validation are resolved server-side from
    managed sandbox sessions — never accepted from untrusted callers.
  - All operations are deterministic and offline.
"""

import logging
from typing import Optional

from fastapi import HTTPException

from app.localization_engine import LocalizationEngine
from app.patch_provider import (
    BasePatchProvider,
    MockPatchProvider,
    PatchProviderError,
    get_patch_provider,
)
from app.patch_validator import PatchValidator, PatchValidatorConfig
from app.schemas import (
    LocalizationResult,
    LocalizeRequest,
    LocalizeResponse,
    PatchProposeRequest,
    PatchProposeResponse,
    PatchValidateRequest,
    PatchValidateResponse,
)

logger = logging.getLogger(__name__)


class Phase4Service:
    """Coordinates Phase 4 localization, patch proposal, and patch validation endpoints.

    Designed for stateless operation. The only external dependency is a session
    lookup function for resolving workspace roots during patch validation.
    """

    def __init__(
        self,
        localization_engine: Optional[LocalizationEngine] = None,
        patch_provider: Optional[BasePatchProvider] = None,
    ):
        self._engine = localization_engine or LocalizationEngine()
        self._provider = patch_provider or MockPatchProvider()

    def localize(self, request: LocalizeRequest) -> LocalizeResponse:
        """Run deterministic bug localization on provided evidence text.

        Returns ranked candidate locations, detected exceptions, and confidence.
        No code execution or repository access is performed.
        """
        try:
            result = self._engine.locate_bug(
                issue_title=request.issue_title,
                issue_body=request.issue_body,
                stack_trace=request.stack_trace,
                reproduction_stdout=request.reproduction_stdout,
                reproduction_stderr=request.reproduction_stderr,
            )
            return LocalizeResponse(success=True, result=result)
        except Exception as exc:
            logger.error("Localization failed: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Localization analysis failed due to an internal error.",
            )

    def propose_patch(self, request: PatchProposeRequest) -> PatchProposeResponse:
        """Generate a reviewable patch proposal through the configured or requested provider.

        The proposal contains a unified diff, rationale, and suggested regression tests.
        No files are created, modified, committed, or pushed.
        """
        try:
            if request.provider and request.provider.lower() != "mock":
                provider = get_patch_provider(request.provider)
            else:
                provider = self._provider

            proposal = provider.propose_patch(
                localization=request.localization,
                context=request.context,
            )
            return PatchProposeResponse(success=True, proposal=proposal)
        except PatchProviderError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            logger.error("Patch proposal failed: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Patch proposal generation failed due to an internal error.",
            )

    def validate_patch(
        self,
        request: PatchValidateRequest,
        workspace_path: str,
    ) -> PatchValidateResponse:
        """Validate a unified diff against a managed workspace root.

        The workspace_path is resolved server-side from a known sandbox session.
        This method is strictly read-only: no files are written, created, or deleted.
        """
        try:
            validator = PatchValidator(workspace_root=workspace_path)
            result = validator.validate(unified_diff=request.unified_diff)
            return PatchValidateResponse(
                success=True,
                is_valid=result.is_valid,
                errors=result.errors,
                affected_files=result.affected_files,
                total_files_analyzed=result.total_files_analyzed,
                total_hunks_analyzed=result.total_hunks_analyzed,
            )
        except ValueError as exc:
            # Workspace path invalid or does not exist
            raise HTTPException(
                status_code=422,
                detail=f"Workspace validation error: {exc}",
            )
        except Exception as exc:
            logger.error("Patch validation failed: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Patch validation failed due to an internal error.",
            )
