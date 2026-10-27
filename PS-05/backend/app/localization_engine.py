import os
import re
from typing import Dict, List, Optional, Set, Tuple

from app.schemas import (
    CandidateLocation,
    LocalizationConfidence,
    LocalizationResult,
)

# Regular expressions for stack traces and error detection
# 1. Python standard traceback line: File "path/to/file.py", line 42, in func_name
PYTHON_TRACEBACK_RE = re.compile(
    r'File\s+["\'](?P<path>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\w+))?',
    re.IGNORECASE,
)

# 2. Generic compiler / linter / runner line format: path/to/file.py:42: or path/to/file.py:42:10:
GENERIC_LOCATION_RE = re.compile(
    r'(?:^|[\s"\'\(])(?P<path>[a-zA-Z0-9_\-/\\]+\.(?:py|js|ts|jsx|tsx|go|rs|java|c|cpp|h)):(?P<line>\d+)(?::(?P<col>\d+))?',
    re.MULTILINE,
)

# 3. Mentioned file in text (linear pattern, avoids nested repetition)
FILE_MENTION_RE = re.compile(
    r'\b(?P<path>[a-zA-Z0-9_\-/\\]+\.(?:py|js|ts|jsx|tsx|go|rs|java|c|cpp|h))\b',
)

# 4. Standard Exception / Error names with word boundary (e.g., ZeroDivisionError, ValueError, KeyError)
EXCEPTION_TYPE_RE = re.compile(
    r'\b(?P<exc>[A-Z][a-zA-Z0-9_]*(?:Error|Exception|Warning|Failure|Fault|Crash))\b',
)

# Substrings indicating third-party or system runtime files that should be deprioritized
THIRD_PARTY_MARKERS = [
    "site-packages",
    "dist-packages",
    "node_modules",
    "<frozen",
    "<string>",
    "/usr/lib",
    "\\lib\\python",
    "/lib/python",
]

MAX_INPUT_CHARS = 50_000
MAX_LINE_CHARS = 1_000
MAX_LINES_ANALYZED = 2_000



def _is_third_party(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return any(marker in normalized for marker in THIRD_PARTY_MARKERS)


def _normalize_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip()
    # Strip leading ./ if present
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


class LocalizationEngine:
    """Deterministic, rule-based bug localization engine.
    
    Extracts suspected defect locations from issue descriptions, stack traces,
    and reproduction outputs without executing code or calling external services.
    All outputs are explicitly labeled as hypotheses.
    """

    def locate_bug(
        self,
        issue_title: str,
        issue_body: Optional[str] = None,
        stack_trace: Optional[str] = None,
        reproduction_stdout: Optional[str] = None,
        reproduction_stderr: Optional[str] = None,
    ) -> LocalizationResult:
        """Deterministically localize suspected defect locations and errors."""
        # Sanitize and bound inputs
        title_safe = (issue_title or "")[:MAX_INPUT_CHARS]
        body_safe = (issue_body or "")[:MAX_INPUT_CHARS]
        trace_safe = (stack_trace or "")[:MAX_INPUT_CHARS]
        stdout_safe = (reproduction_stdout or "")[:MAX_INPUT_CHARS]
        stderr_safe = (reproduction_stderr or "")[:MAX_INPUT_CHARS]

        total_lines_analyzed = (
            title_safe.count("\n")
            + body_safe.count("\n")
            + trace_safe.count("\n")
            + stdout_safe.count("\n")
            + stderr_safe.count("\n")
            + 5
        )

        detected_exceptions: List[str] = []
        raw_candidates: List[CandidateLocation] = []

        def _get_safe_lines(txt: str) -> List[str]:
            return [l[:MAX_LINE_CHARS] for l in txt.splitlines()[:MAX_LINES_ANALYZED]]

        # 1. Extract Exception Types from all text sources
        combined_text = f"{trace_safe}\n{stderr_safe}\n{stdout_safe}\n{body_safe}\n{title_safe}"
        seen_exc: Set[str] = set()
        for line in _get_safe_lines(combined_text):
            for match in EXCEPTION_TYPE_RE.finditer(line):
                exc = match.group("exc")
                if exc and exc not in seen_exc and len(exc) > 3:
                    if exc not in ("TypeError", "ValueError", "KeyError") and not exc.endswith(("Error", "Exception", "Warning", "Failure", "Fault", "Crash")):
                        continue
                    seen_exc.add(exc)
                    detected_exceptions.append(exc)

        # 2. Extract from Stack Trace (Highest specificity)
        if trace_safe:
            trace_candidates = self._parse_traceback(trace_safe, source_type="stack_trace", base_score=0.95)
            raw_candidates.extend(trace_candidates)

        # 3. Extract from Reproduction Stderr
        if stderr_safe:
            stderr_candidates = self._parse_traceback(stderr_safe, source_type="reproduction_stderr", base_score=0.85)
            raw_candidates.extend(stderr_candidates)

        # 4. Extract generic location patterns from reproduction stdout/stderr
        for line in _get_safe_lines(stderr_safe + "\n" + stdout_safe):
            for match in GENERIC_LOCATION_RE.finditer(line):
                path = _normalize_path(match.group("path"))
                line_no = int(match.group("line"))
                raw_candidates.append(
                    CandidateLocation(
                        file_path=path,
                        line_number=line_no,
                        function_name=None,
                        evidence_snippet=line.strip()[:200],
                        source_type="reproduction_output",
                        relevance_score=0.70 if not _is_third_party(path) else 0.20,
                        is_hypothesis=True,
                    )
                )

        # 5. Extract file mentions from Issue Body
        if body_safe:
            for line in _get_safe_lines(body_safe):
                for match in FILE_MENTION_RE.finditer(line):
                    path = _normalize_path(match.group("path"))
                    raw_candidates.append(
                        CandidateLocation(
                            file_path=path,
                            line_number=None,
                            function_name=None,
                            evidence_snippet=line.strip()[:200],
                            source_type="issue_body",
                            relevance_score=0.45 if not _is_third_party(path) else 0.15,
                            is_hypothesis=True,
                        )
                    )

        # 6. Extract file mentions from Issue Title
        if title_safe:
            for line in _get_safe_lines(title_safe):
                for match in FILE_MENTION_RE.finditer(line):
                    path = _normalize_path(match.group("path"))
                    raw_candidates.append(
                        CandidateLocation(
                            file_path=path,
                            line_number=None,
                            function_name=None,
                            evidence_snippet=line.strip()[:200],
                            source_type="issue_title",
                            relevance_score=0.40,
                            is_hypothesis=True,
                        )
                    )


        # 7. Deduplicate and rank candidates deterministically
        ranked_candidates = self._rank_and_deduplicate(raw_candidates)

        # 8. Compute confidence and explanation
        confidence, explanation = self._derive_confidence(ranked_candidates, detected_exceptions, trace_safe, stderr_safe)

        return LocalizationResult(
            candidate_locations=ranked_candidates,
            detected_exceptions=detected_exceptions,
            confidence=confidence,
            confidence_explanation=explanation,
            total_evidence_lines_analyzed=total_lines_analyzed,
            is_root_cause_proven=False,
        )

    def _parse_traceback(self, text: str, source_type: str, base_score: float) -> List[CandidateLocation]:
        """Extract stack frames from Python traceback formatted strings."""
        candidates: List[CandidateLocation] = []
        lines = text.splitlines()[:MAX_LINES_ANALYZED]
        
        matches = []
        for line in lines:
            m = PYTHON_TRACEBACK_RE.search(line)
            if m:
                matches.append((m, line))

        # In Python tracebacks, the bottom-most frame is the site of failure
        num_matches = len(matches)
        for idx, (match, line) in enumerate(matches):
            raw_path = match.group("path")
            line_no = int(match.group("line"))
            func_name = match.group("func")
            norm_path = _normalize_path(raw_path)
            is_tp = _is_third_party(norm_path)

            # Deepest project frame gets highest priority
            is_deepest = (idx == num_matches - 1)
            if is_tp:
                score = 0.20
            else:
                score = base_score if is_deepest else max(0.50, base_score - (num_matches - 1 - idx) * 0.05)

            candidates.append(
                CandidateLocation(
                    file_path=norm_path,
                    line_number=line_no,
                    function_name=func_name,
                    evidence_snippet=line.strip()[:200],
                    source_type=source_type,
                    relevance_score=round(score, 2),
                    is_hypothesis=True,
                )
            )
        return candidates

    def _rank_and_deduplicate(self, candidates: List[CandidateLocation]) -> List[CandidateLocation]:
        """Deduplicate candidates by (file_path, line_number), retaining highest score."""
        merged: Dict[Tuple[str, Optional[int]], CandidateLocation] = {}

        for cand in candidates:
            key = (cand.file_path, cand.line_number)
            if key not in merged:
                merged[key] = cand
            else:
                existing = merged[key]
                if cand.relevance_score > existing.relevance_score:
                    merged[key] = cand

        # Deterministic sorting: relevance_score descending, then file_path ascending, then line ascending
        sorted_list = sorted(
            merged.values(),
            key=lambda c: (-c.relevance_score, c.file_path, c.line_number or 0),
        )
        return sorted_list

    def _derive_confidence(
        self,
        candidates: List[CandidateLocation],
        detected_exceptions: List[str],
        trace: str,
        stderr: str,
    ) -> Tuple[LocalizationConfidence, str]:
        """Transparent derivation of localization confidence."""
        project_candidates = [c for c in candidates if not _is_third_party(c.file_path)]

        has_stack_trace = bool(trace or "Traceback" in stderr)
        has_file_with_line = any(c.line_number is not None for c in project_candidates)
        has_exceptions = len(detected_exceptions) > 0

        if project_candidates and has_file_with_line and has_stack_trace and has_exceptions:
            return (
                LocalizationConfidence.HIGH,
                f"High confidence: verified stack trace frame at line {project_candidates[0].line_number} in '{project_candidates[0].file_path}' matching exception '{detected_exceptions[0]}'.",
            )

        if project_candidates and (has_file_with_line or (has_exceptions and len(project_candidates) > 0)):
            return (
                LocalizationConfidence.MEDIUM,
                f"Medium confidence: identified project file '{project_candidates[0].file_path}' and relevant indicators, but missing complete innermost stack trace verification.",
            )

        if project_candidates:
            return (
                LocalizationConfidence.LOW,
                f"Low confidence: inferred file reference '{project_candidates[0].file_path}' from issue description without runtime stack trace evidence.",
            )

        if detected_exceptions:
            return (
                LocalizationConfidence.LOW,
                f"Low confidence: detected exception '{detected_exceptions[0]}' without identifiable repository file locations.",
            )

        return (
            LocalizationConfidence.NONE,
            "No confidence: insufficient evidence in issue text, reproduction output, or stack traces.",
        )
