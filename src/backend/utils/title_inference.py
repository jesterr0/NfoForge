from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
import re
from typing import Any

from guessit import guessit

from src.backend.utils.guessit_helpers import get_guessit_title
from src.exceptions import MediaParsingError


class TitleWeight(IntEnum):
    """Relative confidence assigned to each source of title evidence."""

    VIDEO_FILENAME = 100
    INPUT_DIRECTORY = 35
    PARENT_DIRECTORY = 25
    GRANDPARENT_DIRECTORY = 15
    GREAT_GRANDPARENT_DIRECTORY = 5


@dataclass(frozen=True, slots=True)
class TitleInferenceResult:
    """Result returned by MediaTitleInferer."""

    title: str
    confidence: float
    candidates: tuple[tuple[str, int], ...]


@dataclass(slots=True)
class _Candidate:
    """Internal title candidate used while accumulating evidence."""

    display_name: str
    score: int = 0


class MediaTitleInferer:
    """Infer a movie or series title from an arbitrary file or directory.

    Supported input examples:

        Movie.Name.2025.1080p.mkv

        Movie.Name.2025/
            Movie.Name.2025.1080p.mkv

        Show.Name/
            Season 1/
                Show.Name.S01E01.mkv
                Show.Name.S01E02.mkv

        Season 1/
            Show.Name.S01E01.mkv
            Show.Name.S01E02.mkv

    The inferer gathers evidence from video filenames, the selected directory,
    and a limited number of ancestor directories. Filename evidence is given
    the greatest weight.
    """

    VIDEO_EXTENSIONS = frozenset(
        {
            ".3gp",
            ".avi",
            ".divx",
            ".flv",
            ".iso",
            ".m2ts",
            ".m4v",
            ".mkv",
            ".mov",
            ".mp4",
            ".mpeg",
            ".mpg",
            ".mts",
            ".ogm",
            ".ogv",
            ".rm",
            ".rmvb",
            ".ts",
            ".vob",
            ".webm",
            ".wmv",
        }
    )

    GENERIC_DIRECTORY_NAMES = frozenset(
        {
            "bdmv",
            "bluray",
            "blu ray",
            "disc",
            "disk",
            "download",
            "downloads",
            "dvd",
            "extra",
            "extras",
            "featurettes",
            "media",
            "movie",
            "movies",
            "sample",
            "samples",
            "season",
            "special",
            "specials",
            "tv",
            "tv show",
            "tv shows",
            "video",
            "videos",
            "video ts",
        }
    )

    GENERIC_DIRECTORY_PATTERNS = (
        re.compile(r"^(?:season|series)\s*\d{1,3}$", re.IGNORECASE),
        re.compile(r"^s\d{1,3}$", re.IGNORECASE),
        re.compile(r"^(?:disc|disk|dvd|cd)\s*\d{1,3}$", re.IGNORECASE),
        re.compile(r"^\d{1,3}$"),
    )

    SAMPLE_PATTERN = re.compile(
        r"(?:^|[._\-\s])sample(?:$|[._\-\s])",
        re.IGNORECASE,
    )

    SPACE_PATTERN = re.compile(r"\s+")
    SEPARATOR_PATTERN = re.compile(r"[._]+")
    BRACKET_PATTERN = re.compile(r"[\[\]{}()]")

    DIRECTORY_WEIGHTS = (
        TitleWeight.PARENT_DIRECTORY,
        TitleWeight.GRANDPARENT_DIRECTORY,
        TitleWeight.GREAT_GRANDPARENT_DIRECTORY,
    )

    def __init__(
        self,
        *,
        recursive: bool = True,
        include_samples: bool = False,
    ) -> None:
        self.recursive = recursive
        self.include_samples = include_samples

        self._guess_cache: dict[str, dict[str, Any]] = {}
        self._candidates: dict[str, _Candidate] = {}

    def infer(
        self,
        input_path: Path | str,
        video_files: Iterable[Path | str] | None = None,
    ) -> TitleInferenceResult:
        """Infer the most likely title for a file or directory.

        Args:
            input_path: A video file or directory containing media.
            video_files: Optional selected media files to use as filename
                evidence. When omitted, supported files are discovered from
                ``input_path``. Directory context is always derived from the
                input path and selected files.

        Returns:
            The selected title, confidence score, and ranked candidates.

        Raises:
            FileNotFoundError: The supplied path does not exist.
            MediaParsingError: No usable title evidence could be found.
        """

        path = Path(input_path).expanduser()

        if not path.exists():
            raise FileNotFoundError(f"Input path does not exist: {path}")

        self._guess_cache.clear()
        self._candidates.clear()

        if video_files is None:
            collected_video_files = self._collect_video_files(path)
        else:
            collected_video_files = self._normalize_video_files(video_files)

        for video_file in collected_video_files:
            self._score_video_filename(video_file)

        self._score_directory_context(path, collected_video_files)

        return self._build_result(path)

    def infer_title(
        self,
        input_path: Path | str,
        video_files: Iterable[Path | str] | None = None,
    ) -> str:
        """Convenience method returning only the winning title."""

        return self.infer(input_path, video_files=video_files).title

    def _normalize_video_files(self, video_files: Iterable[Path | str]) -> list[Path]:
        """Normalize an explicit selection of media files."""

        paths = {Path(video_file).expanduser() for video_file in video_files}
        return sorted(
            (
                path
                for path in paths
                if path.is_file()
                and self._is_video_file(path)
                and (self.include_samples or not self._is_sample(path))
            ),
            key=lambda path: str(path).casefold(),
        )

    def _collect_video_files(self, input_path: Path) -> list[Path]:
        """Collect supported video files from the supplied path."""

        if input_path.is_file():
            if not self._is_video_file(input_path):
                raise MediaParsingError(
                    f"The selected file is not a supported video: {input_path.name}"
                )

            return [input_path]

        iterator: Iterable[Path]

        if self.recursive:
            iterator = input_path.rglob("*")
        else:
            iterator = input_path.iterdir()

        files = [
            path
            for path in iterator
            if path.is_file()
            and self._is_video_file(path)
            and (self.include_samples or not self._is_sample(path))
        ]

        # Stable ordering makes tie behavior deterministic.
        return sorted(files, key=lambda path: str(path).casefold())

    def _score_video_filename(self, video_file: Path) -> None:
        """Extract and score title evidence from a video filename."""

        title = self._extract_guessit_title(video_file.stem)

        if title is not None:
            self._add_candidate(title, TitleWeight.VIDEO_FILENAME)

    def _score_directory_context(
        self,
        input_path: Path,
        video_files: list[Path],
    ) -> None:
        """Score the selected directory and nearby ancestor directories.

        Each directory is scored only once. This prevents a season containing
        twenty episodes from casting twenty duplicate votes for "Season 1" or
        its parent directory.
        """

        directories: dict[Path, int] = {}

        if input_path.is_dir():
            directories[input_path] = int(TitleWeight.INPUT_DIRECTORY)
            starting_directories = {input_path}
        else:
            directories[input_path.parent] = int(TitleWeight.INPUT_DIRECTORY)
            starting_directories = {input_path.parent}

        # Include immediate directories containing discovered videos. This is
        # useful when the selected directory contains several nested seasons.
        for video_file in video_files:
            starting_directories.add(video_file.parent)

        for starting_directory in starting_directories:
            current = starting_directory

            for weight in self.DIRECTORY_WEIGHTS:
                if current == current.parent:
                    break

                previous_weight = directories.get(current, 0)
                directories[current] = max(previous_weight, int(weight))
                current = current.parent

        for directory, weight in directories.items():
            title = self._extract_directory_title(directory)

            if title is not None:
                self._add_candidate(title, weight)

    def _extract_guessit_title(self, value: str) -> str | None:
        """Extract a movie or series title using GuessIt."""

        guess = self._guess(value)

        # GuessIt normally stores the movie or series name under "title".
        # Episode names are generally stored separately as "episode_title".
        title = get_guessit_title(guess)

        if not title:
            # Retain support for callers or GuessIt versions that provide a
            # dedicated series field.
            title = self._coerce_guessit_text(guess.get("series"))

        if title is None:
            return None

        title = self._clean_title(title)

        if not title or self._is_generic_title(title):
            return None

        year = guess.get("year")

        if isinstance(year, int) and not self._title_contains_year(title, year):
            return f"{title} {year}"

        return title

    def _extract_directory_title(self, directory: Path) -> str | None:
        """Extract a candidate from a directory name.

        GuessIt is tried first. A sanitized directory name is used as a
        fallback when GuessIt does not return a useful title.
        """

        directory_name = directory.name.strip()

        if not directory_name:
            return None

        sanitized = self._sanitize_directory_name(directory_name)

        if not sanitized or self._is_generic_title(sanitized):
            return None

        guessed_title = self._extract_guessit_title(directory_name)

        if guessed_title is not None:
            return guessed_title

        return sanitized

    def _guess(self, value: str) -> dict[str, Any]:
        """Run GuessIt while caching repeated values."""

        cache_key = value.casefold()

        if cache_key not in self._guess_cache:
            result = guessit(
                value,
                {
                    "excludes": ["language"],
                },
            )
            self._guess_cache[cache_key] = dict(result)

        return self._guess_cache[cache_key]

    def _add_candidate(self, title: str, weight: int) -> None:
        """Add weighted evidence while merging equivalent capitalization."""

        cleaned = self._clean_title(title)

        if not cleaned or self._is_generic_title(cleaned):
            return

        key = self._candidate_key(cleaned)
        candidate = self._candidates.get(key)

        if candidate is None:
            self._candidates[key] = _Candidate(
                display_name=cleaned,
                score=int(weight),
            )
            return

        candidate.score += int(weight)

        # Prefer the more descriptive representation when equivalent keys
        # differ only in formatting or capitalization.
        if self._display_quality(cleaned) > self._display_quality(
            candidate.display_name
        ):
            candidate.display_name = cleaned

    def _build_result(self, input_path: Path) -> TitleInferenceResult:
        """Select the highest-scoring candidate."""

        if not self._candidates:
            raise MediaParsingError(
                f"Failed to determine a title from {input_path.name or input_path}."
            )

        ranked_candidates = sorted(
            self._candidates.values(),
            key=lambda candidate: (
                -candidate.score,
                -self._display_quality(candidate.display_name)[0],
                -self._display_quality(candidate.display_name)[1],
                candidate.display_name.casefold(),
            ),
        )

        winner = ranked_candidates[0]
        total_score = sum(candidate.score for candidate in ranked_candidates)

        confidence = winner.score / total_score if total_score > 0 else 0.0

        ranked = tuple(
            (candidate.display_name, candidate.score) for candidate in ranked_candidates
        )

        return TitleInferenceResult(
            title=winner.display_name,
            confidence=confidence,
            candidates=ranked,
        )

    def _sanitize_directory_name(self, value: str) -> str:
        """Convert a directory name into readable title text."""

        value = self.SEPARATOR_PATTERN.sub(" ", value)
        value = value.replace("-", " ")
        value = self.BRACKET_PATTERN.sub(" ", value)
        return self._clean_title(value)

    def _clean_title(self, value: str) -> str:
        """Normalize whitespace without altering meaningful capitalization."""

        return self.SPACE_PATTERN.sub(" ", value).strip(" ._-")

    def _is_generic_title(self, value: str) -> bool:
        """Return whether a value is structural rather than a media title."""

        normalized = self._candidate_key(value)

        if normalized in self.GENERIC_DIRECTORY_NAMES:
            return True

        return any(
            pattern.fullmatch(normalized) for pattern in self.GENERIC_DIRECTORY_PATTERNS
        )

    def _candidate_key(self, value: str) -> str:
        """Create a normalized key used to merge equivalent candidates."""

        normalized = self.SEPARATOR_PATTERN.sub(" ", value)
        normalized = self.SPACE_PATTERN.sub(" ", normalized)
        return normalized.strip(" ._-").casefold()

    def _is_video_file(self, path: Path) -> bool:
        return path.suffix.casefold() in self.VIDEO_EXTENSIONS

    def _is_sample(self, path: Path) -> bool:
        return bool(self.SAMPLE_PATTERN.search(path.stem))

    @staticmethod
    def _coerce_guessit_text(value: object) -> str | None:
        """Convert GuessIt string or list-like title values into text."""

        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None

        if isinstance(value, list | tuple):
            for part in value:
                if isinstance(part, str) and part.strip():
                    return part.strip()

        return None

    @staticmethod
    def _title_contains_year(title: str, year: int) -> bool:
        return bool(
            re.search(
                rf"(?<!\d){re.escape(str(year))}(?!\d)",
                title,
            )
        )

    @staticmethod
    def _display_quality(value: str) -> tuple[int, int]:
        """Rank candidate display strings for deterministic tie-breaking."""

        uppercase_count = sum(character.isupper() for character in value)
        return uppercase_count, len(value)
