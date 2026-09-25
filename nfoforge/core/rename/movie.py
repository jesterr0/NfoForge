"""Renaming a movie: the choices, the name they produce, and what gets renamed.

The desktop Rename page holds these choices in its combo boxes and lets the
user change them. A headless run takes them as detected. Both go through
here, so the pre-fill, the tokens it produces and the rules a name has to meet
are the same either way.

Stage 1 (detection) comes from `detect_filename_claims`. This module is
stage 2: the claims the rename actually uses, as override tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import TYPE_CHECKING

from nfoforge.backend.rename_encode import RenameEncodeBackEnd
from nfoforge.backend.tokens import TokenSelection
from nfoforge.backend.utils.filename_claims import detect_filename_claims
from nfoforge.backend.utils.rename_normalizations import (
    EDITION_INFO,
    FRAME_SIZE_INFO,
    LOCALIZATION_INFO,
    RE_RELEASE_INFO,
    is_imax,
)
from nfoforge.backend.utils.resolution import VideoResolutionAnalyzer
from nfoforge.backend.utils.streaming_services import STREAMING_SERVICE_CHOICES
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.rename import QualitySelection
from nfoforge.payloads.media_inputs import MediaInputPayload

if TYPE_CHECKING:
    from nfoforge.config.models import AppConfig

DISC_QUALITIES = frozenset(
    {QualitySelection.DVD, QualitySelection.BLURAY, QualitySelection.UHD_BLURAY}
)
"""Only a disc source can be a REMUX."""

WEB_QUALITIES = frozenset({QualitySelection.WEB_DL, QualitySelection.WEB_RIP})
"""Only a web source can carry a streaming service."""

_SD_QUALITIES = frozenset({QualitySelection.DVD, QualitySelection.SDTV})

_OFFERED = {
    "edition": {item.normalized for item in EDITION_INFO},
    "frame_size": {item.normalized for item in FRAME_SIZE_INFO},
    "localization": {item.normalized for item in LOCALIZATION_INFO},
    "re_release": {item.normalized for item in RE_RELEASE_INFO},
    "streaming_service": set(STREAMING_SERVICE_CHOICES),
}
"""The values each choice can take -- what the Rename page's combos offer."""


@dataclass(slots=True)
class MovieRenameChoices:
    """The claims a movie's new name is built from."""

    edition: str = ""
    frame_size: str = ""
    localization: str = ""
    re_release: str = ""
    streaming_service: str = ""
    remux: bool = False
    hybrid: bool = False
    quality: QualitySelection | None = None
    release_group: str = ""
    """Blank is a decision: this release carries no group."""
    repack_reason: str = ""
    proper_reason: str = ""


def _offered(field: str, value: str) -> str:
    return value if value in _OFFERED[field] else ""


def normalize_choices(choices: MovieRenameChoices) -> MovieRenameChoices:
    """Apply the rules between choices: REMUX needs a disc, a service needs web."""
    if choices.quality is not None:
        if choices.quality not in DISC_QUALITIES:
            choices.remux = False
        if choices.quality not in WEB_QUALITIES:
            choices.streaming_service = ""
    return choices


def detect_movie_choices(
    context: ProcessingContext, settings: AppConfig
) -> MovieRenameChoices:
    """What the Rename page pre-fills, without the page.

    The claims come from the film's own filename -- index 0 of the file list,
    not the whole list, which can include extras that would outvote it. A
    plugin-supplied localization beats the filename, and is not gated by the
    claim switches (it is evidence from elsewhere). The configured group tag
    beats the detected source group.
    """
    media_file = context.media_input.file_list[0]
    claims = detect_filename_claims(
        [media_file.stem], settings.movie.claims, context.custom_edition_info
    )
    pair = context.media_input.comparison_pair
    plugin_localization = _offered(
        "localization",
        context.shared_data.dynamic_data.get("localization_override") or "",
    )
    return normalize_choices(
        MovieRenameChoices(
            edition=_offered("edition", claims.edition),
            frame_size=_offered("frame_size", claims.frame_size),
            localization=plugin_localization
            or _offered("localization", claims.localization),
            re_release=_offered("re_release", claims.re_release),
            streaming_service=_offered("streaming_service", claims.streaming_service),
            remux=bool(claims.remux),
            hybrid=bool(claims.hybrid),
            quality=RenameEncodeBackEnd.get_quality(
                media_input=media_file, source_input=pair.source if pair else None
            ),
            release_group=settings.general.release_group or claims.release_group,
        )
    )


def movie_override_tokens(choices: MovieRenameChoices) -> dict[str, str]:
    """The override tokens the rename renders with.

    An empty choice is left out, so the token falls back to its own reading;
    `release_group` is always present, because a blank group is a decision.
    """
    tokens = {
        "edition": choices.edition.strip(),
        "frame_size": choices.frame_size,
        "localization": choices.localization,
        "re_release": choices.re_release,
        "streaming_service": choices.streaming_service,
        "source": str(choices.quality) if choices.quality else "",
        "remux": "REMUX" if choices.remux else "",
        "hybrid": "HYBRID" if choices.hybrid else "",
    }
    result = {name: value for name, value in tokens.items() if value}
    result["release_group"] = choices.release_group.strip()
    return result


def file_user_tokens(settings: AppConfig) -> dict[str, str]:
    """The user-defined tokens that apply to filenames."""
    return {
        name: value
        for name, (value, kind) in settings.user_tokens.tokens.items()
        if TokenSelection(kind) is TokenSelection.FILE_TOKEN
    }


def render_movie_name(
    context: ProcessingContext,
    settings: AppConfig,
    backend: RenameEncodeBackEnd,
    token: str | None = None,
) -> Path | None:
    """The new filename (with extension), from `backend.override_tokens`.

    `token` replaces the profile's filename template when given.
    """
    return backend.media_renamer(
        media_input_obj=context.media_input,
        mvr_token=token if token is not None else settings.movie.filename_token,
        mvr_colon_replacement=settings.movie.filename_colon_replace,
        media_search_payload=context.media_search,
        title_clean_rules=settings.global_management.title_clean_rules,
        video_dynamic_range=settings.global_management.video_dynamic_range,
        user_tokens=file_user_tokens(settings),
    )


def movie_name_problems(output_name: str, media_file: Path) -> list[str]:
    """Reasons `output_name` cannot be used as the movie's new name."""
    if not output_name:
        return [
            "The generated filename is empty. Choose a token template that "
            "produces a filename before continuing."
        ]
    if not media_file.suffix:
        return ["The input media has no file extension to preserve."]

    lowered = output_name.lower()
    problems: list[str] = []
    if "subbed" in lowered and "dubbed" in lowered:
        problems.append("Both 'Subbed' and 'Dubbed' should not be used together.")
    if is_imax(lowered) and re.search(r"open[\s|\.]*matte", lowered, flags=re.I):
        problems.append("Both 'IMAX' and 'Open Matte' should not be used together.")
    return problems


def movie_quality_problem(
    quality: QualitySelection | None, media_input: MediaInputPayload
) -> str | None:
    """Why `quality` cannot describe this release, or None if it can.

    DVD and SDTV are standard definition, so a release above 576p cannot be
    either. Raises `FileNotFoundError` when the release's MediaInfo is missing.
    """
    if quality not in _SD_QUALITIES:
        return None
    first_file = media_input.require_first_file()
    mediainfo = (
        media_input.file_list_mediainfo.get(first_file)
        if media_input.file_list_mediainfo
        else None
    )
    if not mediainfo:
        raise FileNotFoundError("Failed to parse MediaInfo")
    resolution = VideoResolutionAnalyzer(mediainfo).get_resolution(remove_scan=True)
    if resolution and int(resolution) > 576:
        return f"Cannot utilize quality {quality} with a resolution above 576p."
    return None


def movie_rename_map(
    media_input: MediaInputPayload, output_name: str
) -> dict[Path, Path]:
    """What renaming the movie to `output_name` moves, leaving out no-ops.

    A folder input holding the film directly is renamed to match it too.
    """
    media_file = media_input.file_list[0]
    target = media_file.parent / f"{output_name}{media_file.suffix}"
    input_path = media_input.input_path
    if input_path and input_path.is_dir() and media_file.parent == input_path:
        target = input_path.parent / output_name / f"{output_name}{media_file.suffix}"
    if str(media_file.absolute()) == str(target.absolute()):
        return {}
    return {media_file: target}


def commit_movie_rename(
    context: ProcessingContext,
    choices: MovieRenameChoices,
    override_tokens: dict[str, str],
    output_name: str,
) -> None:
    """Record the rename's decisions on the run for the NFO and titles.

    Repack and proper reasons become NFO template globals, along with the
    repack/proper number read out of the final name.
    """
    dynamic_data = context.shared_data.dynamic_data
    if choices.edition:
        dynamic_data["edition_override"] = choices.edition
    if choices.frame_size:
        dynamic_data["frame_size_override"] = choices.frame_size
    dynamic_data["override_tokens"] = override_tokens

    for name, reason, pattern in (
        ("repack", choices.repack_reason, r"(repack\d*)"),
        ("proper", choices.proper_reason, r"(proper\d*)"),
    ):
        if not reason:
            continue
        context.jinja_engine.add_global(f"{name}_reason", reason, True)
        match = re.search(pattern, output_name, flags=re.I)
        if match:
            context.jinja_engine.add_global(f"{name}_n", match.group(1), True)
        # only one of the two applies to a release
        break
