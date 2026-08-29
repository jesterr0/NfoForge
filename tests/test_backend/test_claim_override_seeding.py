"""Stage 1 for a run that never reached a rename page.

Renaming is optional, and with it off the wizard routes straight past the
page that detects claims and populates the overrides. Nothing else did it, so
the NFO and the tracker titles rendered as though the filenames claimed
nothing. Detection belongs to the run rather than to one page.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from src.backend.process import ProcessBackEnd
from src.config.config import ConfigManager
from src.config.models import ClaimSwitches
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload

MOVIE_STEM = "Movie.2024.Directors.Cut.IMAX.REPACK.1080p.BluRay.x264-GRP"


def _switches(**overrides: bool) -> ClaimSwitches:
    base = {
        "enabled": True,
        "edition": True,
        "frame_size": True,
        "localization": True,
        "re_release": True,
        "remux": True,
        "hybrid": True,
        "release_group": True,
    }
    base.update(overrides)
    return ClaimSwitches(**base)  # pyright: ignore[reportArgumentType]


def _backend(
    movie_claims: ClaimSwitches | None = None,
    series_claims: ClaimSwitches | None = None,
) -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        ConfigManager,
        SimpleNamespace(
            settings=SimpleNamespace(
                movie=SimpleNamespace(claims=movie_claims or _switches()),
                series=SimpleNamespace(claims=series_claims or _switches()),
            )
        ),
    )
    return backend


def _context(*stems: str, media_type: MediaType = MediaType.MOVIE) -> ProcessingContext:
    return ProcessingContext(
        media_input=MediaInputPayload(
            input_path=Path("input"),
            media_type=media_type,
            file_list=[Path(f"{stem}.mkv") for stem in stems],
        ),
        media_search=MediaSearchPayload(media_type=media_type),
    )


def test_a_run_that_skipped_the_rename_page_still_detects_its_claims() -> None:
    context = _context(MOVIE_STEM)

    _backend()._seed_claim_overrides(context)

    overrides = context.shared_data.dynamic_data["override_tokens"]
    assert overrides["release_group"] == "GRP"
    assert overrides["edition"] == "Directors Cut"
    assert overrides["frame_size"] == "IMAX"
    assert overrides["re_release"] == "REPACK"


def test_the_switches_still_govern_the_skip_path() -> None:
    """A switch the user turned off must mean the same thing everywhere. If
    seeding ignored it, turning release group parsing off would work on the
    rename page and silently not work with renaming disabled."""
    context = _context(MOVIE_STEM)

    _backend(movie_claims=_switches(release_group=False))._seed_claim_overrides(context)

    overrides = context.shared_data.dynamic_data["override_tokens"]
    assert "release_group" not in overrides
    assert overrides["edition"] == "Directors Cut"


def test_a_run_that_reached_the_rename_page_is_left_alone() -> None:
    """Those overrides are the user's stage-2 decisions, and a blank group is
    one of them -- re-detecting would hand back what they cleared."""
    context = _context(MOVIE_STEM)
    context.shared_data.dynamic_data["override_tokens"] = {"release_group": ""}

    _backend()._seed_claim_overrides(context)

    assert context.shared_data.dynamic_data["override_tokens"] == {"release_group": ""}


def test_a_series_run_reads_the_series_switches() -> None:
    context = _context(
        "Show.S01E01.1080p.WEB-DL.x264-GRP",
        "Show.S01E02.1080p.WEB-DL.x264-GRP",
        media_type=MediaType.SERIES,
    )

    _backend(
        movie_claims=_switches(release_group=False),
        series_claims=_switches(),
    )._seed_claim_overrides(context)

    assert context.shared_data.dynamic_data["override_tokens"]["release_group"] == "GRP"


def test_a_pack_that_disagrees_carries_no_group() -> None:
    """Claims are pack-wide: one dissenting episode means the claim is not the
    pack's, so no control could carry it and no output should."""
    context = _context(
        "Show.S01E01.1080p.WEB-DL.x264-GRP",
        "Show.S01E02.1080p.WEB-DL.x264-OTHER",
        media_type=MediaType.SERIES,
    )

    _backend()._seed_claim_overrides(context)

    assert "release_group" not in context.shared_data.dynamic_data["override_tokens"]


def test_a_run_with_no_files_seeds_nothing() -> None:
    context = _context()

    _backend()._seed_claim_overrides(context)

    assert "override_tokens" not in context.shared_data.dynamic_data
