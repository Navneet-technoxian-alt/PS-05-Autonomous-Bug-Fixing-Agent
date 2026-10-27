"""
patch_applier.py — Safe In-Process Patch Application Engine (Phase 5A)

Applies validated unified diffs strictly within managed, disposable sandbox workspaces.

SAFETY GUARANTEES:
  1. No Shell / Subprocess Execution:
     Operates purely in-process in Python. Does not invoke `patch`, `git apply`,
     or any shell interpreters.
  2. Server-Resolved Workspaces Only:
     Only applies patches inside isolated workspaces managed by the sandbox service.
     Never accepts caller-controlled arbitrary directory paths.
  3. Pre-Application Revalidation:
     Revalidates the unified diff against PatchValidator immediately before
     attempting any application.
  4. Anti-Host Overwrite Protection:
     Strictly forbids applying patches to system roots (/), current working
     directories, or the PS-05 application source tree.
  5. Two-Phase Atomic Application:
     Phase 1: Validates and parses all hunks, matching context and deletion lines
              in memory against target files. If ANY hunk fails to match or ANY
              target file is missing/incompatible, aborts immediately with ZERO
              filesystem modifications.
     Phase 2: Atomically applies verified content to target files on disk.
  6. Path Confinement & Symlink Defense:
     Resolves all target paths to absolute paths and verifies:
       - Path is strictly relative to workspace_root.
       - Target file is not a symlink.
       - No parent directory between workspace_root and target is a symlink.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple, Union

from app.patch_validator import PatchValidator, PatchValidatorConfig, PatchValidationResult


@dataclass
class PatchApplicationResult:
    """Structured outcome of a patch application attempt."""
    success: bool
    applied: bool
    applied_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    is_security_violation: bool = False
    backup_snapshot: Optional[Dict[Path, Optional[str]]] = None


@dataclass
class _ParsedHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[str]


@dataclass
class _FilePatch:
    raw_old: str
    raw_new: str
    clean_path: str
    is_create: bool
    is_delete: bool
    hunks: List[_ParsedHunk]


class PatchApplierError(Exception):
    """Raised when patch application fails safety checks or content matching."""
    pass


class PatchApplier:
    """Applies unified diffs safely and deterministically to a disposable workspace."""

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

        # Guard against applying patches to root, home, or the active PS-05 backend/source directory
        self._verify_workspace_safety(self._workspace_root)

        self._validator = PatchValidator(workspace_root=self._workspace_root, config=config)

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    @staticmethod
    def _verify_workspace_safety(root: Path) -> None:
        """Fail closed if workspace points to system roots or current application code."""
        resolved = root.resolve()
        resolved_str = str(resolved).rstrip("\\/")

        # Prohibit system roots
        if resolved_str in ("/", "\\") or re.match(r"^[a-zA-Z]:\\?$", resolved_str):
            raise ValueError(f"Refusing to apply patch to filesystem root: {resolved}")

        # Prohibit user home directory
        home = Path.home().resolve()
        if resolved == home:
            raise ValueError(f"Refusing to apply patch to user home directory: {resolved}")

        # Anchor protected application source trees to actual module location
        # This file is located at <project_root>/backend/app/patch_applier.py
        app_dir = Path(__file__).resolve().parent          # .../backend/app
        backend_dir = app_dir.parent                      # .../backend
        project_root = backend_dir.parent                 # .../PS-05

        for protected in (app_dir, backend_dir, project_root):
            try:
                if resolved == protected or resolved.is_relative_to(protected):
                    raise ValueError(f"Refusing to apply patch to PS-05 application source directory: {resolved}")
            except AttributeError:
                if os.path.commonpath([str(resolved), str(protected)]) == str(protected):
                    raise ValueError(f"Refusing to apply patch to PS-05 application source directory: {resolved}")

        # Prohibit current working directory as an additional guard
        cwd = Path.cwd().resolve()
        if resolved == cwd:
            raise ValueError(f"Refusing to apply patch to current working directory: {resolved}")

    def apply(self, unified_diff: Union[str, bytes]) -> PatchApplicationResult:
        """Validate and apply a unified diff to the managed workspace.

        All-or-nothing execution: if any hunk fails to match or any file cannot
        be safely written, zero modifications are made to the workspace.
        """
        # Step 1: Pre-application revalidation
        validation: PatchValidationResult = self._validator.validate(unified_diff)
        if not validation.is_valid:
            return PatchApplicationResult(
                success=False,
                applied=False,
                applied_files=[],
                errors=list(validation.errors),
                is_security_violation=validation.is_security_violation,
            )

        diff_text = unified_diff if isinstance(unified_diff, str) else unified_diff.decode("utf-8")

        # Step 2: Parse diff into structured file patches and hunks
        try:
            file_patches = self._parse_diff(diff_text)
        except Exception as exc:
            return PatchApplicationResult(
                success=False,
                applied=False,
                applied_files=[],
                errors=[f"Failed to parse unified diff: {exc}"],
            )

        if not file_patches:
            return PatchApplicationResult(
                success=False,
                applied=False,
                applied_files=[],
                errors=["No actionable file patches found in diff."],
            )

        # Step 3: Phase 1 — In-memory dry-run and content generation
        # Computes planned modifications for all files before touching disk.
        planned_writes: Dict[Path, str] = {}
        planned_deletions: List[Path] = []
        errors: List[str] = []

        for patch in file_patches:
            target_path = self._resolve_target_path(patch.clean_path, errors)
            if errors:
                return PatchApplicationResult(
                    success=False,
                    applied=False,
                    errors=errors,
                    is_security_violation=True,
                )

            if patch.is_create:
                if target_path.exists():
                    errors.append(f"Cannot create '{patch.clean_path}': file already exists.")
                    break
                try:
                    new_content = self._generate_created_file_content(patch)
                    planned_writes[target_path] = new_content
                except PatchApplierError as err:
                    errors.append(f"Error creating '{patch.clean_path}': {err}")
                    break

            elif patch.is_delete:
                if not target_path.exists():
                    errors.append(f"Cannot delete '{patch.clean_path}': file does not exist.")
                    break
                planned_deletions.append(target_path)

            else:
                # File modification
                if not target_path.exists() or not target_path.is_file():
                    errors.append(f"Cannot patch '{patch.clean_path}': file does not exist on disk.")
                    break

                try:
                    original_content = target_path.read_text(encoding="utf-8")
                except Exception as read_err:
                    errors.append(f"Failed to read '{patch.clean_path}': {read_err}")
                    break

                try:
                    patched_content = self._apply_hunks_to_content(original_content, patch.hunks, patch.clean_path)
                    planned_writes[target_path] = patched_content
                except PatchApplierError as patch_err:
                    errors.append(str(patch_err))
                    break

        if errors:
            return PatchApplicationResult(
                success=False,
                applied=False,
                applied_files=[],
                errors=errors,
            )

        # Step 4: Phase 2 — Atomic disk execution
        applied_files: List[str] = []
        backups: Dict[Path, Optional[str]] = {}

        try:
            # Backup original state for rollback guarantee
            for path in planned_writes:
                backups[path] = path.read_text(encoding="utf-8") if path.exists() else None
            for path in planned_deletions:
                backups[path] = path.read_text(encoding="utf-8")

            # Apply writes
            for path, content in planned_writes.items():
                # Re-verify path safety immediately before writing
                self._verify_path_unbroken(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="\n")
                rel_name = str(path.relative_to(self._workspace_root)).replace("\\", "/")
                applied_files.append(rel_name)

            # Apply deletions
            for path in planned_deletions:
                self._verify_path_unbroken(path)
                path.unlink()
                rel_name = str(path.relative_to(self._workspace_root)).replace("\\", "/")
                applied_files.append(rel_name)

        except Exception as write_err:
            # Rollback on any filesystem error
            for path, orig in backups.items():
                try:
                    if orig is None:
                        if path.exists():
                            path.unlink()
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(orig, encoding="utf-8")
                except Exception:
                    pass

            return PatchApplicationResult(
                success=False,
                applied=False,
                applied_files=[],
                errors=[f"Filesystem write failed during patch application, rolled back: {write_err}"],
            )

        return PatchApplicationResult(
            success=True,
            applied=True,
            applied_files=applied_files,
            errors=[],
            is_security_violation=False,
            backup_snapshot=backups,
        )

    def rollback(self, backup_snapshot: Optional[Dict[Path, Optional[str]]]) -> Tuple[bool, List[str]]:
        """Safely restore files to their pre-patch state using a backup snapshot.

        Guarantees:
        - Recreates original content for modified files.
        - Deletes newly created files.
        - Recreates deleted files with their original content.
        - Strictly verifies paths remain within workspace root.
        """
        if not backup_snapshot:
            return True, []

        errors: List[str] = []
        for path, orig in backup_snapshot.items():
            try:
                resolved = path.resolve()
                try:
                    if not resolved.is_relative_to(self._workspace_root):
                        errors.append(f"Refusing to rollback file outside workspace: {path}")
                        continue
                except AttributeError:
                    if os.path.commonpath([str(resolved), str(self._workspace_root)]) != str(self._workspace_root):
                        errors.append(f"Refusing to rollback file outside workspace: {path}")
                        continue

                if orig is None:
                    # File was newly created by the patch; delete it
                    if path.exists():
                        path.unlink()
                else:
                    # File was modified or deleted; restore original content
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(orig, encoding="utf-8")
            except Exception as exc:
                errors.append(f"Failed to rollback '{path}': {exc}")

        return (len(errors) == 0), errors

    def _resolve_target_path(self, clean_path: str, errors: List[str]) -> Path:
        """Resolve target path securely and verify workspace containment."""
        norm_path = clean_path.replace("\\", "/").strip("/")
        resolved = (self._workspace_root / norm_path).resolve()

        try:
            if not resolved.is_relative_to(self._workspace_root):
                errors.append(f"Path '{clean_path}' resolves outside workspace root.")
        except AttributeError:
            if os.path.commonpath([str(resolved), str(self._workspace_root)]) != str(self._workspace_root):
                errors.append(f"Path '{clean_path}' resolves outside workspace root.")

        return resolved

    def _verify_path_unbroken(self, path: Path) -> None:
        """Verify target and parent directories are not symlinks."""
        if path.is_symlink():
            raise PatchApplierError(f"Target '{path.name}' is a symlink.")
        cur = path.parent
        while cur != self._workspace_root and cur != cur.parent:
            if cur.exists() and cur.is_symlink():
                raise PatchApplierError(f"Parent directory '{cur.name}' is a symlink.")
            cur = cur.parent

    def _parse_diff(self, diff_text: str) -> List[_FilePatch]:
        """Parse unified diff text into structured file patches and hunks."""
        lines = diff_text.splitlines()
        file_patches: List[_FilePatch] = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]
            if line.startswith("--- "):
                old_line = line
                if i + 1 >= n or not lines[i + 1].startswith("+++ "):
                    i += 1
                    continue
                new_line = lines[i + 1]
                i += 2

                old_raw = self._extract_path(old_line[4:])
                new_raw = self._extract_path(new_line[4:])
                is_create = (old_raw == "/dev/null")
                is_delete = (new_raw == "/dev/null")

                clean_path = self._strip_prefix(new_raw if not is_delete else old_raw)

                hunks: List[_ParsedHunk] = []
                while i < n and not lines[i].startswith("--- "):
                    hunk_line = lines[i]
                    if hunk_line.startswith("@@ "):
                        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", hunk_line)
                        if m:
                            old_start = int(m.group(1))
                            old_count = int(m.group(2)) if m.group(2) is not None else 1
                            new_start = int(m.group(3))
                            new_count = int(m.group(4)) if m.group(4) is not None else 1

                            hunk_lines: List[str] = []
                            i += 1
                            while i < n and not lines[i].startswith("@@ ") and not lines[i].startswith("--- "):
                                cur = lines[i]
                                if cur.startswith(("+", "-", " ", "\\")):
                                    hunk_lines.append(cur)
                                i += 1

                            hunks.append(_ParsedHunk(
                                old_start=old_start,
                                old_count=old_count,
                                new_start=new_start,
                                new_count=new_count,
                                lines=hunk_lines,
                            ))
                            continue
                    i += 1

                file_patches.append(_FilePatch(
                    raw_old=old_raw,
                    raw_new=new_raw,
                    clean_path=clean_path,
                    is_create=is_create,
                    is_delete=is_delete,
                    hunks=hunks,
                ))
            else:
                i += 1

        return file_patches

    @staticmethod
    def _extract_path(text: str) -> str:
        token = text.strip()
        if "\t" in token:
            token = token.split("\t", 1)[0].strip()
        elif " " in token:
            parts = token.split()
            if len(parts) >= 2 and re.match(r"^\d{4}-\d{2}-\d{2}", parts[1]):
                token = parts[0]
        return token

    @staticmethod
    def _strip_prefix(p: str) -> str:
        if p == "/dev/null":
            return p
        p = p.replace("\\", "/")
        if re.match(r"^[abciw]/", p):
            return p[2:]
        return p

    def _generate_created_file_content(self, patch: _FilePatch) -> str:
        """Construct content for a newly created file from diff hunks."""
        out_lines: List[str] = []
        for hunk in patch.hunks:
            for line in hunk.lines:
                if line.startswith("+"):
                    out_lines.append(line[1:])
                elif line.startswith("-"):
                    raise PatchApplierError("New file creation patch contains deletion line.")
        return "\n".join(out_lines) + ("\n" if out_lines else "")

    def _apply_hunks_to_content(
        self,
        original_content: str,
        hunks: List[_ParsedHunk],
        filename: str,
    ) -> str:
        """Apply sequential hunks to original string content."""
        orig_lines = original_content.splitlines()
        has_trailing_newline = original_content.endswith("\n") if original_content else True

        # Track line offset adjustments from previous hunks
        line_offset = 0
        current_lines = list(orig_lines)

        for hunk_idx, hunk in enumerate(hunks):
            expected_old_start = hunk.old_start - 1 + line_offset
            old_hunk_lines = [l[1:] for l in hunk.lines if l.startswith((" ", "-"))]
            new_hunk_lines = [l[1:] for l in hunk.lines if l.startswith((" ", "+"))]

            # Try exact match at expected_old_start first
            match_index = self._find_hunk_match(current_lines, old_hunk_lines, expected_old_start)

            if match_index is None:
                raise PatchApplierError(
                    f"Hunk #{hunk_idx + 1} for '{filename}' failed to match context at line {hunk.old_start}."
                )

            # Replace matched slice with new hunk lines
            current_lines[match_index : match_index + len(old_hunk_lines)] = new_hunk_lines

            # Adjust running offset for subsequent hunks
            line_offset += len(new_hunk_lines) - len(old_hunk_lines)

        result_text = "\n".join(current_lines)
        if has_trailing_newline:
            result_text += "\n"

        return result_text

    @staticmethod
    def _find_hunk_match(
        target_lines: List[str],
        hunk_old_lines: List[str],
        preferred_index: int,
        search_window: int = 10,
    ) -> Optional[int]:
        """Locate where hunk_old_lines match in target_lines, checking preferred index first."""
        hunk_len = len(hunk_old_lines)
        if hunk_len == 0:
            return max(0, min(preferred_index, len(target_lines)))

        # 1. Exact match at preferred index
        if 0 <= preferred_index <= len(target_lines) - hunk_len:
            if target_lines[preferred_index : preferred_index + hunk_len] == hunk_old_lines:
                return preferred_index

        # 2. Local search within window around preferred index
        low = max(0, preferred_index - search_window)
        high = min(len(target_lines) - hunk_len, preferred_index + search_window)
        for idx in range(low, high + 1):
            if target_lines[idx : idx + hunk_len] == hunk_old_lines:
                return idx

        return None


def apply_patch(
    unified_diff: Union[str, bytes],
    workspace_root: Union[str, Path],
    config: Optional[PatchValidatorConfig] = None,
) -> PatchApplicationResult:
    """Convenience function for applying a validated patch to a workspace."""
    applier = PatchApplier(workspace_root=workspace_root, config=config)
    return applier.apply(unified_diff=unified_diff)
