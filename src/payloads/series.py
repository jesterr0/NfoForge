import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guessit import guessit

from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.payloads.media_inputs import MediaInputPayload


@dataclass(slots=True)
class SeriesReleaseInfo:
    media_type: MediaType | None
    input_path: Path | None
    primary_file: Path | None
    title_path: Path | None
    season: int | None = None
    episode_start: int | None = None
    episode_end: int | None = None
    episode_count: int = 0
    episode_format: EpisodeFormat = EpisodeFormat.STANDARD

    @property
    def is_series(self) -> bool:
        return self.media_type is MediaType.SERIES

    @property
    def is_pack(self) -> bool:
        return self.is_series and self.episode_count > 1

    @property
    def is_special(self) -> bool:
        return self.is_series and self.season == 0

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
        return path.stem if path and path.suffix else path.name if path else ""

    @property
    def season_tag(self) -> str | None:
        return f"S{self.season:02d}" if self.season is not None else None

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


def build_series_release_info(media_input: MediaInputPayload) -> SeriesReleaseInfo:
    file_list = list(media_input.file_list)
    primary_file = file_list[0] if file_list else media_input.input_path
    mappings = media_input.series_episode_map or {}

    seasons: list[int] = []
    episodes: list[int] = []
    for file_path in file_list:
        mapping = _mapping_for_path(file_path, mappings)
        season = _int_or_none(mapping.get("season")) if mapping else None
        episode = _int_or_none(mapping.get("episode")) if mapping else None
        if season is not None:
            seasons.append(season)
        if episode is not None:
            episodes.append(episode)

    if not seasons or not episodes:
        for file_path in file_list or ([primary_file] if primary_file else []):
            parsed = guessit(file_path.name, options={"type": "episode"})
            season = _int_or_none(parsed.get("season"))
            episode = _episode_number(parsed.get("episode"))
            if season is not None:
                seasons.append(season)
            if episode is not None:
                episodes.append(episode)

    season = min(seasons) if seasons else None
    episode_start = min(episodes) if episodes else None
    episode_end = max(episodes) if episodes else None
    episode_count = max(len(file_list), len(mappings), len(episodes))

    return SeriesReleaseInfo(
        media_type=media_input.media_type,
        input_path=media_input.input_path,
        primary_file=primary_file,
        title_path=media_input.input_path if episode_count > 1 else primary_file,
        season=season,
        episode_start=episode_start,
        episode_end=episode_end,
        episode_count=episode_count,
        episode_format=media_input.series_episode_format,
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


def _episode_number(value: Any) -> int | None:
    if isinstance(value, list | tuple):
        value = value[0] if value else None
    return _int_or_none(value)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
