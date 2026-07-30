from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import ClassVar

from src.config.paths import ConfigPaths
from src.enums.indexer import Indexer
from src.logger.nfo_forge_logger import LOG


@dataclass(frozen=True, slots=True)
class PreparedFrameForgeIndex:
    """A private encode index prepared for one FrameForge invocation."""

    cache_root: Path
    path: Path
    existed_before: bool


class FrameForgeIndexCache:
    """Maintain reusable encode indexes outside release directories.

    FrameForge 1.4.0 only honors an explicit index path when that path already
    exists. New entries are therefore created as empty placeholders before
    FrameForge starts. L-SMASH and FFMS2 validate existing indexes themselves
    and rebuild them when required, so separate manifests are unnecessary.
    """

    CACHE_DIR_NAME = "frameforge_indexes"
    MAX_ENTRIES: ClassVar[int] = 10
    _STEM_MAX_LENGTH = 48
    _HASH_LENGTH = 12
    _INDEX_SUFFIXES = {
        Indexer.LSMASH: ".lwi",
        Indexer.FFMS2: ".ffindex",
    }

    def __init__(self, base_root: Path | None = None) -> None:
        base = base_root or ConfigPaths.default_working_dir()
        self.base_root = Path(base)

    @property
    def cache_root(self) -> Path:
        """Return the normal internal cache root without creating it."""
        return self.base_root / self.CACHE_DIR_NAME

    def prepare(
        self,
        encode_input: Path,
        indexer: Indexer,
        protected_media_root: Path | None = None,
    ) -> PreparedFrameForgeIndex:
        """Prepare a reusable private index path for an encode."""
        encode = encode_input.resolve()
        cache_root = self._safe_cache_root(protected_media_root)
        cache_root.mkdir(parents=True, exist_ok=True)

        index_path = cache_root / self._index_name(encode, indexer)
        if index_path.exists() and not index_path.is_file():
            raise OSError(f"FrameForge index path is not a file: {index_path}")

        existed_before = self._is_reusable(index_path)
        if not index_path.exists():
            index_path.touch()

        self.prune(cache_root, active_index=index_path)
        LOG.debug(
            LOG.LOG_SOURCE.BE,
            (
                f"Reusing FrameForge encode index for {encode.name}"
                if existed_before
                else f"Preparing FrameForge encode index for {encode.name}"
            ),
        )
        return PreparedFrameForgeIndex(
            cache_root=cache_root,
            path=index_path,
            existed_before=existed_before,
        )

    def mark_success(self, prepared: PreparedFrameForgeIndex) -> bool:
        """Record successful use after verifying FrameForge populated the index."""
        if not self._is_reusable(prepared.path):
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                "FrameForge completed without producing a usable encode index",
            )
            if not prepared.existed_before:
                prepared.path.unlink(missing_ok=True)
            return False

        self._touch(prepared.path)
        self.prune(prepared.cache_root, active_index=prepared.path)
        return True

    @staticmethod
    def discard_failed(prepared: PreparedFrameForgeIndex) -> None:
        """Remove only an index that did not predate the failed invocation."""
        if not prepared.existed_before:
            try:
                prepared.path.unlink(missing_ok=True)
            except OSError as error:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Could not remove failed FrameForge index {prepared.path}: {error}",
                )

    def prune(
        self,
        cache_root: Path | None = None,
        active_index: Path | None = None,
    ) -> None:
        """Keep the newest index files and remove legacy cache directories."""
        root = cache_root or self.cache_root
        if not root.exists():
            return

        indexes: list[tuple[int, Path]] = []
        for entry in root.iterdir():
            if entry.is_dir():
                self._remove_legacy_entry(entry)
                continue
            if entry.suffix.casefold() not in {".lwi", ".ffindex"}:
                continue
            try:
                indexes.append((entry.stat().st_mtime_ns, entry))
            except OSError:
                continue

        indexes.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        keep = {entry for _, entry in indexes[: self.MAX_ENTRIES]}
        if active_index and active_index in {entry for _, entry in indexes}:
            keep.add(active_index)
            if len(keep) > self.MAX_ENTRIES:
                removable = keep - {active_index}
                if removable:
                    keep.remove(
                        min(
                            removable,
                            key=lambda item: (item.stat().st_mtime_ns, item.name),
                        )
                    )

        for _, entry in indexes:
            if entry not in keep:
                try:
                    entry.unlink(missing_ok=True)
                except OSError as error:
                    LOG.warning(
                        LOG.LOG_SOURCE.BE,
                        f"Could not prune FrameForge index {entry}: {error}",
                    )

    def _safe_cache_root(self, protected_media_root: Path | None) -> Path:
        root = self.cache_root
        if protected_media_root and self._is_relative_to(root, protected_media_root):
            fallback = Path(tempfile.gettempdir()) / "nfoforge" / self.CACHE_DIR_NAME
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"FrameForge cache is inside the media tree; using {fallback}",
            )
            return fallback
        return root

    def _index_name(self, encode: Path, indexer: Indexer) -> str:
        identity = f"{encode}\0{indexer}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[
            : self._HASH_LENGTH
        ]
        return f"{self._safe_stem(encode.stem)}-{digest}{self._index_suffix(indexer)}"

    @classmethod
    def _safe_stem(cls, stem: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._ ")
        return (cleaned or "media")[: cls._STEM_MAX_LENGTH]

    @classmethod
    def _index_suffix(cls, indexer: Indexer) -> str:
        try:
            return cls._INDEX_SUFFIXES[indexer]
        except KeyError as error:
            raise ValueError(f"Unsupported FrameForge indexer: {indexer}") from error

    @staticmethod
    def _is_reusable(path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _touch(path: Path) -> None:
        try:
            now = time.time_ns()
            os.utime(path, ns=(now, now))
        except OSError:
            try:
                path.touch()
            except OSError:
                pass

    @staticmethod
    def _remove_legacy_entry(entry: Path) -> None:
        try:
            shutil.rmtree(entry)
        except OSError as error:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Could not prune legacy FrameForge cache {entry}: {error}",
            )
