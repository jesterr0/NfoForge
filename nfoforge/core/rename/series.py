"""Renaming a series pack: its choices, each episode's claims, and the targets.

A pack has two surfaces. The pack's choices are what every episode agrees on
-- a claim one episode lacks is not the release's claim -- and each episode
also carries its own claims, from its own filename. Episodes are renamed from
their own claims; the pack's choices become the override tokens. The shared
parts live in `choices`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from nfoforge.backend.rename_encode_series import RenameEncodeSeriesBackEnd
from nfoforge.backend.utils.filename_claims import (
    FilenameClaims,
    detect_file_claims,
    detect_filename_claims,
    resolve_file_claims,
)
from nfoforge.backend.utils.media_files import find_sidecars_for
from nfoforge.config.tv_tokens import (
    get_tvr_episode_token,
    resolve_season_subfolder_token,
)
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.rename.choices import (
    RenameChoices,
    choices_from_claims,
    common_value,
    file_user_tokens,
    record_overrides,
)
from nfoforge.payloads.series import build_series_release_info

if TYPE_CHECKING:
    from nfoforge.config.models import AppConfig

type EpisodeClaims = Callable[[Path], dict[str, str]]
"""One episode's resolved claims, as `resolve_file_claims` produces them."""


class SeriesRenameError(ValueError):
    """The pack cannot be renamed as it stands."""


class SeriesNotMappedError(SeriesRenameError):
    """No file has been matched to an episode yet."""


class NoEpisodeNamesError(SeriesRenameError):
    """The template produced a name for none of the episodes."""


@dataclass(slots=True)
class SeriesRenameTargets:
    """What renaming a pack moves. No-op moves are left out."""

    files: dict[Path, Path] = field(default_factory=dict)
    directories: dict[Path, Path] = field(default_factory=dict)
    failed: list[Path] = field(default_factory=list)
    """Episodes no name could be generated for; they are left as they are."""

    @property
    def is_empty(self) -> bool:
        return not self.files and not self.directories


def detect_series_choices(
    context: ProcessingContext, settings: AppConfig
) -> RenameChoices:
    """What the series Rename page pre-fills, without the page.

    A claim or quality is the pack's only when every episode agrees on it.
    """
    media_files = context.media_input.file_list
    if not media_files:
        raise SeriesRenameError("No files found in media input payload")
    claims = detect_filename_claims(
        [Path(path).stem for path in media_files],
        settings.series.claims,
        context.custom_edition_info,
    )
    pair = context.media_input.comparison_pair
    quality = common_value(
        RenameEncodeSeriesBackEnd.get_quality(
            media_input=Path(media_file),
            source_input=pair.source if pair else None,
        )
        for media_file in media_files
    )
    return choices_from_claims(claims, quality, context, settings)


def episode_token(context: ProcessingContext, settings: AppConfig) -> str:
    """The configured filename template for this pack's episode format."""
    return get_tvr_episode_token(
        settings.series, context.media_input.series_episode_format
    )


def detect_episode_claims(
    context: ProcessingContext, settings: AppConfig
) -> list[tuple[Path, FilenameClaims]]:
    """Each mapped episode with the claims its own filename carries.

    Ordered by season then episode rather than by however the files came off
    disk: at several hundred rows across several seasons, filesystem order is
    not how anyone reads a pack.
    """
    episode_map = context.media_input.series_episode_map or {}
    ordered = sorted(
        episode_map.items(),
        key=lambda item: (
            item[1].get("season") or 0,
            item[1].get("episode") or 0,
            item[0].name,
        ),
    )
    return [
        (
            media_file,
            detect_file_claims(
                media_file.stem,
                settings.series.claims,
                context.custom_edition_info,
            ),
        )
        for media_file, _ in ordered
    ]


def detected_episode_claims(
    context: ProcessingContext, settings: AppConfig
) -> EpisodeClaims:
    """Each episode's claims exactly as detected, with nobody editing them."""
    resolved = {
        media_file: resolve_file_claims(claims, {})
        for media_file, claims in detect_episode_claims(context, settings)
    }
    return lambda media_file: resolved.get(media_file, {})


def _folder_name(
    context: ProcessingContext,
    settings: AppConfig,
    backend: RenameEncodeSeriesBackEnd,
    folder_token: str,
    season: int,
    season_end: int | None,
) -> str:
    folder_path = backend.series_folder_renamer(
        media_input_obj=context.media_input,
        token=folder_token,
        colon_replacement=settings.series.filename_colon_replace,
        media_search_payload=context.media_search,
        title_clean_rules=settings.global_management.title_clean_rules,
        video_dynamic_range=settings.global_management.video_dynamic_range,
        user_tokens=file_user_tokens(settings),
        season_num=season,
        season_end=season_end,
    )
    return folder_path.name if folder_path else ""


def pack_folder_name(
    context: ProcessingContext,
    settings: AppConfig,
    backend: RenameEncodeSeriesBackEnd,
) -> str | None:
    """The name the opened folder is renamed to, or None without a season.

    A pack spanning several seasons renders its {season_number} as a range
    (S01-S05).
    """
    release_info = build_series_release_info(context.media_input)
    if release_info.season is None:
        return None
    return _folder_name(
        context,
        settings,
        backend,
        settings.series.season_folder_token,
        release_info.season,
        release_info.season_end,
    )


def build_series_rename(
    context: ProcessingContext,
    settings: AppConfig,
    backend: RenameEncodeSeriesBackEnd,
    *,
    token: str,
    episode_claims: EpisodeClaims,
) -> SeriesRenameTargets:
    """Every file and folder renaming the pack moves.

    Each mapped episode is rendered from `token` with its own claims, and
    `backend.override_tokens` for the pack's. Subtitles and per-episode .nfo
    files follow their episode. The opened folder is renamed to the pack's
    name and each season subfolder to its own season's.

    Raises `SeriesNotMappedError` when no episode is mapped, and
    `NoEpisodeNamesError` when no episode could have a name generated.
    """
    media_input = context.media_input
    episode_map = media_input.series_episode_map
    if not episode_map:
        raise SeriesNotMappedError(
            "No episode mappings were found. Please return to the Series Match "
            "page and map each file to an episode."
        )

    series = settings.series
    global_management = settings.global_management
    user_tokens = file_user_tokens(settings)

    targets = SeriesRenameTargets()
    rename_map: dict[Path, Path] = {}
    for media_file, media_data in episode_map.items():
        renamed_file = backend.series_renamer(
            media_input_obj=media_input,
            media_file=media_file,
            file_claims=episode_claims(media_file),
            token=token,
            colon_replacement=series.filename_colon_replace,
            media_search_payload=context.media_search,
            title_clean_rules=global_management.title_clean_rules,
            video_dynamic_range=global_management.video_dynamic_range,
            user_tokens=user_tokens,
            season_num=media_data["season"],
            episode_num=media_data["episode"],
            episode_format=media_input.series_episode_format,
            multi_episode_style=series.multi_episode_style,
            # each renamed file belongs to exactly one season, so season_end
            # matches season_num here (single-season, unchanged rendering);
            # the multi-season {season_number} range only applies to the
            # aggregate release title/NFO (see ProcessBackEnd).
            season_end=media_data["season"],
        )
        if not renamed_file:
            targets.failed.append(media_file)
            continue
        rename_map[media_file] = (
            media_file.parent / f"{renamed_file.stem}{media_file.suffix}"
        )

    if not rename_map:
        names = "\n".join(f"  {path.name}" for path in targets.failed)
        raise NoEpisodeNamesError(
            "No filenames could be generated from the current token template. "
            f"Nothing was renamed.\n\n{names}"
        )

    # Subtitles and per-episode .nfo files are named after the episode they
    # belong to, so they have to follow it -- otherwise the rename silently
    # separates a pair the release depends on.
    for media_file, sidecars in find_sidecars_for(rename_map).items():
        renamed_output = rename_map[media_file]
        for sidecar, suffix in sidecars.items():
            rename_map[sidecar] = (
                renamed_output.parent / f"{renamed_output.stem}{suffix}"
            )

    # Rename the opened folder to a pack name, and each season subfolder
    # within it to its own season's name. A pack spanning several seasons
    # renders the root's {season_number} as a range (S01-S05); each season
    # subfolder renders its own single season.
    release_info = build_series_release_info(media_input)
    file_seasons = {
        media_file: media_data["season"]
        for media_file, media_data in episode_map.items()
        if media_data.get("season") is not None
    }

    root_folder_name = pack_folder_name(context, settings, backend) or ""
    season_folder_names: dict[int, str] = {}
    if release_info.season is not None:
        subfolder_token = resolve_season_subfolder_token(
            series.season_subfolder_token, series.season_folder_token
        )
        for season in sorted(set(file_seasons.values())):
            name = _folder_name(
                context, settings, backend, subfolder_token, season, season
            )
            if name:
                season_folder_names[season] = name

    rename_map, directory_targets = backend.build_pack_rename_targets(
        input_path=media_input.input_path,
        rename_map=rename_map,
        file_seasons=file_seasons,
        root_folder_name=root_folder_name,
        season_folder_names=season_folder_names,
    )
    targets.files = {
        src: trg
        for src, trg in rename_map.items()
        if str(src.absolute()) != str(trg.absolute())
    }
    targets.directories = {
        src: trg
        for src, trg in directory_targets.items()
        if str(src.absolute()) != str(trg.absolute())
    }
    return targets


def commit_series_rename(
    context: ProcessingContext,
    choices: RenameChoices,
    override_tokens: dict[str, str],
) -> None:
    """Record the rename's decisions on the run for the NFO and titles.

    A pack has no single filename to read a repack number from, so the
    repack/proper pattern is recorded instead, for each episode's to match.
    """
    record_overrides(context, choices, override_tokens)
    for name, reason, pattern in (
        ("repack", choices.repack_reason, r"(repack\d*)"),
        ("proper", choices.proper_reason, r"(proper\d*)"),
    ):
        if not reason:
            continue
        context.jinja_engine.add_global(f"{name}_reason", reason, True)
        context.jinja_engine.add_global(f"{name}_pattern", pattern, True)
        # only one of the two applies to a release
        break
