"""Where generate_tracker_title sources a title from.

The entry governs where a tracker has one, and the user's global template
applies otherwise. That reverses what this file used to assert -- that the
user's own override governed for every tracker without exception -- and the
reversal is the feature rather than a cost of it: the shipped title config
was not derived from tracker rules, and every tracker checked against its
published rules during design had defects.

`TrackerInfo` still reaches this function, because callers hold one and
later work reads other fields from it. A test below pins that no title
field remains on it to be read.
"""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from src.backend.process import ProcessBackEnd
from src.backend.trackers.title_rules import TITLE_RULES, Separator
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import TrackerError
from src.payloads.series import build_series_release_info
from src.payloads.trackers import TrackerInfo


def _backend(
    movie_template: str = "{title_clean} (global)",
    movie_colon: ColonReplace = ColonReplace.REPLACE_WITH_DASH,
) -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        ConfigManager,
        SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(release_group=""),
                movie=SimpleNamespace(
                    title_token=movie_template,
                    title_colon_replace=movie_colon,
                    claims=SimpleNamespace(enabled=True),
                ),
                series=SimpleNamespace(
                    multi_episode_style=MultiEpisodeStyle.RANGE,
                    claims=SimpleNamespace(enabled=True),
                ),
                user_tokens=SimpleNamespace(tokens={}),
                global_management=SimpleNamespace(
                    title_clean_rules=None,
                    video_dynamic_range=None,
                ),
            ),
        ),
    )
    return backend


def _context() -> ProcessingContext:
    return ProcessingContext(
        media_input=deepcopy(EXAMPLE_MEDIA_INPUT_PAYLOAD),
        media_search=deepcopy(EXAMPLE_SEARCH_PAYLOAD),
    )


def _renders_the_users_template() -> TrackerSelection:
    """Any tracker with no composition of its own.

    Derived rather than named. Which tracker happens to lack rules today is
    not what these tests are about, and naming one would break the day it
    gains some -- for the same reason they were rewritten when the entries
    landed.

    Spaced, because these tests assert a spaced string. SeedPool defers
    to the user too but renders the release form, which would make the
    expectation about its separator rather than about precedence.
    """
    for tracker, entry in TITLE_RULES.items():
        if (
            entry.composition is None
            and entry.has_release_name_field
            and entry.normalisation.separator is Separator.SPACED
        ):
            return tracker
    pytest.fail(
        "Every tracker composes now, so nothing renders the user's global "
        "template. That is a real change rather than a broken fixture: "
        "decide what the global title template is still for."
    )


def _title(
    tracker: TrackerSelection,
    context: ProcessingContext | None = None,
    backend: ProcessBackEnd | None = None,
) -> str | None:
    context = context if context is not None else _context()
    backend = backend if backend is not None else _backend()
    return backend.generate_tracker_title(
        tracker,
        context,
        build_series_release_info(context.media_input),
    )


def test_a_composing_tracker_ignores_the_users_global_template() -> None:
    """Enforcement means overriding what the user chose.

    This is the one place the file naming work's output-preserving
    principle is deliberately reversed.
    """
    title = _title(TrackerSelection.AITHER)

    assert title is not None
    assert "(global)" not in title
    assert title.startswith("Movie Name")


def test_a_tracker_without_a_composition_renders_the_users_template() -> None:
    # Seven trackers have no layout of their own and render the user's
    # house style, which is exactly what they do today.
    assert _title(_renders_the_users_template()) == "Movie Name (global)"


def test_a_tracker_with_no_release_name_field_has_no_title() -> None:
    # PTP derives its release from structured fields; HUNO auto mode builds
    # its name from the torrent filename, MediaInfo and TMDB.
    assert _title(TrackerSelection.PASS_THE_POPCORN) is None
    assert _title(TrackerSelection.HUNO) is None


def test_the_entry_colon_beats_the_users_global() -> None:
    context = _context()
    context.media_search.title = "Mission: Impossible"
    backend = _backend(
        movie_template="{title_exact}",
        movie_colon=ColonReplace.DELETE,
    )

    # Aither's entry keeps colons; the user asked for them to be deleted.
    aither = _title(TrackerSelection.AITHER, context, backend)
    # A tracker naming no colon rule lets the user's setting apply.
    deferring = _title(_renders_the_users_template(), context, backend)

    assert aither is not None
    assert "Mission: Impossible" in aither
    # DELETE removes the colon and leaves the space that followed it.
    assert deferring == "Mission Impossible"


def test_no_title_override_field_remains_on_a_tracker() -> None:
    """The 57 override slots are gone, and cannot be smuggled back.

    This replaces a test that pinned them as *ignored* while they still
    existed, which is what let the configuration be removed afterwards
    without changing behaviour. A TrackerInfo still reaches
    generate_tracker_title, so a title field left on it could silently
    start governing again.
    """
    info = TrackerInfo()

    for field in (
        "mvr_title_override_enabled",
        "mvr_title_colon_replace",
        "mvr_title_token_override",
        "mvr_title_replace_map",
        "tvr_title_overrides",
    ):
        assert not hasattr(info, field), field


def test_accepted_claims_reach_the_tracker_title() -> None:
    """A claim the user accepted must reach the tracker title.

    These tokens were gated on the old parse_filename_attributes flag,
    which generate_tracker_title never passed -- so they resolved to
    nothing on every upload even though Aither's rules ask for a re-release
    marker. They arrive as overrides now, which is what the rename page
    puts in shared_data.
    """
    context = _context()
    context.shared_data.dynamic_data["override_tokens"] = {
        "re_release": "REPACK",
        "remux": "REMUX",
    }

    title = _title(TrackerSelection.AITHER, context)

    assert title is not None
    assert "REPACK" in title
    assert "REMUX" in title


def test_an_unclaimed_attribute_is_not_inferred_for_the_tracker_title() -> None:
    """The other half: with nothing accepted, nothing is invented.

    The example payload's filename carries REPACK and REMUX. Reaching for
    them here would make the tracker title disagree with the rename page,
    which is what a user switching a category off is asking not to happen.
    """
    title = _title(TrackerSelection.AITHER)

    assert title is not None
    assert "REPACK" not in title
    assert "REMUX" not in title


def test_audio_codec_override_reaches_split_tracker_audio_tokens() -> None:
    """LST splits Atmos from the codec even though the wizard exposes the
    combined ``audio_codec`` token for editing."""
    context = _context()
    context.shared_data.dynamic_data["override_tokens"] = {
        "audio_codec": "DD+ Atmos",
        "audio_channel_s": "5.1",
    }

    title = _title(TrackerSelection.LST, context)

    assert title is not None
    assert "DD+ 5.1 Atmos" in title


def test_beyondhd_keeps_its_audio_undivided_where_lst_splits_it() -> None:
    # The same release, two trackers, two published spellings: BHD
    # wants "DDP Atmos 5.1" where LST wants "DD+ 5.1 Atmos".
    context = _context()
    context.shared_data.dynamic_data["override_tokens"] = {
        "audio_codec": "DDP Atmos",
        "audio_channel_s": "5.1",
    }

    beyond_hd = _title(TrackerSelection.BEYOND_HD, context)
    lst = _title(TrackerSelection.LST, context)

    assert beyond_hd is not None
    assert "DDP Atmos 5.1" in beyond_hd
    assert lst is not None
    assert "DD+ 5.1 Atmos" in lst


def _composing_tracker() -> TrackerSelection:
    """Any tracker with a composition of its own."""
    for tracker, entry in TITLE_RULES.items():
        if entry.composition is not None:
            return tracker
    pytest.fail("No tracker composes, so there are no hardcoded rules left.")


def test_an_empty_title_with_a_composition_is_refused() -> None:
    """A hardcoded composition producing nothing means something is broken.

    Failing is better than uploading a name the tracker's rules will
    reject. generate_tracker_title returns None whenever get_output() is
    falsy, and _format_token_string returns None on ValueError, KeyError or
    IndexError with only a warning -- so a malformed rule used to degrade
    silently into uploading a filename to a tracker with strict naming
    requirements.
    """
    tracker = _composing_tracker()
    backend = _backend()

    with pytest.raises(TrackerError, match=str(tracker)):
        backend.resolve_tracker_title(tracker, None, Path("Some.Release-GRP.mkv"))


def test_an_empty_title_without_a_composition_falls_back_and_says_so() -> None:
    """Correct for SeedPool, which names uploads after the release.

    A tracker with no composition is rendering the user's global template,
    where the release name is the sensible last resort. What it must never
    be is silent -- that is the defect this replaces.
    """
    tracker = _renders_the_users_template()
    backend = _backend()

    resolved = backend.resolve_tracker_title(
        tracker, None, Path("Some.Release.1080p.BluRay.x264-GRP.mkv")
    )

    # Spaced, because the fallback is normalised like any other title --
    # see below.
    assert resolved == "Some Release 1080p BluRay x264-GRP"


def test_a_tracker_with_no_release_name_field_needs_no_title() -> None:
    # Nothing to shape, so an absent title is the expected state rather
    # than a failure or a fallback.
    resolved = _backend().resolve_tracker_title(
        TrackerSelection.PASS_THE_POPCORN, None, Path("Some.Release-GRP.mkv")
    )

    assert resolved is None


def test_a_rendered_title_is_returned_unchanged() -> None:
    backend = _backend()

    assert (
        backend.resolve_tracker_title(
            _composing_tracker(), "Movie Name 2024", Path("x.mkv")
        )
        == "Movie Name 2024"
    )


def test_the_fallback_is_normalised_like_any_other_title() -> None:
    """A release name is a filename stem, so it arrives dotted.

    That is what SeedPool wants and the opposite of what every other
    tracker here does, so the fallback goes through the entry's
    normalisation rather than being passed along raw.
    """
    backend = _backend()
    stem = Path("Some.Release.1080p.BluRay.x264-GRP.mkv")

    spaced = backend.resolve_tracker_title(_renders_the_users_template(), None, stem)
    dotted = backend.resolve_tracker_title(TrackerSelection.SEEDPOOL, None, stem)

    assert spaced == "Some Release 1080p BluRay x264-GRP"
    assert dotted == "Some.Release.1080p.BluRay.x264-GRP"
