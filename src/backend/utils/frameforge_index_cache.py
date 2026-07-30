from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any, ClassVar

from src.config.paths import ConfigPaths
from src.config.persistence import atomic_write_text
from src.enums.indexer import Indexer
from src.logger.nfo_forge_logger import LOG


@dataclass(frozen=True, slots=True)
class FrameForgeIndexPaths:
    """Index files and metadata belonging to one FrameForge input pair."""

    cache_root: Path
    entry_dir: Path
    source_index: Path | None
    encode_index: Path
    manifest: Path


class FrameForgeIndexCache:
    """Maintain reusable FrameForge indexes outside release directories.

    Encode indexes always live here so generated sidecars cannot become part
    of a recursively generated torrent. External source files are left to
    FrameForge's native index lookup; sources inside the selected upload tree
    can opt into the same private cache.
    """

    CACHE_DIR_NAME = "frameforge_indexes"
    MANIFEST_NAME = "manifest.json"
    MANIFEST_VERSION = 1
    MAX_ENTRIES: ClassVar[int] = 10
    _STEM_MAX_LENGTH = 32
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
        source_input: Path,
        encode_input: Path,
        indexer: Indexer,
        cache_source: bool = False,
    ) -> FrameForgeIndexPaths:
        """Return index paths for a source/encode pair.

        Encode indexes are always cached. Source indexes are cached only when
        ``cache_source`` is true; external comparison sources are otherwise
        left to FrameForge so it can use its native adjacent/StaxRip lookup.
        A matching manifest and the required index files constitute a cache
        hit. Any stale or incomplete entry is discarded before a new
        generation.
        """
        source = source_input.resolve()
        encode = encode_input.resolve()
        suffix = self._index_suffix(indexer)
        cache_root = self._safe_cache_root(source, encode)
        cache_root.mkdir(parents=True, exist_ok=True)

        entry_dir = cache_root / self._entry_name(
            source, encode, indexer, include_source=cache_source
        )
        source_index = (
            entry_dir / f"source_{self._safe_stem(source.stem)}{suffix}"
            if cache_source
            else None
        )
        encode_index = entry_dir / f"encode_{self._safe_stem(encode.stem)}{suffix}"
        manifest = entry_dir / self.MANIFEST_NAME
        paths = FrameForgeIndexPaths(
            cache_root=cache_root,
            entry_dir=entry_dir,
            source_index=source_index,
            encode_index=encode_index,
            manifest=manifest,
        )

        expected = self._manifest_data(
            source, encode, indexer, include_source=cache_source
        )
        if self._is_valid(paths, expected):
            self._touch_entry(entry_dir)
            reuse_message = (
                f"Reusing FrameForge indexes for {source.name} and {encode.name}"
                if cache_source
                else f"Reusing FrameForge encode index for {encode.name}"
            )
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                reuse_message,
            )
            self.prune(cache_root, active_entry=entry_dir)
            return paths

        if entry_dir.exists():
            self._remove_entry(entry_dir)
        entry_dir.mkdir(parents=True, exist_ok=True)
        if source_index:
            self._seed_source_index(source, source_index, suffix)
        self.prune(cache_root, active_entry=entry_dir)
        LOG.debug(
            LOG.LOG_SOURCE.BE,
            (
                f"Preparing FrameForge index cache for {source.name} and {encode.name}"
                if cache_source
                else f"Preparing FrameForge encode index cache for {encode.name}"
            ),
        )
        return paths

    def mark_success(
        self,
        paths: FrameForgeIndexPaths,
        source_input: Path,
        encode_input: Path,
        indexer: Indexer,
    ) -> bool:
        """Commit generated indexes after verifying the required files exist."""
        source_index_missing = (
            paths.source_index is not None and not paths.source_index.is_file()
        )
        if source_index_missing or not paths.encode_index.is_file():
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                "FrameForge completed without producing the required index files; "
                "the indexes will not be cached",
            )
            self.discard_uncommitted(paths)
            return False

        manifest_data = self._manifest_data(
            source_input.resolve(),
            encode_input.resolve(),
            indexer,
            include_source=paths.source_index is not None,
        )
        manifest_data["last_used_ns"] = time.time_ns()
        try:
            atomic_write_text(paths.manifest, json.dumps(manifest_data, indent=2))
        except OSError as error:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Could not persist FrameForge index metadata: {error}",
            )
            return False
        self._touch_entry(paths.entry_dir)
        self.prune(paths.cache_root, active_entry=paths.entry_dir)
        return True

    def discard_uncommitted(self, paths: FrameForgeIndexPaths) -> None:
        """Remove a failed entry unless it was already a valid cache hit."""
        if not paths.manifest.exists():
            self._remove_entry(paths.entry_dir)

    def prune(
        self, cache_root: Path | None = None, active_entry: Path | None = None
    ) -> None:
        """Keep only the newest valid cache entries and remove orphaned ones."""
        root = cache_root or self.cache_root
        if not root.exists():
            return

        entries: list[tuple[int, Path]] = []
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            manifest = entry / self.MANIFEST_NAME
            if not manifest.is_file():
                if entry == active_entry:
                    continue
                self._remove_entry(entry)
                continue
            try:
                json.loads(manifest.read_text(encoding="utf-8"))
                entries.append((entry.stat().st_mtime_ns, entry))
            except (OSError, ValueError, TypeError):
                if entry != active_entry:
                    self._remove_entry(entry)

        entries.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        keep = {entry for _, entry in entries[: self.MAX_ENTRIES]}
        if active_entry and active_entry in {entry for _, entry in entries}:
            keep.add(active_entry)
            if len(keep) > self.MAX_ENTRIES:
                removable = keep - {active_entry}
                oldest_kept = min(
                    removable,
                    key=lambda item: (item.stat().st_mtime_ns, item.name),
                )
                keep.remove(oldest_kept)

        for _, entry in entries:
            if entry not in keep:
                self._remove_entry(entry)

    def _safe_cache_root(self, source: Path, encode: Path) -> Path:
        """Avoid placing the cache below the common media directory."""
        common_parent = self._common_parent(source.parent, encode.parent)
        root = self.cache_root
        if common_parent is not None and self._is_relative_to(root, common_parent):
            fallback = Path(tempfile.gettempdir()) / "nfoforge" / self.CACHE_DIR_NAME
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"FrameForge cache is inside the media tree; using {fallback}",
            )
            return fallback
        return root

    @staticmethod
    def _common_parent(first: Path, second: Path) -> Path | None:
        try:
            return Path(os.path.commonpath((str(first), str(second))))
        except ValueError:
            return None

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False

    def _entry_name(
        self,
        source: Path,
        encode: Path,
        indexer: Indexer,
        *,
        include_source: bool,
    ) -> str:
        identity_parts = [str(encode), str(indexer)]
        if include_source:
            identity_parts.insert(0, str(source))
        identity = "\0".join(identity_parts)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[
            : self._HASH_LENGTH
        ]
        label = self._safe_stem(encode.stem)
        if include_source:
            label = f"{self._safe_stem(source.stem)}-{label}"
        return f"{label}-{digest}"

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

    def _manifest_data(
        self,
        source: Path,
        encode: Path,
        indexer: Indexer,
        *,
        include_source: bool,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "version": self.MANIFEST_VERSION,
            "indexer": str(indexer),
            "encode": self._file_signature(encode),
        }
        if include_source:
            data["source"] = self._file_signature(source)
        return data

    @staticmethod
    def _file_signature(path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": str(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    @staticmethod
    def _is_valid(paths: FrameForgeIndexPaths, expected: dict[str, Any]) -> bool:
        if (
            paths.source_index is not None and not paths.source_index.is_file()
        ) or not paths.encode_index.is_file():
            return False
        try:
            manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        return all(manifest.get(key) == value for key, value in expected.items())

    def _seed_source_index(self, source: Path, target: Path, suffix: str) -> None:
        """Copy a known source sidecar into the private cache, best effort.

        FrameForge remains responsible for validating the copied index and
        rebuilding it when stale. The original sidecar is never modified.
        StaxRip-specific temporary indexes are intentionally not guessed here;
        external sources use FrameForge's native lookup instead.
        """
        for candidate in self._source_index_candidates(source, suffix):
            if not candidate.is_file():
                continue
            try:
                shutil.copy2(candidate, target)
            except OSError as error:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Could not seed FrameForge source index from {candidate}: {error}",
                )
            else:
                LOG.debug(
                    LOG.LOG_SOURCE.BE,
                    f"Seeded FrameForge source index from {candidate.name}",
                )
            return

    @staticmethod
    def _source_index_candidates(source: Path, suffix: str) -> tuple[Path, ...]:
        """Return common sidecar spellings for a source file."""
        return (Path(f"{source}{suffix}"), source.with_suffix(suffix))

    @staticmethod
    def _touch_entry(entry: Path) -> None:
        try:
            now = time.time_ns()
            os.utime(entry, ns=(now, now))
        except OSError:
            pass

    @staticmethod
    def _remove_entry(entry: Path) -> None:
        try:
            shutil.rmtree(entry)
        except OSError as error:
            LOG.warning(
                LOG.LOG_SOURCE.BE, f"Could not prune FrameForge cache {entry}: {error}"
            )
