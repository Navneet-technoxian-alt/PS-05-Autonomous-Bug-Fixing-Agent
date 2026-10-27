"""
patch_validator.py — Patch Safety Validation Engine (Phase 4 Step 2C)

Inspects proposed unified diffs prior to any sandbox application or human review.
Purely static, in-memory, and strictly read-only:
  - NEVER applies patches.
  - NEVER writes or creates files in the target workspace.
  - NEVER executes code or runs tests.

Validation Rules Enforced:
1. Limits: Reject empty diffs, diffs exceeding size limits (default 256 KB), or exceeding file limits (default 10 files).
2. Header Integrity: Strictly parse unified diff file and hunk headers. Reject malformed or truncated headers.
3. Path Safety: Reject absolute paths (Unix / Windows drive), UNC shares, traversal (..), and colons.
4. Workspace Containment: Ensure all paths resolve strictly within the designated workspace_root.
5. Symlink Traversal: Reject symlink targets and parent directories that escape workspace_root.
6. Binary & Complex Patches: Reject git binary diffs, null bytes, and unsupported rename/copy operations.
7. Allowlist / Blocklist: Permit legitimate source/config/test files; reject blocked extensions (executables, scripts, keys) and blocked files (.env, credentials, workflow configs).
8. Deduplication: Reject multiple/conflicting diff entries for the same target file.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import List, Optional, Set, Union


# ---------------------------------------------------------------------------
# Default Configuration Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_DIFF_SIZE_BYTES: int = 256 * 1024  # 256 KB
DEFAULT_MAX_FILES: int = 10
DEFAULT_MAX_HUNKS_PER_FILE: int = 50

# Permitted source, config, documentation, and test file extensions
DEFAULT_ALLOWED_EXTENSIONS: Set[str] = {
    # Python
    ".py", ".pyi",
    # JavaScript / TypeScript / Web
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".html", ".css", ".scss",
    # Systems & compiled languages
    ".go", ".rs", ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".cs",
    # Scripting / mobile / other
    ".rb", ".php", ".swift", ".kt", ".kts", ".scala", ".r",
    # Config / data / documentation
    ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".cfg",
    ".md", ".rst", ".txt", ".sql",
}

# Strictly blocked file extensions (executables, shell scripts, keys, bytecode)
DEFAULT_BLOCKED_EXTENSIONS: Set[str] = {
    # Binaries & executables
    ".exe", ".dll", ".so", ".dylib", ".bin", ".com", ".msi",
    ".bat", ".cmd", ".ps1", ".sh", ".bash", ".zsh",
    ".jar", ".apk", ".dmg", ".iso", ".img",
    # Bytecode & caches
    ".pyc", ".pyo", ".pyd", ".class",
    # Secrets & credentials
    ".pem", ".key", ".crt", ".der", ".p12", ".pfx",
    ".id_rsa", ".id_dsa", ".id_ecdsa", ".id_ed25519",
}

# Blocked specific filenames (credentials, secrets, workflow definitions)
DEFAULT_BLOCKED_FILENAMES: Set[str] = {
    ".env", "credentials", "secrets.json", "id_rsa", "id_ed25519",
    "authorized_keys", "known_hosts", "shadow", "passwd",
}

# Blocked repository directory trees
DEFAULT_BLOCKED_DIRECTORIES: Set[str] = {
    ".git", ".github", ".vscode", ".idea", "node_modules", ".venv", "venv", "__pycache__"
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class PatchValidatorConfig:
    """Configurable boundaries and policies for patch safety validation."""
    max_diff_size_bytes: int = DEFAULT_MAX_DIFF_SIZE_BYTES
    max_files: int = DEFAULT_MAX_FILES
    max_hunks_per_file: int = DEFAULT_MAX_HUNKS_PER_FILE
    allowed_extensions: Optional[Set[str]] = field(default_factory=lambda: set(DEFAULT_ALLOWED_EXTENSIONS))
    blocked_extensions: Set[str] = field(default_factory=lambda: set(DEFAULT_BLOCKED_EXTENSIONS))
    blocked_filenames: Set[str] = field(default_factory=lambda: set(DEFAULT_BLOCKED_FILENAMES))
    blocked_directories: Set[str] = field(default_factory=lambda: set(DEFAULT_BLOCKED_DIRECTORIES))


@dataclass
class PatchValidationResult:
    """Structured, immutable outcome of patch validation."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    affected_files: List[str] = field(default_factory=list)
    total_files_analyzed: int = 0
    total_hunks_analyzed: int = 0
    is_security_violation: bool = False


SECURITY_VIOLATION_PATTERNS = (
    "traversal",
    "absolute path",
    "unc share",
    "drive path or colon",
    "null byte",
    "symlink",
    "outside workspace",
    "sensitive file",
    "protected repository directory",
    "forbidden in path",
    "is forbidden",
    "is blocked",
    "blocked for file",
    "blocked extension",
    "not in the allowed extensions",
)


def is_patch_security_violation(errors: Union[List[str], str]) -> bool:
    """Check whether any validation or application error represents a security violation."""
    if isinstance(errors, str):
        errors = [errors]
    combined = " ".join(errors).lower()
    return any(p in combined for p in SECURITY_VIOLATION_PATTERNS)


# ---------------------------------------------------------------------------
# Patch Validator Implementation
# ---------------------------------------------------------------------------

class PatchValidator:
    """Strict, read-only unified diff validator."""

    def __init__(
        self,
        workspace_root: Union[str, Path],
        config: Optional[PatchValidatorConfig] = None,
    ):
        if workspace_root is None:
            raise ValueError("workspace_root must not be None.")

        self._workspace_root = Path(workspace_root).resolve()
        if not self._workspace_root.exists() or not self._workspace_root.is_dir():
            raise ValueError(f"workspace_root must be an existing directory: {self._workspace_root}")

        self._config = config or PatchValidatorConfig()

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    @property
    def config(self) -> PatchValidatorConfig:
        return self._config

    def validate(self, unified_diff: Union[str, bytes]) -> PatchValidationResult:
        """Validate a unified diff string or bytes against safety policies.

        Guaranteed to be strictly read-only. Does not modify any file or execute code.
        """
        errors: List[str] = []

        # 1. Type validation and decoding
        if unified_diff is None:
            return PatchValidationResult(is_valid=False, errors=["Diff content must not be None."])

        if isinstance(unified_diff, bytes):
            if b"\x00" in unified_diff:
                return PatchValidationResult(
                    is_valid=False,
                    errors=["Binary patches containing null bytes are rejected."],
                    is_security_violation=True,
                )
            try:
                diff_text = unified_diff.decode("utf-8")
            except UnicodeDecodeError as exc:
                return PatchValidationResult(is_valid=False, errors=[f"Diff is not valid UTF-8: {exc}"])
        elif isinstance(unified_diff, str):
            if "\x00" in unified_diff:
                return PatchValidationResult(
                    is_valid=False,
                    errors=["Binary patches containing null bytes are rejected."],
                    is_security_violation=True,
                )
            diff_text = unified_diff
        else:
            return PatchValidationResult(
                is_valid=False,
                errors=[f"Unsupported diff input type: expected str or bytes, got '{type(unified_diff).__name__}'."]
            )

        # 2. Empty / Whitespace checks
        if not diff_text.strip():
            return PatchValidationResult(is_valid=False, errors=["Diff is empty or whitespace only."])

        # 3. Overall size check
        size_bytes = len(diff_text.encode("utf-8"))
        if size_bytes > self._config.max_diff_size_bytes:
            return PatchValidationResult(
                is_valid=False,
                errors=[f"Diff size ({size_bytes} bytes) exceeds maximum permitted limit ({self._config.max_diff_size_bytes} bytes)."]
            )

        # 4. Binary patch markers
        if re.search(r"^GIT binary patch", diff_text, re.MULTILINE):
            return PatchValidationResult(is_valid=False, errors=["Binary patches are not supported (GIT binary patch marker detected)."])
        if re.search(r"^Binary files .* differ$", diff_text, re.MULTILINE):
            return PatchValidationResult(is_valid=False, errors=["Binary patches are not supported (Binary files differ marker detected)."])

        # 5. Unsupported rename / copy operations
        if re.search(r"^(rename from|rename to|copy from|copy to|similarity index)", diff_text, re.MULTILINE):
            return PatchValidationResult(
                is_valid=False,
                errors=["Unsupported operation: file rename, copy, or similarity metadata operations are not permitted."]
            )

        # 6. Parse file sections and headers strictly
        lines = diff_text.splitlines()
        file_sections = self._parse_file_sections(lines, errors)
        if errors:
            return PatchValidationResult(is_valid=False, errors=errors)

        if not file_sections:
            return PatchValidationResult(is_valid=False, errors=["No valid unified diff file headers ('---' / '+++') found."])

        # 7. File count check
        if len(file_sections) > self._config.max_files:
            return PatchValidationResult(
                is_valid=False,
                errors=[f"Number of affected files ({len(file_sections)}) exceeds limit ({self._config.max_files})."]
            )

        # 8. Per-file validation
        affected_files: List[str] = []
        seen_files: Set[str] = set()
        total_hunks = 0

        for sec in file_sections:
            total_hunks += len(sec["hunks"])

            # Check for excessive hunks
            if len(sec["hunks"]) > self._config.max_hunks_per_file:
                errors.append(
                    f"File '{sec['raw_target']}' contains {len(sec['hunks'])} hunks, exceeding limit of {self._config.max_hunks_per_file}."
                )

            # File must have at least one valid hunk header
            if not sec["hunks"]:
                errors.append(f"Malformed diff: file '{sec['raw_target']}' has no valid hunk headers ('@@').")

            clean_rel_path = sec["clean_path"]

            # Deduplication check
            norm_key = clean_rel_path.lower() if os.name == "nt" else clean_rel_path
            if norm_key in seen_files:
                errors.append(f"Duplicate file entry detected in patch for '{clean_rel_path}'.")
            else:
                seen_files.add(norm_key)

            # Validate path safety rules
            self._validate_path_security(clean_rel_path, sec["raw_target"], errors)

            if clean_rel_path not in affected_files:
                affected_files.append(clean_rel_path)

        has_security_violation = is_patch_security_violation(errors)

        return PatchValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            affected_files=affected_files,
            total_files_analyzed=len(file_sections),
            total_hunks_analyzed=total_hunks,
            is_security_violation=has_security_violation,
        )

    def _parse_file_sections(self, lines: List[str], errors: List[str]) -> List[dict]:
        sections = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]

            if line.startswith("--- "):
                old_line = line
                if i + 1 >= n or not lines[i + 1].startswith("+++ "):
                    errors.append(f"Malformed header at line {i + 1}: '---' is not followed by '+++'.")
                    i += 1
                    continue

                new_line = lines[i + 1]
                i += 2

                old_path_raw = self._extract_path_from_header(old_line[4:])
                new_path_raw = self._extract_path_from_header(new_line[4:])

                target_path, path_err = self._determine_target_path(old_path_raw, new_path_raw)
                if path_err:
                    errors.append(path_err)
                    continue

                hunks = []
                while i < n and not lines[i].startswith("--- "):
                    hunk_line = lines[i]
                    if hunk_line.startswith("@@ "):
                        if not re.match(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", hunk_line):
                            errors.append(f"Malformed hunk header: '{hunk_line}'.")
                        else:
                            hunks.append(hunk_line)
                    i += 1

                sections.append({
                    "raw_old": old_path_raw,
                    "raw_new": new_path_raw,
                    "raw_target": new_path_raw if new_path_raw != "/dev/null" else old_path_raw,
                    "clean_path": target_path,
                    "hunks": hunks,
                })
            else:
                i += 1

        return sections

    def _extract_path_from_header(self, text: str) -> str:
        token = text.strip()
        if "	" in token:
            token = token.split("	", 1)[0].strip()
        elif " " in token:
            parts = token.split()
            if len(parts) >= 2 and re.match(r"^\d{4}-\d{2}-\d{2}", parts[1]):
                token = parts[0]
        return token

    def _determine_target_path(self, old_raw: str, new_raw: str) -> tuple[str, Optional[str]]:
        is_create = (old_raw == "/dev/null")
        is_delete = (new_raw == "/dev/null")

        if is_create and is_delete:
            return "", "Malformed header: both old and new paths are '/dev/null'."

        def strip_prefix(p: str) -> str:
            if p == "/dev/null":
                return p
            p = p.replace("\\", "/")
            if re.match(r"^[abciw]/", p):
                return p[2:]
            return p

        clean_old = strip_prefix(old_raw)
        clean_new = strip_prefix(new_raw)

        if is_create:
            return clean_new, None
        if is_delete:
            return clean_old, None

        if clean_old != clean_new:
            return "", (
                f"Unsupported rename operation: old path '{clean_old}' does not match new path '{clean_new}'."
            )

        return clean_new, None

    def _validate_path_security(self, rel_path: str, raw_target: str, errors: List[str]) -> None:
        if not rel_path or not rel_path.strip():
            errors.append("Invalid empty path in diff header.")
            return

        if "\x00" in raw_target or "\x00" in rel_path:
            errors.append(f"Path contains illegal null byte: '{raw_target}'.")
            return

        if ":" in raw_target or ":" in rel_path:
            errors.append(f"Windows drive path or colon illegal in relative path: '{raw_target}'.")
            return

        if raw_target.startswith("\\") or raw_target.startswith("//"):
            errors.append(f"UNC share paths are strictly forbidden: '{raw_target}'.")
            return

        if raw_target.startswith("/") or raw_target.startswith("\\"):
            errors.append(f"Absolute paths are forbidden: '{raw_target}'.")
            return

        normalized = rel_path.replace("\\", "/")

        parts = normalized.split("/")
        if any(p == ".." for p in parts):
            errors.append(f"Path traversal '..' is strictly forbidden: '{rel_path}'.")
            return

        filename = parts[-1]

        for p in parts:
            if p.lower() in self._config.blocked_directories:
                errors.append(f"Access to protected repository directory '{p}' is forbidden in path '{rel_path}'.")
                return

        if filename.lower() in self._config.blocked_filenames:
            errors.append(f"Modification of sensitive file '{filename}' is blocked.")
            return

        ext = "".join(Path(filename).suffixes).lower()
        simple_ext = Path(filename).suffix.lower()

        if simple_ext in self._config.blocked_extensions or ext in self._config.blocked_extensions:
            errors.append(f"File extension '{simple_ext or ext}' is blocked for file '{rel_path}'.")
            return

        if self._config.allowed_extensions is not None:
            if simple_ext not in self._config.allowed_extensions and ext not in self._config.allowed_extensions:
                errors.append(
                    f"File extension '{simple_ext or ext}' of file '{rel_path}' is not in the allowed extensions list."
                )
                return

        try:
            resolved_target = (self._workspace_root / normalized).resolve()
        except Exception as resolve_err:
            errors.append(f"Failed to resolve path '{rel_path}': {resolve_err}")
            return

        try:
            if not resolved_target.is_relative_to(self._workspace_root):
                errors.append(f"Path '{rel_path}' resolves outside workspace root.")
                return
        except AttributeError:
            if os.path.commonpath([str(resolved_target), str(self._workspace_root)]) != str(self._workspace_root):
                errors.append(f"Path '{rel_path}' resolves outside workspace root.")
                return

        if resolved_target.is_symlink():
            errors.append(f"Target path '{rel_path}' is a symlink, which is strictly forbidden.")
            return

        current = resolved_target.parent
        while current != self._workspace_root and current != current.parent:
            if current.exists() and current.is_symlink():
                errors.append(f"Parent directory '{current.name}' in path '{rel_path}' is a symlink, which is forbidden.")
                return
            current = current.parent


def validate_patch(
    unified_diff: Union[str, bytes],
    workspace_root: Union[str, Path],
    config: Optional[PatchValidatorConfig] = None,
) -> PatchValidationResult:
    """Convenience functional wrapper for patch safety validation."""
    validator = PatchValidator(workspace_root=workspace_root, config=config)
    return validator.validate(unified_diff=unified_diff)
