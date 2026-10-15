"""Renaming a movie: its choices, the name they produce, and what gets renamed.

A movie is renamed from its own file -- index 0 of the file list, which is the
film; the rest can be extras. The shared parts live in `choices`.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING

from nfoforge.backend.rename_encode import RenameEncodeBackEnd
from nfoforge.backend.utils.filename_claims import detect_filename_claims
from nfoforge.backend.utils.rename_normalizations import is_imax
from nfoforge.context.processing_context import ProcessingContext
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
    media_file = context.media_input.file_list[0]
    claims = detect_filename_claims(
        [media_file.stem], settings.movie.claims, context.custom_edition_info
    )
    pair = context.media_input.comparison_pair
    quality = RenameEncodeBackEnd.get_quality(
        media_input=media_file, source_input=pair.source if pair else None
    )
    return choices_from_claims(claims, quality, context, settings)


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
