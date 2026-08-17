from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from guessit import guessit

from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.payloads.media_inputs import MediaInputPayload


def format_multi_season_range(season: int, season_end: int) -> str:
    """Render a multi-season numeric range as "01-S05" (no leading "S" on
    the start season).

    Shared by ``SeriesReleaseInfo.season_tag`` (which prepends its own
    leading "S") and ``TokenReplacer._season_number`` (whose token template
    supplies the leading "S" itself, e.g. ``S{season_number|zfill(2)}``) so
    the two independent call sites can't drift apart on how a season range
    is padded/joined.
    """
    return f"{season:02d}-S{season_end:02d}"


@dataclass(slots=True)
class SeriesReleaseInfo:
    media_type: MediaType | None
    input_path: Path | None
    primary_file: Path | None
    title_path: Path | None
    season: int | None = None
    season_end: int | None = None
    episode_start: int | None = None
    episode_end: int | None = None
    episode_count: int = 0
    episode_format: EpisodeFormat = EpisodeFormat.STANDARD
    input_is_directory: bool = False

    @property
    def is_series(self) -> bool:
        return self.media_type is MediaType.SERIES

    @property
    def is_pack(self) -> bool:
        return self.is_series and self.episode_count > 1

    @property
    def is_special(self) -> bool:
        # a pack is only "special" when EVERY season in it is season 0 (a
        # pure specials pack); a mixed pack containing season 0 alongside
        # real seasons (season == 0 via min()) must not be flagged special.
        return self.is_series and self.season == 0 and self.season_end in (0, None)

    @property
    def is_hd(self) -> bool:
        name = self.search_name.lower()
        return bool(re.search(r"\b(?:7[0-9]{2}p|1080[pi]|2160p|4320p)\b", name))

    @property
    def search_path(self) -> Path | None:
        if self.is_pack:
            return self.input_path or self.title_path or self.primary_file
        return self.title_path or self.primary_file or self.input_path

    @property
    def search_name(self) -> str:
        path = self.search_path
        if not path:
            return ""
        if self.is_pack and self.input_is_directory:
            return path.name
        return path.stem if path.suffix else path.name

    @property
    def season_tag(self) -> str | None:
        if self.season is None:
            return None
        if self.season_end is not None and self.season_end != self.season:
            return f"S{format_multi_season_range(self.season, self.season_end)}"
        return f"S{self.season:02d}"

    @property
    def episode_tag(self) -> str | None:
        if self.episode_start is None:
            return None
        if self.episode_end is not None and self.episode_end != self.episode_start:
            return f"E{self.episode_start:02d}-E{self.episode_end:02d}"
        return f"E{self.episode_start:02d}"

    @property
    def display_tag(self) -> str:
        if self.season_tag and self.episode_tag and not self.is_pack:
            return f"{self.season_tag}{self.episode_tag}"
        if self.season_tag:
            return self.season_tag
        return ""

    def missing_upload_fields(self) -> tuple[str, ...]:
        """Season/episode values a series release needs but couldn't resolve.

        A pack needs only a season -- UNIT3D expresses a pack as episode 0 (see
        ``Unit3dBaseUploader._build_upload_payload``), so its episode number is
        never in question. A single episode needs both, and without them the
        release is broken well beyond the upload payload: ``season_tag`` and
        ``episode_tag`` return ``None``, ``display_tag`` collapses to ``""``,
        and the season-folder rename is skipped.
        """
        if not self.is_series:
            return ()
        missing: list[str] = []
        if self.season is None:
            missing.append("season")
        if not self.is_pack and self.episode_start is None:
            missing.append("episode")
        return tuple(missing)


def build_series_release_info(media_input: MediaInputPayload) -> SeriesReleaseInfo:
    file_list = list(media_input.file_list)
    primary_file = file_list[0] if file_list else media_input.input_path
    mappings = media_input.series_episode_map or {}

    seasons: list[int] = []
    episode_starts: list[int] = []
    # per-file episode end (defaults to that file's episode_start when the
    # file only covers a single episode) so a lone file spanning multiple
    # episodes (e.g. "S01E01E02") still contributes its true upper bound.
    episode_ends: list[int] = []
    for file_path in file_list:
        mapping = _mapping_for_path(file_path, mappings)
        season = _int_or_none(mapping.get("season")) if mapping else None
        episode = _int_or_none(mapping.get("episode")) if mapping else None
        episode_end = _int_or_none(mapping.get("episode_end")) if mapping else None
        if season is not None:
            seasons.append(season)
        if episode is not None:
            episode_starts.append(episode)
            episode_ends.append(episode_end if episode_end is not None else episode)

    # backfill each dimension independently: a partially mapped set (say every
    # file has a season but none has an episode) must not have guessit's
    # seasons appended on top of the mapped ones, which would widen season_end
    # with values the user never chose.
    need_seasons = not seasons
    need_episodes = not episode_starts
    if need_seasons or need_episodes:
        for file_path in file_list or ([primary_file] if primary_file else []):
            parsed = guessit(file_path.name, options={"type": "episode"})
            if need_seasons:
                season = _fallback_season(file_path.name, parsed.get("season"))
                if season is not None:
                    seasons.append(season)
            if need_episodes:
                episode_start, episode_end = _episode_range(parsed.get("episode"))
                if episode_start is not None:
                    episode_starts.append(episode_start)
                    episode_ends.append(
                        episode_end if episode_end is not None else episode_start
                    )

    season = min(seasons) if seasons else None
    season_end = max(seasons) if seasons else None
    episode_start = min(episode_starts) if episode_starts else None
    episode_end = max(episode_ends) if episode_ends else None
    episode_count = max(len(file_list), len(mappings), len(episode_starts))

    return SeriesReleaseInfo(
        media_type=media_input.media_type,
        input_path=media_input.input_path,
        primary_file=primary_file,
        title_path=media_input.input_path if episode_count > 1 else primary_file,
        season=season,
        season_end=season_end,
        episode_start=episode_start,
        episode_end=episode_end,
        episode_count=episode_count,
        episode_format=media_input.series_episode_format,
        input_is_directory=media_input.input_is_directory(),
    )


def describe_missing_upload_fields(release_info: SeriesReleaseInfo) -> str | None:
    """User-facing message for an unresolvable season/episode, or ``None``.

    Shared by the Series Match wizard page and the backend upload guard so the
    two can't drift on how the problem is explained.
    """
    missing = release_info.missing_upload_fields()
    if not missing:
        return None
    fields = " and ".join(f"{field} number" for field in missing)
    return (
        f"Could not determine the {fields} for this release, and trackers "
        "require it. Enter the missing value for each file on the Series "
        "Match page -- filenames using absolute episode numbering (e.g. "
        '"Anime Title - 087") or an air date instead of SxxExx can\'t be '
        "read automatically."
    )


def _mapping_for_path(
    file_path: Path, mappings: dict[Any, dict[str, Any]]
) -> dict[str, Any]:
    if file_path in mappings:
        return mappings[file_path]
    file_path_str = str(file_path)
    if file_path_str in mappings:
        return mappings[file_path_str]
    for key, value in mappings.items():
        if str(key) == file_path_str or getattr(key, "name", None) == file_path.name:
            return value
    return {}


_SPECIALS_MARKER_RE = re.compile(
    r"(?i)(?:\bs00\b|\bs00e\d|season[ ._-]*0(?!\d)|\bspecials?\b)"
)


def _fallback_season(file_name: str, value: Any) -> int | None:
    """Season recovered from a filename, rejecting guessit's phantom season 0.

    guessit reads the leading digit of an absolute episode number as a season,
    so "Anime.Title.-.087.1080p..." parses as season 0 / episode 87. Season 0
    means specials both to UNIT3D (which renders it as "Special {episode}") and
    to ``SeriesReleaseInfo.is_special``, so taking guessit at its word would
    silently mis-categorize absolute-numbered anime instead of failing loudly.
    Only trust a 0 when the filename actually names a specials season -- a real
    "Show.S00E03" or "Show.Season.0" release still resolves to 0.
    """
    season = _int_or_none(value)
    if season == 0 and not _SPECIALS_MARKER_RE.search(file_name):
        return None
    return season


def _episode_range(value: Any) -> tuple[int | None, int | None]:
    """Resolve guessit's episode value to (start, end).

    guessit returns a list of episode numbers for a single file that spans
    multiple episodes (e.g. "S01E01E02" -> [1, 2]); a plain int otherwise.
    """
    if isinstance(value, list | tuple):
        values = [v for v in (_int_or_none(v) for v in value) if v is not None]
        if not values:
            return None, None
        return min(values), max(values)
    episode = _int_or_none(value)
    return episode, episode


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
