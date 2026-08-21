"""Where generate_tracker_title sources a title from.

The entry governs where a tracker has one, and the user's global template
applies otherwise. That reverses what this file used to assert -- that the
user's own override governed for every tracker without exception -- and the
reversal is the feature rather than a cost of it: the shipped title config
was not derived from tracker rules, and every tracker checked against its
published rules during design had defects.

`TrackerInfo` still carries its title override fields and still reaches this
function, because removing them from the configuration is separate work. A
test below pins that they are ignored rather than merely unused, so the
removal cannot quietly change behaviour when it lands.
"""

from copy import deepcopy
from types import SimpleNamespace
from typing import cast

from src.backend.process import ProcessBackEnd
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection
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


def _title(
    tracker: TrackerSelection,
    context: ProcessingContext | None = None,
    backend: ProcessBackEnd | None = None,
) -> str | None:
    context = context if context is not None else _context()
    backend = backend if backend is not None else _backend()
    return backend.generate_tracker_title(
        tracker,
        TrackerInfo(),
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
    assert _title(TrackerSelection.BLUTOPIA) == "Movie Name (global)"


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
    # Blutopia names no colon rule, so the user's setting applies.
    blutopia = _title(TrackerSelection.BLUTOPIA, context, backend)

    assert aither is not None
    assert "Mission: Impossible" in aither
    # DELETE removes the colon and leaves the space that followed it.
    assert blutopia == "Mission Impossible"


def test_a_stored_title_override_no_longer_influences_the_title() -> None:
    """The 57 override slots stop governing here before they are deleted.

    A TrackerInfo still reaches this function and still carries the fields
    until the configuration is removed, so this pins that they are ignored
    rather than merely unused.
    """
    context = _context()
    overridden = TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override="{title_clean} OVERRIDDEN",  # noqa: S106
        mvr_title_colon_replace=ColonReplace.KEEP,
    )

    title = _backend().generate_tracker_title(
        TrackerSelection.BLUTOPIA,
        overridden,
        context,
        build_series_release_info(context.media_input),
    )

    assert title == "Movie Name (global)"


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
