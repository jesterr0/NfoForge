"""Renaming a movie: its choices, the name they produce, and what gets renamed.

A movie is renamed from its own file -- index 0 of the file list, which is the
film; the rest can be extras. The shared parts live in `choices`.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING

from nfoforge.backend.rename_encode import RenameEncodeBackEnd
from nfoforge.backend.rename_files import RenamePlan
from nfoforge.backend.utils.filename_claims import detect_filename_claims
from nfoforge.backend.utils.rename_normalizations import is_imax
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.disc import DiscType, detect_region, disc_quality
from nfoforge.core.rename.choices import (
    RenameChoices,
    choices_from_claims,
    file_user_tokens,
    record_overrides,
)
from nfoforge.payloads.media_inputs import MediaInputPayload

if TYPE_CHECKING:
    from nfoforge.config.models import AppConfig


def detect_movie_choices(
    context: ProcessingContext, settings: AppConfig
) -> RenameChoices:
    """What the movie Rename page pre-fills, without the page.

    The claims come from the film's own filename, not the whole file list,
    which can include extras that would outvote it.
    """
    media_input = context.media_input
    # a disc is named by its folder, not by the clip standing in for it
    name_path = media_input.release_name_path() or media_input.file_list[0]
    claims = detect_filename_claims(
        [media_input.release_name()],
        settings.movie.claims,
        context.custom_edition_info,
    )
    if media_input.is_disc():
        return _disc_choices(context, settings)
    pair = media_input.comparison_pair
    quality = RenameEncodeBackEnd.get_quality(
        media_input=name_path, source_input=pair.source if pair else None
    )
    return choices_from_claims(claims, quality, context, settings)


def _disc_choices(context: ProcessingContext, settings: AppConfig) -> RenameChoices:
    """A full disc's choices: read off the disc, never off a clip.

    The source is the medium itself, and an untouched disc is never a REMUX,
    a HYBRID, a web release or a re-framed one, whatever its folder says.
    """
    media_input = context.media_input
    disc = media_input.discs[0]
    primary = media_input.primary_media_file()
    mediainfo = media_input.file_list_mediainfo.get(primary) if primary else None
    claims = detect_filename_claims(
        [media_input.release_name()],
        settings.movie.claims,
        context.custom_edition_info,
    )
    choices = choices_from_claims(
        claims, disc_quality(disc, mediainfo), context, settings
    )
    choices.remux = choices.hybrid = False
    choices.frame_size = choices.localization = choices.streaming_service = ""
    choices.region = detect_region(disc, media_input.release_name())
    return choices


def default_name_token(settings: AppConfig, media_input: MediaInputPayload) -> str:
    """The template a release is named with when none is given.

    A disc has its own, by type: it is named as the medium, not as a file.
    """
    if media_input.is_disc():
        if media_input.discs[0].disc_type is DiscType.DVD:
            return settings.disc.dvd_name_token
        return settings.disc.bluray_name_token
    return settings.movie.filename_token


def render_movie_name(
    context: ProcessingContext,
    settings: AppConfig,
    backend: RenameEncodeBackEnd,
    token: str | None = None,
) -> Path | None:
    """The new filename (with extension), from `backend.override_tokens`.

    `token` replaces the profile's template when given; otherwise a disc
    uses its disc template (`default_name_token`).
    """
    return backend.media_renamer(
        media_input_obj=context.media_input,
        mvr_token=token
        if token is not None
        else default_name_token(settings, context.media_input),
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


def movie_rename_map(
    media_input: MediaInputPayload, output_name: str
) -> dict[Path, Path]:
    """What renaming the movie to `output_name` moves, leaving out no-ops.

    A folder input holding the film directly is renamed to match it too.
    Nothing inside a disc is ever moved: renaming a clip breaks the disc.
    """
    if media_input.is_disc():
        return {}
    media_file = media_input.file_list[0]
    target = media_file.parent / f"{output_name}{media_file.suffix}"
    input_path = media_input.input_path
    if input_path and input_path.is_dir() and media_file.parent == input_path:
        target = input_path.parent / output_name / f"{output_name}{media_file.suffix}"
    if str(media_file.absolute()) == str(target.absolute()):
        return {}
    return {media_file: target}


def disc_rename_plan(
    media_input: MediaInputPayload, output_name: str
) -> RenamePlan | None:
    """The one rename a disc allows: its root folder, or its image file.

    An image keeps its `.iso`. None when the release is not a disc or it
    already has that name. An image has to be unmounted before the plan runs
    (`MediaInputPayload.unmount_disc_images`); it is mounted again on demand.
    """
    root = media_input.input_path
    if not media_input.is_disc() or root is None or not output_name:
        return None
    image = media_input.discs[0].is_image
    target = root.parent / (f"{output_name}{root.suffix}" if image else output_name)
    if str(root.absolute()) == str(target.absolute()):
        return None
    if image:
        return RenamePlan.build({root: target}, root)
    return RenamePlan.build({}, root, directory_targets={root: target})


def commit_movie_rename(
    context: ProcessingContext,
    choices: RenameChoices,
    override_tokens: dict[str, str],
    output_name: str,
) -> None:
    """Record the rename's decisions on the run for the NFO and titles.

    Repack and proper reasons become NFO template globals, along with the
    repack/proper number read out of the final name.
    """
    record_overrides(context, choices, override_tokens)
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
