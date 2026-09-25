"""Matching a series pack's files to TVDB episodes.

The desktop episode mapper shows the matches and lets the user correct them;
a headless run takes them as matched. Both go through `EpisodeMatcher`, so a
file lands on the same episode either way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import re
from typing import Any

from guessit import guessit

from nfoforge.backend.utils.episode_matching import (
    TITLE_DISAGREEMENT_FLOOR,
    TITLE_SUGGESTION_FLOOR,
    ParsedFile,
    TitleCheck,
    check_title_against_episode,
    claimed_season_episodes,
    rank_title_candidates,
)
from nfoforge.enums.series import EpisodeFormat

EpisodeData = dict[str, Any]
EpisodeMapping = dict[str, Any]

#: Assignment method for a season/episode the filename states plainly but the
#: selected TVDB ordering does not list. The numbers are kept as parsed and
#: flagged rather than discarded -- see ``_store_unverified_parse``.
UNVERIFIED_PARSE_METHOD = "parsed (no TVDB match)"
UNVERIFIED_PARSE_CONFIDENCE = 0.6


def match_by_absolute(
    files_parsed: dict[Any, int | None],
    absolute_episodes: list[dict[str, Any]],
) -> dict[Any, dict[str, Any]]:
    """Match files to TVDB absolute-order episodes by absolute episode number.

    This is a pure, Qt-free helper so it can be unit-tested without a widget.

    Args:
        files_parsed: maps an arbitrary, hashable file identifier (a
            ``Path``, a filename string, a row index, etc. -- the caller
            decides) to that file's parsed absolute episode number. This is
            typically guessit's ``episode`` value for an anime/absolute
            release that carries no season component, e.g.
            ``"[Group] Show - 025.mkv"`` parses to ``25``. A value of
            ``None`` means the file had no parseable number and is skipped.
        absolute_episodes: the list of TVDB episode dicts for the
            "Absolute Order" season type, i.e.
            ``episodes_by_type[type_id]["episodes"]`` for the entry whose
            ``type`` is ``"absolute"``. Each dict is expected to carry an
            ``absoluteNumber`` key (and typically ``seasonNumber``/``number``
            identifying where that absolute episode lives in aired order).

    Returns:
        A dict with the same keys as ``files_parsed``, but containing only
        the keys that produced a match, mapped to the matched episode dict
        from ``absolute_episodes``. Keys with no parseable number, or whose
        number doesn't appear in ``absolute_episodes``, are omitted.
    """
    episodes_by_absolute_number: dict[int, dict[str, Any]] = {}
    for episode_data in absolute_episodes:
        absolute_number = episode_data.get("absoluteNumber")
        if absolute_number is None:
            continue
        episodes_by_absolute_number.setdefault(absolute_number, episode_data)

    matches: dict[Any, dict[str, Any]] = {}
    for file_key, absolute_number in files_parsed.items():
        if absolute_number is None:
            continue
        matched_episode = episodes_by_absolute_number.get(absolute_number)
        if matched_episode is not None:
            matches[file_key] = matched_episode
    return matches


def _normalize_air_date(value: Any) -> str | None:
    """Normalize a date-like value to an ISO "YYYY-MM-DD" string.

    Accepts ``datetime.date``/``datetime.datetime`` (what guessit returns
    for a parsed filename date) as well as a string (what TVDB's ``aired``
    field carries, e.g. ``"2024-05-01"``). Returns ``None`` if ``value`` is
    ``None``, empty, or not a recognizable date.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return None
    return None


def match_by_air_date(
    files_parsed: dict[Any, Any],
    episodes: list[dict[str, Any]],
) -> dict[Any, dict[str, Any]]:
    """Match files to TVDB episodes by air date.

    This is a pure, Qt-free helper so it can be unit-tested without a widget.
    It mirrors ``match_by_absolute`` but keys on air date instead of
    absolute episode number, for daily/date releases (e.g.
    "Show.2024.05.01.mkv") that carry no season/episode component at all.

    Args:
        files_parsed: maps an arbitrary, hashable file identifier (a
            ``Path``, a filename string, a row index, etc. -- the caller
            decides) to that file's parsed date. This is typically
            guessit's ``date`` value, a ``datetime.date`` (or
            ``datetime.datetime``). A value of ``None`` means the file had
            no parseable date and is skipped.
        episodes: the list of TVDB episode dicts to search, each expected
            to carry ``seasonNumber``/``number`` (identifying the episode)
            and an ``aired`` date string (e.g. ``"2024-05-01"``).

    Returns:
        A dict with the same keys as ``files_parsed``, but containing only
        the keys that produced a match, mapped to the matched episode dict
        from ``episodes``. Keys with no parseable date, or whose date
        doesn't match any episode's ``aired`` date, are omitted. Dates are
        normalized (see ``_normalize_air_date``) before comparison so a
        ``datetime.date``/``datetime.datetime`` parsed value compares equal
        to TVDB's ISO date string.
    """
    episodes_by_date: dict[str, dict[str, Any]] = {}
    for episode_data in episodes:
        normalized_aired = _normalize_air_date(episode_data.get("aired"))
        if normalized_aired is None:
            continue
        episodes_by_date.setdefault(normalized_aired, episode_data)

    matches: dict[Any, dict[str, Any]] = {}
    for file_key, parsed_date in files_parsed.items():
        normalized_parsed = _normalize_air_date(parsed_date)
        if normalized_parsed is None:
            continue
        matched_episode = episodes_by_date.get(normalized_parsed)
        if matched_episode is not None:
            matches[file_key] = matched_episode
    return matches


def parse_episode_file(file_path: Path) -> EpisodeData:
    """Parse one input file's season, episode and episode title.

    The filename is parsed on its own, and as an episode, which is what
    every other parse site in the app does. Handing GuessIt the whole
    path instead let the directories above the file compete for the show
    title: for a pack sitting in a folder that carries its own release
    info, GuessIt read the grandparent as the show and the episode title
    came back as the containing directory's name -- the same value for
    every file in the pack. Season and episode were unaffected, so the
    damage was invisible until something read the title, which fuzzy
    matching does for any file the numbers cannot place.

    The full path is still consulted for a season the filename omits,
    because a pack may keep its episodes in ``Season NN`` subfolders with
    bare names like ``ep01.mkv``. Only the season is taken from it.
    """
    try:
        parsed: EpisodeData = dict(guessit(file_path.name, options={"type": "episode"}))
    except Exception:
        parsed = {}

    if parsed.get("season") is None:
        try:
            from_path = dict(guessit(str(file_path), options={"type": "episode"}))
        except Exception:
            from_path = {}
        season = from_path.get("season")
        if season is not None:
            parsed["season"] = season

    return parsed


def coerce_season(value: Any) -> int | None:
    """Return a parsed season number, including GuessIt's list form."""
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, int) else None


def parsed_file_summary(parsed_data: EpisodeData) -> ParsedFile:
    """What one parsed filename claims, for ranking episode orderings."""
    episode = parsed_data.get("episode")
    if isinstance(episode, list):
        episodes = tuple(
            number for number in sorted(episode) if isinstance(number, int)
        )
    elif isinstance(episode, int):
        episodes = (episode,)
    else:
        episodes = ()

    episode_title = parsed_data.get("episode_title")
    if isinstance(episode_title, list):
        episode_title = " ".join(
            value for value in episode_title if isinstance(value, str)
        )
    return ParsedFile(
        season=coerce_season(parsed_data.get("season")),
        episodes=episodes,
        title=episode_title if isinstance(episode_title, str) else None,
    )


def episodes_for_ordering(
    episodes_by_type: dict[Any, EpisodeData], type_id: Any
) -> dict[int, dict[int, EpisodeData]]:
    """One TVDB ordering's episodes, keyed season -> episode number."""
    available: dict[int, dict[int, EpisodeData]] = {}
    if type_id is None or type_id not in episodes_by_type:
        return available
    for episode_data in episodes_by_type[type_id].get("episodes", []):
        season_num = episode_data.get("seasonNumber")
        episode_num = episode_data.get("number")
        if season_num is not None and episode_num is not None:
            available.setdefault(season_num, {})[episode_num] = episode_data
    return available


def _normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching"""
    # remove common video terms and normalize
    text = re.sub(
        r"\b(720p|1080p|hdtv|webrip|bluray|dvdrip|x264|h264|x265|hevc)\b",
        "",
        text.lower(),
    )
    # remove season/episode patterns for fuzzy matching
    text = re.sub(r"\bs\d+e\d+\b", "", text)  # remove S01E01 style
    text = re.sub(r"\bseason\s*\d+\b", "", text)  # remove "season 1" style
    text = re.sub(r"\bepisode\s*\d+\b", "", text)  # remove "episode 1" style
    text = re.sub(r"\b\d+x\d+\b", "", text)  # remove 1x01 style
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text.strip())
    return text


def method_label(base: str, title_check: TitleCheck) -> str:
    """Name the episode a row's own title belongs to, where it differs."""
    if title_check.points_elsewhere:
        return f"{base} (title -> E{title_check.suggested_episode:02d}?)"
    return base


@dataclass(slots=True)
class MatchCounts:
    matched: int = 0
    fuzzy: int = 0


@dataclass
class EpisodeMatcher:
    """Matches a pack's files to a TVDB ordering's episodes.

    Holds everything matching reads -- the episodes, the chosen ordering, the
    release format, the fuzzy settings -- and the mappings it writes, keyed by
    file. The desktop episode mapper keeps one and renders its mappings; a
    headless run builds one from the run's TVDB data and reads them back.
    """

    available_episodes: dict[int, dict[int, EpisodeData]] = field(default_factory=dict)
    """The chosen ordering's episodes, season -> episode number -> data."""
    episodes_by_type: dict[Any, EpisodeData] = field(default_factory=dict)
    """Every TVDB ordering, as `tvdb_data["episodes_by_type"]` holds them."""
    order_type_id: Any | None = None
    series_format: EpisodeFormat = EpisodeFormat.STANDARD
    show_title: str | None = None
    fuzzy_enabled: bool = True
    fuzzy_threshold: float = 75.0
    mappings: dict[Path, EpisodeMapping] = field(default_factory=dict)
    parsed: dict[Path, EpisodeData] = field(default_factory=dict)
    """Each file's GuessIt parse, cached: parsing is slow enough to matter."""

    def parse(self, file_path: Path) -> EpisodeData:
        parsed_data = self.parsed.get(file_path)
        if parsed_data is None:
            parsed_data = parse_episode_file(file_path)
            self.parsed[file_path] = parsed_data
        return parsed_data

    def use_ordering(self, type_id: Any) -> None:
        """Match against another of TVDB's orderings from now on."""
        self.order_type_id = type_id
        self.available_episodes = episodes_for_ordering(self.episodes_by_type, type_id)

    # -- storing ---------------------------------------------------------
    def store_mapping(
        self,
        file_path: Path,
        season: int,
        episode: int,
        episode_data: EpisodeData,
        confidence: float,
        method: str,
        episode_end: int | None = None,
        episode_list: Sequence[int] | None = None,
        episode_order_type_id: Any | None = None,
        verified: bool = True,
        title_check: TitleCheck | None = None,
        episode_title_override: str | None = None,
    ) -> EpisodeMapping:
        """Store file-to-episode mapping, and return the stored row.

        ``episode_end`` carries the last episode number for a file that spans
        multiple episodes (e.g. a single "S01E01E02" file). It is ``None``
        for a normal single-episode mapping.

        ``episode_list`` names every episode the file covers. Callers pass it
        when they parsed one, which is the only way a non-contiguous span
        such as "S01E01E05" can be recorded; otherwise it is derived from
        ``episode`` and ``episode_end``, so every row carries a list and no
        reader has to special-case the single-episode file.

        ``verified`` is False when ``episode_data`` is a synthesized stand-in
        rather than a real episode from the selected ordering -- the filename
        (or the user) named a season/episode TVDB does not list. Readers that
        only need the numbers can ignore it; it exists so the UI can say which
        rows TVDB has confirmed.

        ``episode_order_type_id`` records which TVDB episode ordering
        ``episode_data`` came from. TVDB serves several -- aired, DVD,
        absolute -- and the same (season, episode) pair can name different
        episodes in each, so a later lookup for a *different* episode of the
        same file has to read the same list. ``None`` means the flat
        ``tvdb_data["episodes"]`` list, which is what rows written before
        this field existed mean.
        """
        if episode_list:
            stored_episodes = sorted(episode_list)
        elif episode_end is not None and episode_end > episode:
            stored_episodes = list(range(episode, episode_end + 1))
        else:
            stored_episodes = [episode]

        self.mappings[file_path] = {
            "season": season,
            "episode": episode,
            "episode_end": episode_end,
            "episode_list": stored_episodes,
            "episode_data": episode_data,
            "episode_name": episode_data.get("name", "Unknown"),
            "confidence": confidence,
            "assignment_method": method,
            "episode_order_type_id": episode_order_type_id,
            "verified": verified,
            "title_match_score": title_check.score if title_check else None,
            "episode_title_override": episode_title_override or None,
        }
        return self.mappings[file_path]

    def store_unverified_parse(
        self,
        file_path: Path,
        season: int,
        episode: int,
        episode_end: int | None = None,
        episode_list: Sequence[int] | None = None,
    ) -> EpisodeMapping:
        """Record a parsed season/episode the selected ordering cannot confirm.

        Uses the same synthesized payload the manual-entry path builds for a
        season/episode TVDB has no data for, so a number NfoForge parsed and a
        number the user typed are stored identically and render identically.
        """
        episode_data: EpisodeData = {
            "season": season,
            "episode": episode,
            "name": None,
            "aired": None,
        }
        return self.store_mapping(
            file_path,
            season,
            episode,
            episode_data,
            UNVERIFIED_PARSE_CONFIDENCE,
            UNVERIFIED_PARSE_METHOD,
            episode_end=episode_end,
            episode_list=episode_list,
            episode_order_type_id=self.order_type_id,
            verified=False,
        )

    # -- evidence --------------------------------------------------------
    def title_check_for(self, file_path: Path, season: int, episode: int) -> TitleCheck:
        """Ask a filename's own episode title whether it agrees with the
        episode its number landed on.

        The number matching proves little on its own: every ordering of a
        season has an episode 3, so a pack numbered against one ordering
        binds cleanly to another and renames itself wrong at full
        confidence.
        """
        parsed_data = self.parsed.get(file_path) or {}
        parsed_title = parsed_data.get("episode_title")
        if isinstance(parsed_title, list):
            parsed_title = " ".join(
                value for value in parsed_title if isinstance(value, str)
            )
        return check_title_against_episode(
            parsed_title if isinstance(parsed_title, str) else None,
            self.available_episodes.get(season, {}),
            episode,
        )

    def episode_is_claimed(
        self, season: int, episode: int, claimed_by: Path | None = None
    ) -> bool:
        """Whether another file already covers this episode.

        Matching used to be able to put two files on one episode: a file
        whose number the ordering does not list fell through to fuzzy, which
        has only a title to go on and in a complete pack lands on an episode
        some other file already holds. The pack then failed to validate as
        "not properly mapped", with every row on screen filled in.
        """
        for file_path, mapping in self.mappings.items():
            if file_path == claimed_by:
                continue
            if (season, episode) in claimed_season_episodes(mapping):
                return True
        return False

    def episode_title_candidates(
        self, filename: str, parsed_data: EpisodeData | None
    ) -> list[str]:
        """Strings from one file that might be its episode title.

        GuessIt's own ``episode_title`` is preferred and is passed through
        unaltered, so the comparison sees the title as written -- stripping
        punctuation here would throw away the ampersand in "Lost & Found",
        which the comparison itself knows how to read. The filename-derived
        fallback is for names GuessIt cannot parse, and does need the show
        name and release terms taken off it first.
        """
        candidates: list[str] = []

        if parsed_data:
            parsed_episode_title = parsed_data.get("episode_title")
            if isinstance(parsed_episode_title, list):
                parsed_episode_title = " ".join(
                    value
                    for value in parsed_episode_title
                    if isinstance(value, str) and value.strip()
                )
            if isinstance(parsed_episode_title, str) and parsed_episode_title.strip():
                candidates.append(parsed_episode_title)

        filename_clean = _normalize_text(filename)
        show_name_variations: list[str] = []
        if isinstance(self.show_title, str) and self.show_title.strip():
            show_title = self.show_title.lower()
            show_name_variations.append(_normalize_text(show_title))
            show_title_clean = re.sub(r"[^a-z0-9\s]", " ", show_title)
            show_title_clean = re.sub(r"\s+", " ", show_title_clean.strip())
            if show_title_clean and show_title_clean not in show_name_variations:
                show_name_variations.append(show_title_clean)

        filename_episode_title = filename_clean
        for show_name in show_name_variations:
            if show_name:
                filename_episode_title = filename_episode_title.replace(
                    show_name, ""
                ).strip()

        # remove common technical terms that don't help with episode matching
        filename_episode_title = re.sub(
            r"(web|dl|rip|bluray|dvd|hdtv|mkv|mp4|avi)",
            "",
            filename_episode_title,
        )

        # The group tag survives normalization as a bare word ("-G" -> "g")
        # and counts as part of the title, which is enough to stop a part
        # number being recognised as one.
        release_group = (parsed_data or {}).get("release_group")
        if isinstance(release_group, str) and release_group.strip():
            filename_episode_title = re.sub(
                rf"{re.escape(_normalize_text(release_group))}",
                "",
                filename_episode_title,
            )
        filename_episode_title = re.sub(r"\s+", " ", filename_episode_title.strip())
        if len(filename_episode_title) >= 3:
            candidates.append(filename_episode_title)

        return candidates

    def fuzzy_match_episode_name(
        self,
        filename: str,
        season: int | None = None,
        parsed_data: EpisodeData | None = None,
        claimed_by: Path | None = None,
        min_score: float | None = None,
    ) -> tuple[int, tuple[int, ...], float] | None:
        """Match a file to episodes by title, returning every episode it covers.

        Answers with a tuple of episode numbers rather than one number: a
        provider splits a two-part story into two episodes while a release
        ships it as one file, so a file named after the story matches the
        story. Matching only its first half left the second half with no file
        to give it and no way to say so.

        Episodes another file already covers are excluded before ranking, so
        this cannot manufacture an overlap.
        """
        if not self.fuzzy_enabled:
            return None

        title_candidates = self.episode_title_candidates(filename, parsed_data)
        if not title_candidates:
            return None

        # ``min_score`` raises the bar above the user's general setting for
        # a caller that is overriding harder evidence than a title.
        threshold = float(self.fuzzy_threshold)
        if min_score is not None:
            threshold = max(threshold, min_score)

        # A number parsed with no season beside it is often a part number
        # rather than an episode: "A.Moral.Star.1" is part one of a two-part
        # story, not episode one.
        parsed_episode = (parsed_data or {}).get("episode")
        part_hint = parsed_episode if isinstance(parsed_episode, int) else None

        # identity check, not truthiness -- season 0 is a valid TVDB season
        # (specials), and `season == 0` is falsy in Python.
        seasons_to_search = (
            [season] if season is not None else list(self.available_episodes)
        )

        best: tuple[int, tuple[int, ...], float] | None = None
        for search_season in seasons_to_search:
            season_episodes = self.available_episodes.get(search_season)
            if not season_episodes:
                continue

            already_claimed = {
                number
                for number in season_episodes
                if self.episode_is_claimed(search_season, number, claimed_by)
            }

            for title_candidate in title_candidates:
                ranked = rank_title_candidates(
                    title_candidate,
                    season_episodes,
                    exclude=already_claimed,
                    threshold=threshold,
                    part_hint=part_hint,
                )
                if not ranked:
                    continue
                candidate = ranked[0]
                if best is None or candidate.score > best[2] * 100.0:
                    best = (search_season, candidate.episodes, candidate.score / 100.0)

        return best

    def _store_fuzzy(
        self, file_path: Path, result: tuple[int, tuple[int, ...], float], method: str
    ) -> EpisodeMapping:
        matched_season, matched_episodes, confidence = result
        # A title match can cover a whole multi-part story, so the span is
        # carried through exactly as a parsed "S01E01-E02" would be.
        return self.store_mapping(
            file_path,
            matched_season,
            matched_episodes[0],
            self.available_episodes[matched_season][matched_episodes[0]],
            confidence,
            method,
            episode_end=matched_episodes[-1] if len(matched_episodes) > 1 else None,
            episode_list=list(matched_episodes),
            episode_order_type_id=self.order_type_id,
        )

    # -- orderings -------------------------------------------------------
    def absolute_order_episodes(self) -> tuple[Any | None, list[EpisodeData]]:
        """Return TVDB's "Absolute Order" episode list and its type id.

        This scans all season types rather than only the selected ordering,
        so absolute-number matching keeps working even when another ordering
        is selected while the Anime/Absolute release format is active -- the
        release format only controls title/filename tokens and doesn't change
        which TVDB order is displayed.

        The type id comes back with the list because a mapping stored from
        it did not come from the selected ordering, and the row has to record
        the list it actually used.
        """
        for type_id, type_data in self.episodes_by_type.items():
            order_type = str(type_data.get("type", "")).lower()
            order_name = str(type_data.get("type_name", "")).lower()
            if "absolute" in order_type or "absolute" in order_name:
                episodes = type_data.get("episodes", [])
                if isinstance(episodes, list):
                    return type_id, [
                        dict(episode)
                        for episode in episodes
                        if isinstance(episode, dict)
                    ]
        return None, []

    def available_episodes_flat(self) -> list[EpisodeData]:
        """Every episode of the selected ordering, for matchers that key on a
        field (like ``aired``) rather than the season/episode structure."""
        return [
            episode_data
            for season_episodes in self.available_episodes.values()
            for episode_data in season_episodes.values()
        ]

    # -- matching --------------------------------------------------------
    def match_files(
        self, files: Sequence[Path], preserve_existing: bool = False
    ) -> MatchCounts:
        """Match `files`, in order, storing a mapping for each one placed.

        ``preserve_existing`` leaves files that already carry a mapping
        untouched and matches only the rest, so a correction someone made is
        not recomputed back into the wrong answer.
        """
        counts = MatchCounts()
        if not self.available_episodes:
            return counts

        absolute_type_id, absolute_episodes = (
            self.absolute_order_episodes()
            if self.series_format is EpisodeFormat.ANIME_ABSOLUTE
            else (None, [])
        )
        for file_path in files:
            if preserve_existing and file_path in self.mappings:
                continue
            method = self._match_file(file_path, absolute_type_id, absolute_episodes)
            if method == "fuzzy":
                counts.fuzzy += 1
            elif method:
                counts.matched += 1
        return counts

    def _match_file(
        self,
        file_path: Path,
        absolute_type_id: Any | None,
        absolute_episodes: list[EpisodeData],
    ) -> str | None:
        """Match one file. Returns how it was placed, or None if it was not."""
        parsed_data = self.parse(file_path)

        # stage 1: try regex/guessit parsing (highest confidence)
        season = coerce_season(parsed_data.get("season"))
        episode = parsed_data.get("episode")

        # guessit returns a list of episode numbers for files that span
        # multiple episodes (e.g. "S01E01E02"). keep the lowest as the
        # primary episode and carry the highest as the range end so a
        # single file's multi-episode span isn't collapsed to episode 1.
        # the whole list is kept alongside them: the expand styles name
        # every episode the file holds, and "S01E01E05" is a span whose
        # ends alone describe wrongly.
        episode_end = None
        episode_list: list[int] | None = None
        if isinstance(episode, list):
            if episode:
                sorted_episodes = sorted(episode)
                episode_list = sorted_episodes
                episode, episode_end = sorted_episodes[0], sorted_episodes[-1]
                if episode_end == episode:
                    episode_end = None
            else:
                episode = None

        # identity checks, not truthiness -- TVDB uses season 0 for specials,
        # and `season == 0` is falsy in Python.
        if (
            season is not None
            and episode is not None
            and season in self.available_episodes
            and episode in self.available_episodes[season]
        ):
            title_check = self.title_check_for(file_path, season, episode)
            self.store_mapping(
                file_path,
                season,
                episode,
                self.available_episodes[season][episode],
                0.95,
                method_label("regex", title_check),
                episode_end=episode_end,
                episode_list=episode_list,
                episode_order_type_id=self.order_type_id,
                title_check=title_check,
            )
            return "regex"

        # Stage 1a: the filename states a season and an episode plainly, but
        # the selected ordering has no such episode -- most often because a
        # multi-part premiere is one entry there and two episodes here. Keep
        # what the filename says, flagged as unverified, unless this file's
        # own episode title names an episode the ordering does have: then the
        # title is the better evidence. That bar is deliberately higher than
        # the general fuzzy threshold, because it overrides a stated number.
        if season is not None and episode is not None:
            rescued = self.fuzzy_match_episode_name(
                file_path.stem,
                season=season,
                parsed_data=parsed_data,
                claimed_by=file_path,
                min_score=TITLE_SUGGESTION_FLOOR,
            )
            if rescued is not None:
                self._store_fuzzy(file_path, rescued, "title")
                return "title"

            self.store_unverified_parse(
                file_path,
                season,
                episode,
                episode_end=episode_end,
                episode_list=episode_list,
            )
            return "unverified"

        # stage 1b: anime/absolute-numbered releases (e.g.
        # "[Group] Show - 025.mkv") carry no season, just an absolute episode
        # number. The `season is None` guard is required: a file that DID
        # parse a real season must fall through to fuzzy/unmatched instead of
        # having its episode digit reinterpreted as an absolute number.
        if absolute_episodes and episode is not None and season is None:
            absolute_episode_data = match_by_absolute(
                {file_path: episode}, absolute_episodes
            ).get(file_path)
            if absolute_episode_data is not None:
                matched_season = absolute_episode_data.get("seasonNumber")
                matched_episode = absolute_episode_data.get("number")
                if matched_season is not None and matched_episode is not None:
                    # translate the range end through the same absolute index,
                    # dropping it if it lands in another season. The parsed
                    # list holds absolute numbers, so it is not passed on.
                    matched_episode_end = None
                    if episode_end is not None:
                        end_episode_data = match_by_absolute(
                            {file_path: episode_end}, absolute_episodes
                        ).get(file_path)
                        if end_episode_data is not None:
                            end_number = end_episode_data.get("number")
                            if (
                                end_episode_data.get("seasonNumber") == matched_season
                                and end_number is not None
                            ):
                                matched_episode_end = end_number

                    self.store_mapping(
                        file_path,
                        matched_season,
                        matched_episode,
                        absolute_episode_data,
                        0.9,
                        "absolute",
                        episode_end=matched_episode_end,
                        episode_order_type_id=absolute_type_id,
                    )
                    return "absolute"

        # stage 1c: daily/date releases (e.g. "Show.2024.05.01.mkv") carry
        # only an air date. Guarded like 1b, with identity checks: a genuinely
        # parsed "S00E01" must not be hijacked by date.
        parsed_date = parsed_data.get("date")
        if (
            self.series_format is EpisodeFormat.DAILY_DATE
            and parsed_date is not None
            and season is None
            and episode is None
        ):
            daily_episode_data = match_by_air_date(
                {file_path: parsed_date}, self.available_episodes_flat()
            ).get(file_path)
            if daily_episode_data is not None:
                matched_season = daily_episode_data.get("seasonNumber")
                matched_episode = daily_episode_data.get("number")
                if matched_season is not None and matched_episode is not None:
                    self.store_mapping(
                        file_path,
                        matched_season,
                        matched_episode,
                        daily_episode_data,
                        0.9,
                        "daily",
                        episode_order_type_id=self.order_type_id,
                    )
                    return "daily"

        # stage 2: try fuzzy matching (medium confidence)
        fuzzy_result = self.fuzzy_match_episode_name(
            file_path.stem,
            season=season,
            parsed_data=parsed_data,
            claimed_by=file_path,
        )
        if fuzzy_result:
            self._store_fuzzy(file_path, fuzzy_result, "fuzzy")
            return "fuzzy"
        return None

    def fuzzy_match_file(self, file_path: Path, season: int | None) -> bool:
        """Place one file by its title alone, within `season` when given.

        For a file the numbers could not place. Returns whether it matched.
        """
        parsed_data = self.parse(file_path)
        if season is None:
            season = coerce_season(parsed_data.get("season"))
        result = self.fuzzy_match_episode_name(
            file_path.stem,
            season=season,
            parsed_data=parsed_data,
            claimed_by=file_path,
        )
        if not result:
            return False
        self._store_fuzzy(file_path, result, "fuzzy")
        return True

    def title_disagreements(self) -> tuple[int, int]:
        """How many mapped files were title-checked, and how many disagree.

        Counted from the scores stored on the mappings, so it is equally right
        after an ordering change, which re-resolves mappings in place.
        """
        scores = [
            mapping["title_match_score"]
            for mapping in self.mappings.values()
            if isinstance(mapping.get("title_match_score"), (int, float))
        ]
        return len(scores), sum(
            1 for score in scores if score < TITLE_DISAGREEMENT_FLOOR
        )
