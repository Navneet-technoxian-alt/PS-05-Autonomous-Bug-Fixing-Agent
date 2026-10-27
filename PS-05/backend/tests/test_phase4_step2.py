import os
import pytest

from app.localization_engine import LocalizationEngine
from app.patch_provider import BasePatchProvider, MockPatchProvider, PatchProviderError
from app.schemas import LocalizationConfidence, LocalizationResult, PatchProposal


# --- Test Localization Engine (2A) ---

def test_extract_stack_trace_path_and_line():
    engine = LocalizationEngine()
    sample_trace = """
Traceback (most recent call last):
  File "calculator/main.py", line 12, in run
    result = compute(10, 0)
  File "calculator/engine.py", line 45, in compute
    return a / b
ZeroDivisionError: division by zero
"""
    result = engine.locate_bug(
        issue_title="Crash when divisor is zero",
        issue_body="Calling compute with b=0 triggers an unhandled crash.",
        stack_trace=sample_trace,
    )

    assert result.confidence == LocalizationConfidence.HIGH
    assert "ZeroDivisionError" in result.detected_exceptions
    assert len(result.candidate_locations) >= 2

    # Innermost frame should be ranked top
    top_candidate = result.candidate_locations[0]
    assert top_candidate.file_path == "calculator/engine.py"
    assert top_candidate.line_number == 45
    assert top_candidate.function_name == "compute"
    assert top_candidate.relevance_score >= 0.90
    assert top_candidate.is_hypothesis is True

    # Second frame should be the caller
    second_candidate = result.candidate_locations[1]
    assert second_candidate.file_path == "calculator/main.py"
    assert second_candidate.line_number == 12


def test_extract_exception_types():
    engine = LocalizationEngine()
    result = engine.locate_bug(
        issue_title="Unhandled KeyError and ValueError on missing config",
        issue_body="When config.json is absent, KeyError is raised, then caught and re-raised as ConfigurationError.",
    )

    assert "KeyError" in result.detected_exceptions
    assert "ValueError" in result.detected_exceptions
    assert "ConfigurationError" in result.detected_exceptions


def test_candidate_ranking_and_third_party_penalty():
    engine = LocalizationEngine()
    sample_trace = """
Traceback (most recent call last):
  File "app/service.py", line 30, in handle_request
    resp = requests.get(url)
  File "/usr/local/lib/python3.11/site-packages/requests/api.py", line 73, in get
    return request('get', url, params=params)
ConnectTimeoutError: connection timed out
"""
    result = engine.locate_bug(
        issue_title="Timeout error",
        stack_trace=sample_trace,
    )

    # Project frame app/service.py must outrank the site-packages frame
    assert len(result.candidate_locations) >= 2
    assert result.candidate_locations[0].file_path == "app/service.py"
    assert result.candidate_locations[0].relevance_score > result.candidate_locations[1].relevance_score


def test_confidence_explanation_transparency():
    engine = LocalizationEngine()
    
    # 1. High confidence case
    res_high = engine.locate_bug(
        issue_title="Crash in parser",
        stack_trace='File "parser/lexer.py", line 88, in tokenize\n    raise SyntaxError("bad token")',
    )
    assert res_high.confidence == LocalizationConfidence.HIGH
    assert "parser/lexer.py" in res_high.confidence_explanation
    assert "SyntaxError" in res_high.confidence_explanation

    # 2. Low confidence case (only file mention in issue title)
    res_low = engine.locate_bug(
        issue_title="Bug in utils/helpers.py",
        issue_body="Something goes wrong when calling helper functions.",
    )
    assert res_low.confidence == LocalizationConfidence.LOW
    assert "inferred file reference" in res_low.confidence_explanation.lower()

    # 3. None confidence case (no details)
    res_none = engine.locate_bug(
        issue_title="It is completely broken",
        issue_body="Please fix ASAP.",
    )
    assert res_none.confidence == LocalizationConfidence.NONE
    assert "insufficient evidence" in res_none.confidence_explanation.lower()


def test_missing_and_malformed_evidence():
    engine = LocalizationEngine()

    # None values handled safely
    res_null = engine.locate_bug(
        issue_title="",
        issue_body=None,
        stack_trace=None,
        reproduction_stdout=None,
        reproduction_stderr=None,
    )
    assert res_null.confidence == LocalizationConfidence.NONE
    assert res_null.candidate_locations == []
    assert res_null.detected_exceptions == []

    # Extremely large input handled safely without hanging or throwing
    large_garbage = "A" * 200_000
    res_large = engine.locate_bug(
        issue_title=large_garbage,
        issue_body=large_garbage,
    )
    assert res_large.total_evidence_lines_analyzed > 0
    assert res_large.is_root_cause_proven is False


# --- Test Patch Provider Abstraction (2B) ---

def test_mock_patch_provider_generates_valid_proposal():
    engine = LocalizationEngine()
    localization = engine.locate_bug(
        issue_title="ZeroDivisionError in core/calc.py",
        stack_trace='File "core/calc.py", line 15, in divide\n    return x / y\nZeroDivisionError: division by zero',
    )

    provider = MockPatchProvider()
    assert issubclass(MockPatchProvider, BasePatchProvider)
    assert provider.provider_name == "mock-deterministic-provider"

    proposal = provider.propose_patch(localization)

    assert isinstance(proposal, PatchProposal)
    assert proposal.is_applied is False  # CRITICAL: patch must never be applied
    assert proposal.affected_files == ["core/calc.py"]
    assert "--- a/core/calc.py" in proposal.unified_diff
    assert "+++ b/core/calc.py" in proposal.unified_diff
    assert "ZeroDivisionError" in proposal.rationale
    assert len(proposal.proposed_regression_tests) == 1
    assert "pytest" in proposal.proposed_regression_tests[0]


def test_mock_patch_provider_handles_empty_candidates():
    provider = MockPatchProvider()
    empty_loc = LocalizationResult(
        candidate_locations=[],
        detected_exceptions=[],
        confidence=LocalizationConfidence.NONE,
        confidence_explanation="No evidence",
        total_evidence_lines_analyzed=1,
        is_root_cause_proven=False,
    )
    proposal = provider.propose_patch(empty_loc)
    assert proposal.affected_files == []
    assert proposal.unified_diff == ""
    assert "No candidate locations" in proposal.rationale
    assert proposal.is_applied is False


def test_mock_patch_provider_rejects_invalid_inputs():
    provider = MockPatchProvider()

    with pytest.raises(PatchProviderError) as exc1:
        provider.propose_patch(None)  # type: ignore
    assert "must not be None" in str(exc1.value)

    with pytest.raises(PatchProviderError) as exc2:
        provider.propose_patch("invalid_string_argument")  # type: ignore
    assert "Expected localization of type LocalizationResult" in str(exc2.value)


def test_patch_provider_does_not_modify_filesystem(tmp_path):
    # Verify that proposing a patch leaves all files untouched
    dummy_file = tmp_path / "test_target.py"
    original_content = "def test(): pass\n"
    dummy_file.write_text(original_content, encoding="utf-8")

    engine = LocalizationEngine()
    localization = engine.locate_bug(
        issue_title="Bug",
        stack_trace=f'File "{dummy_file}", line 1, in test\n    raise RuntimeError()',
    )

    provider = MockPatchProvider()
    proposal = provider.propose_patch(localization)

    assert proposal.is_applied is False
    # Content of file must remain identical
    assert dummy_file.read_text(encoding="utf-8") == original_content
