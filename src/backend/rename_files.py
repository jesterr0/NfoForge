from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import traceback
from uuid import uuid4

from tenacity import Retrying, retry_if_exception, stop_after_attempt
from tenacity.wait import wait_exponential

from src.logger.nfo_forge_logger import LOG

RENAME_ATTEMPTS = 3
_RETRYABLE_WINERRORS = {5, 32, 33}
_RETRYABLE_ERRNOS = {errno.EACCES, errno.EBUSY}


@dataclass(frozen=True, slots=True)
class RenamePlan:
    """A fully derived set of in-place file and directory renames."""

    file_targets: dict[Path, Path]
    directory_targets: dict[Path, Path]
    input_path: Path | None

    @classmethod
    def build(
        cls,
        file_targets: dict[Path, Path],
        input_path: Path | None,
    ) -> RenamePlan:
        effective_targets = {
            source: target
            for source, target in file_targets.items()
            if _paths_differ(source, target)
        }
        directory_targets: dict[Path, Path] = {}

        for source, target in effective_targets.items():
            source_directory = source.parent
            target_directory = target.parent
            if not _paths_differ(source_directory, target_directory):
                continue

            existing_target = directory_targets.get(source_directory)
            if existing_target is not None and _paths_differ(
                existing_target, target_directory
            ):
                raise ValueError(
                    "Files from the same source folder cannot be renamed into "
                    "multiple destination folders."
                )
            directory_targets[source_directory] = target_directory

        return cls(
            file_targets=effective_targets,
            directory_targets=directory_targets,
            input_path=input_path,
        )


@dataclass(frozen=True, slots=True)
class RenameResult:
    """The final filesystem state produced by a rename attempt."""

    success: bool
    path_mapping: dict[Path, Path]
    updated_input_path: Path | None
    message: str | None = None
    rollback_complete: bool = True


@dataclass(frozen=True, slots=True)
class _RenameOperation:
    source: Path
    target: Path
    is_directory: bool


class RenameExecutor:
    """Validate and execute a rename plan without copying media data."""

    @classmethod
    def execute(cls, plan: RenamePlan) -> RenameResult:
        try:
            cls._preflight(plan)
        except (OSError, ValueError) as error:
            return RenameResult(
                success=False,
                path_mapping={},
                updated_input_path=plan.input_path,
                message=cls._format_error(error),
            )

        current_paths = {source: source for source in plan.file_targets}
        journal: list[_RenameOperation] = []

        try:
            # A re-sequenced pack can target names currently occupied by other
            # files in the same plan (for example E01 -> E02, E02 -> E03).
            # Vacate only those blocking source paths first; every temporary
            # hop is journaled so the normal rollback path remains atomic.
            for source in cls._blocking_sources(plan):
                temporary = cls._temporary_path(source)
                cls._rename_with_journal(
                    source,
                    temporary,
                    is_directory=False,
                    journal=journal,
                )
                current_paths[source] = temporary

            # Rename filenames while their original parent still exists. The
            # parent directory is renamed last so a folder failure can be
            # rolled back without losing track of any large media files.
            for source, final_target in plan.file_targets.items():
                current_source = current_paths[source]
                target = cls._intermediate_file_target(plan, source, final_target)
                if not _paths_differ(current_source, target):
                    continue
                cls._rename_with_journal(
                    current_source,
                    target,
                    is_directory=False,
                    journal=journal,
                )
                current_paths[source] = target

            for source_directory, target_directory in plan.directory_targets.items():
                cls._rename_with_journal(
                    source_directory,
                    target_directory,
                    is_directory=True,
                    journal=journal,
                )
                cls._remap_directory(current_paths, source_directory, target_directory)

            missing_targets = [
                path for path in current_paths.values() if not path.is_file()
            ]
            if missing_targets:
                raise FileNotFoundError(
                    "Rename verification failed; expected file(s) were not found: "
                    + ", ".join(str(path) for path in missing_targets)
                )

            mapping = {
                source: current
                for source, current in current_paths.items()
                if _paths_differ(source, current)
            }
            updated_input_path = cls._remap_input_path(
                plan.input_path, current_paths, plan.directory_targets
            )
            return RenameResult(
                success=True,
                path_mapping=mapping,
                updated_input_path=updated_input_path,
            )
        except OSError as error:
            LOG.error(
                LOG.LOG_SOURCE.BE,
                f"Rename operation failed:\n{traceback.format_exc()}",
            )
            cls._replay_journal(journal, current_paths)
            rollback_complete = cls._rollback(journal, current_paths)
            mapping = {
                source: current
                for source, current in current_paths.items()
                if _paths_differ(source, current)
            }
            updated_input_path = cls._remap_input_path_from_current(
                plan.input_path, current_paths
            )
            message = cls._format_error(error)
            if rollback_complete:
                message += "\n\nNo rename changes were kept."
            else:
                message += (
                    "\n\nSome completed renames could not be restored. NfoForge "
                    "updated its paths to the files it could locate; review the "
                    "rename preview before retrying."
                )
            return RenameResult(
                success=False,
                path_mapping=mapping,
                updated_input_path=updated_input_path,
                message=message,
                rollback_complete=rollback_complete,
            )

    @classmethod
    def _preflight(cls, plan: RenamePlan) -> None:
        target_keys: dict[str, Path] = {}
        intermediate_keys: dict[str, Path] = {}
        moving_source_keys = {
            _path_key(source)
            for source, final_target in plan.file_targets.items()
            if _paths_differ(
                source,
                cls._intermediate_file_target(plan, source, final_target),
            )
        }

        for source, final_target in plan.file_targets.items():
            if not source.is_file():
                raise FileNotFoundError(f"Source file does not exist: {source}")
            cls._validate_same_volume(source, final_target)

            expected_parent = plan.directory_targets.get(source.parent, source.parent)
            if _path_key(final_target.parent) != _path_key(expected_parent):
                raise ValueError(
                    "File renames must stay in the source folder (or its mapped "
                    f"destination folder): {source} -> {final_target}"
                )

            target_key = _path_key(final_target)
            previous_target = target_keys.get(target_key)
            if previous_target is not None:
                raise FileExistsError(
                    "Multiple files would use the same destination: "
                    f"{previous_target} and {final_target}"
                )
            target_keys[target_key] = final_target

            target = cls._intermediate_file_target(plan, source, final_target)
            intermediate_key = _path_key(target)
            previous_intermediate = intermediate_keys.get(intermediate_key)
            if previous_intermediate is not None:
                raise FileExistsError(
                    "Multiple files would use the same intermediate name: "
                    f"{previous_intermediate} and {target}"
                )
            intermediate_keys[intermediate_key] = target

            if not target.parent.is_dir():
                raise FileNotFoundError(
                    f"Destination parent folder does not exist: {target.parent}"
                )
            if intermediate_key not in moving_source_keys:
                cls._reject_existing_target(source, target)

        directory_target_keys: dict[str, Path] = {}
        for source_directory, target_directory in plan.directory_targets.items():
            if not source_directory.is_dir():
                raise FileNotFoundError(
                    f"Source folder does not exist: {source_directory}"
                )
            if _path_key(source_directory.parent) != _path_key(target_directory.parent):
                raise ValueError(
                    "Folder renames must remain in the same parent directory: "
                    f"{source_directory} -> {target_directory}"
                )
            cls._validate_same_volume(source_directory, target_directory)

            target_key = _path_key(target_directory)
            previous_target = directory_target_keys.get(target_key)
            if previous_target is not None:
                raise FileExistsError(
                    "Multiple folders would use the same destination: "
                    f"{previous_target} and {target_directory}"
                )
            directory_target_keys[target_key] = target_directory
            cls._reject_existing_target(source_directory, target_directory)

    @staticmethod
    def _intermediate_file_target(
        plan: RenamePlan,
        source: Path,
        final_target: Path,
    ) -> Path:
        if source.parent in plan.directory_targets:
            return source.parent / final_target.name
        return final_target

    @classmethod
    def _blocking_sources(cls, plan: RenamePlan) -> list[Path]:
        """Return source files that must be vacated before final renames."""
        blocking_keys: set[str] = set()
        for source, final_target in plan.file_targets.items():
            target = cls._intermediate_file_target(plan, source, final_target)
            target_key = _path_key(target)
            if target_key != _path_key(source):
                blocking_keys.add(target_key)

        return [
            source for source in plan.file_targets if _path_key(source) in blocking_keys
        ]

    @staticmethod
    def _validate_same_volume(source: Path, target: Path) -> None:
        if os.path.normcase(source.anchor) != os.path.normcase(target.anchor):
            raise ValueError(
                "Renames must stay on the same drive or network share; files "
                f"will not be copied: {source} -> {target}"
            )

    @staticmethod
    def _reject_existing_target(source: Path, target: Path) -> None:
        if not target.exists():
            return
        if _path_key(source) == _path_key(target):
            return
        raise FileExistsError(f"Destination already exists: {target}")

    @classmethod
    def _rename_with_journal(
        cls,
        source: Path,
        target: Path,
        *,
        is_directory: bool,
        journal: list[_RenameOperation],
    ) -> None:
        if _is_case_only_change(source, target):
            temporary = cls._temporary_path(source)
            cls._rename_with_retry(source, temporary)
            journal.append(_RenameOperation(source, temporary, is_directory))
            cls._rename_with_retry(temporary, target)
            journal.append(_RenameOperation(temporary, target, is_directory))
        else:
            cls._rename_with_retry(source, target)
            journal.append(_RenameOperation(source, target, is_directory))

        kind = "folder" if is_directory else "file"
        LOG.debug(LOG.LOG_SOURCE.BE, f"Renamed {kind}: {source} -> {target}")

    @classmethod
    def _rename_with_retry(cls, source: Path, target: Path) -> None:
        for attempt in Retrying(
            retry=retry_if_exception(cls._is_retryable_error),
            stop=stop_after_attempt(RENAME_ATTEMPTS),
            wait=wait_exponential(multiplier=0.25, min=0.25, max=0.5),
            reraise=True,
        ):
            with attempt:
                cls._reject_existing_target(source, target)
                source.rename(target)

    @staticmethod
    def _is_retryable_error(error: BaseException) -> bool:
        if not isinstance(error, OSError):
            return False
        return (
            getattr(error, "winerror", None) in _RETRYABLE_WINERRORS
            or error.errno in _RETRYABLE_ERRNOS
        )

    @staticmethod
    def _temporary_path(source: Path) -> Path:
        while True:
            candidate = (
                source.parent / f".{source.name}.nfoforge-rename-{uuid4().hex}.tmp"
            )
            if not candidate.exists():
                return candidate

    @classmethod
    def _rollback(
        cls,
        journal: list[_RenameOperation],
        current_paths: dict[Path, Path],
    ) -> bool:
        rollback_complete = True
        for operation in reversed(journal):
            if not operation.target.exists():
                rollback_complete = False
                continue
            try:
                cls._rename_with_retry(operation.target, operation.source)
            except OSError:
                rollback_complete = False
                LOG.error(
                    LOG.LOG_SOURCE.BE,
                    "Failed to roll back rename "
                    f"{operation.target} -> {operation.source}:\n"
                    f"{traceback.format_exc()}",
                )
                continue

            if operation.is_directory:
                cls._remap_directory(current_paths, operation.target, operation.source)
            else:
                for original, current in current_paths.items():
                    if not _paths_differ(current, operation.target):
                        current_paths[original] = operation.source

        return rollback_complete and all(
            path.is_file() for path in current_paths.values()
        )

    @classmethod
    def _replay_journal(
        cls,
        journal: list[_RenameOperation],
        current_paths: dict[Path, Path],
    ) -> None:
        """Rebuild tracked paths from completed filesystem operations."""
        replayed_paths = {source: source for source in current_paths}
        for operation in journal:
            if operation.is_directory:
                cls._remap_directory(
                    replayed_paths,
                    operation.source,
                    operation.target,
                )
                continue
            for original, current in replayed_paths.items():
                if not _paths_differ(current, operation.source):
                    replayed_paths[original] = operation.target
                    break

        current_paths.clear()
        current_paths.update(replayed_paths)

    @staticmethod
    def _remap_directory(
        current_paths: dict[Path, Path],
        source_directory: Path,
        target_directory: Path,
    ) -> None:
        for original, current in current_paths.items():
            try:
                relative = current.relative_to(source_directory)
            except ValueError:
                continue
            current_paths[original] = target_directory / relative

    @staticmethod
    def _remap_input_path(
        input_path: Path | None,
        current_paths: dict[Path, Path],
        directory_targets: dict[Path, Path],
    ) -> Path | None:
        if input_path is None:
            return None
        mapped_file = current_paths.get(input_path)
        if mapped_file is not None:
            return mapped_file
        return directory_targets.get(input_path, input_path)

    @staticmethod
    def _remap_input_path_from_current(
        input_path: Path | None,
        current_paths: dict[Path, Path],
    ) -> Path | None:
        if input_path is None:
            return None
        mapped_file = current_paths.get(input_path)
        if mapped_file is not None:
            return mapped_file

        for original, current in current_paths.items():
            if original.parent == input_path and _paths_differ(
                current.parent, input_path
            ):
                return current.parent
        return input_path

    @staticmethod
    def _format_error(error: BaseException) -> str:
        if isinstance(error, FileExistsError):
            return (
                f"{error}\n\nChoose a different name or move the existing "
                "destination before retrying."
            )
        if isinstance(error, PermissionError):
            return (
                f"Windows denied the rename: {error}\n\nClose programs using the "
                "folder or files, confirm the destination does not already exist, "
                "and verify that your account has modify/delete permission on the "
                "drive or network share."
            )
        if isinstance(error, FileNotFoundError):
            return (
                f"{error}\n\nThe input may have been moved or renamed outside "
                "NfoForge. Re-select the media if it is no longer in this location."
            )
        return f"Could not complete the rename: {error}"


def _absolute_text(path: Path) -> str:
    return os.path.abspath(os.fspath(path))


def _path_key(path: Path) -> str:
    return os.path.normcase(_absolute_text(path))


def _paths_differ(source: Path, target: Path) -> bool:
    return _absolute_text(source) != _absolute_text(target)


def _is_case_only_change(source: Path, target: Path) -> bool:
    return _paths_differ(source, target) and _path_key(source) == _path_key(target)
