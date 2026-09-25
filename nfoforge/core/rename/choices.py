"""The claims a release's new name is built from, shared by movies and series.

The Rename pages hold these in their combo boxes and let the user change them;
a headless run takes them as detected. Stage 1 (detection) is
`detect_filename_claims`. This is stage 2: the claims the rename actually
uses, and the override tokens they become.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nfoforge.backend.tokens import TokenSelection
from nfoforge.backend.utils.filename_claims import FilenameClaims
from nfoforge.backend.utils.rename_normalizations import (
    EDITION_INFO,
    FRAME_SIZE_INFO,
    LOCALIZATION_INFO,
    RE_RELEASE_INFO,
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
"""The values each choice can take -- what the Rename pages' combos offer."""


@dataclass(slots=True)
class RenameChoices:
    """The claims a release's new name is built from."""

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


def normalize_choices(choices: RenameChoices) -> RenameChoices:
    """Apply the rules between choices: REMUX needs a disc, a service needs web."""
    if choices.quality is not None:
        if choices.quality not in DISC_QUALITIES:
            choices.remux = False
        if choices.quality not in WEB_QUALITIES:
            choices.streaming_service = ""
    return choices


def choices_from_claims(
    claims: FilenameClaims,
    quality: QualitySelection | None,
    context: ProcessingContext,
    settings: AppConfig,
) -> RenameChoices:
    """Turn detected claims into choices, as the Rename pages pre-fill them.

    Only values the pages' combos offer are kept. A plugin-supplied
    localization beats the filename, and is not gated by the claim switches
    (it is evidence from elsewhere). The configured group tag beats the
    detected source group.
    """
    plugin_localization = _offered(
        "localization",
        context.shared_data.dynamic_data.get("localization_override") or "",
    )
    return normalize_choices(
        RenameChoices(
            edition=_offered("edition", claims.edition),
            frame_size=_offered("frame_size", claims.frame_size),
            localization=plugin_localization
            or _offered("localization", claims.localization),
            re_release=_offered("re_release", claims.re_release),
            streaming_service=_offered("streaming_service", claims.streaming_service),
            remux=bool(claims.remux),
            hybrid=bool(claims.hybrid),
            quality=quality,
            release_group=settings.general.release_group or claims.release_group,
        )
    )


def common_value[T](values: Iterable[T]) -> T | None:
    """The one value every item agrees on, or None if they disagree."""
    distinct = set(values)
    return next(iter(distinct)) if len(distinct) == 1 else None


def rename_override_tokens(choices: RenameChoices) -> dict[str, str]:
    """The override tokens a rename renders with.

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


def quality_problem(
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


def record_overrides(
    context: ProcessingContext,
    choices: RenameChoices,
    override_tokens: dict[str, Any],
) -> None:
    """Record the rename's claims on the run, for the NFO and tracker titles."""
    dynamic_data = context.shared_data.dynamic_data
    if choices.edition:
        dynamic_data["edition_override"] = choices.edition
    if choices.frame_size:
        dynamic_data["frame_size_override"] = choices.frame_size
    dynamic_data["override_tokens"] = override_tokens
