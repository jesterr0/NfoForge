"""Where generate_tracker_title sources a title from.

The user's own override governs, for every tracker without exception. Some
were once locked to the packaged default, and PassThePopcorn was excluded
entirely; both carve-outs were removed. A locked template cannot differ
between profiles, and what a tracker actually demands is applied in code at
upload anyway (see `tracker_title_formatting`).
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
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection
from src.payloads.series import SeriesReleaseInfo, build_series_release_info
from src.payloads.trackers import TitleOverridePayload, TrackerInfo


def _backend(packaged_default: TrackerInfo) -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        ConfigManager,
        SimpleNamespace(
            settings=SimpleNamespace(
                movie=SimpleNamespace(
                    title_token="{title_clean} (global)",  # noqa: S106
                    title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
                    parse_filename_attributes=True,
                ),
                series=SimpleNamespace(
                    multi_episode_style=MultiEpisodeStyle.RANGE,
                    parse_filename_attributes=True,
                ),
                user_tokens=SimpleNamespace(tokens={}),
                global_management=SimpleNamespace(
                    title_clean_rules=None,
                    video_dynamic_range=None,
                ),
            ),
            defaults=SimpleNamespace(
                trackers=SimpleNamespace(
                    by_selection=lambda: {
                        TrackerSelection.AITHER: packaged_default,
                        TrackerSelection.PASS_THE_POPCORN: TrackerInfo(),
                    }
                )
            ),
        ),
    )
    return backend


def _context() -> ProcessingContext:
    return ProcessingContext(
        media_input=deepcopy(EXAMPLE_MEDIA_INPUT_PAYLOAD),
        media_search=deepcopy(EXAMPLE_SEARCH_PAYLOAD),
    )


def test_the_live_override_governs_even_where_a_packaged_default_exists() -> None:
    """Aither ships a packaged title, and used to be locked to it. Now the
    profile's own value wins -- which is what lets one profile name encodes
    and another name discs."""
    context = _context()
    packaged_default = TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override="{title_clean} (packaged)",  # noqa: S106
        mvr_title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
    )
    backend = _backend(packaged_default)
    live = TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override="{title_clean} (user override)",  # noqa: S106
        mvr_title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
    )

    output = backend.generate_tracker_title(
        TrackerSelection.AITHER,
        live,
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie Name (user override)"


def test_disabling_the_override_falls_through_to_the_global_template() -> None:
    """Turning an override off has to mean something now that it is the
    user's to turn off. It used to be ignored for a locked tracker."""
    context = _context()
    backend = _backend(
        TrackerInfo(
            mvr_title_override_enabled=True,
            mvr_title_token_override="{title_clean} (packaged)",  # noqa: S106
        )
    )
    disabled_live = TrackerInfo(
        mvr_title_override_enabled=False,
        mvr_title_token_override="{title_clean} (user override)",  # noqa: S106
    )

    output = backend.generate_tracker_title(
        TrackerSelection.AITHER,
        disabled_live,
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie Name (global)"


def test_pass_the_popcorn_reads_its_override_like_any_other_tracker() -> None:
    """PTP was the last tracker excluded here, on the grounds that its upload
    form has no release-name field (see `ptp_uploader`).

    That is still true -- what is generated shapes what NfoForge shows and
    records for the upload rather than what PTP receives -- but it is no
    reason to special-case the title here. Every tracker reads its own
    override.
    """
    context = _context()
    backend = _backend(TrackerInfo())
    live = TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override="{title_clean} (user override)",  # noqa: S106
        mvr_title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
    )

    output = backend.generate_tracker_title(
        TrackerSelection.PASS_THE_POPCORN,
        live,
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie Name (user override)"


def test_a_tracker_that_was_always_editable_is_unchanged() -> None:
    """BeyondHD was never locked, so nothing about it changed."""
    context = _context()
    backend = _backend(TrackerInfo())
    live = TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override="{title_clean} (user override)",  # noqa: S106
        mvr_title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
    )

    output = backend.generate_tracker_title(
        TrackerSelection.BEYOND_HD,
        live,
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie Name (user override)"


def _series_backend(packaged_default: TrackerInfo) -> ProcessBackEnd:
    """Like _backend, but with the series token fields generate_tracker_title
    reads on the is_series path."""
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        ConfigManager,
        SimpleNamespace(
            settings=SimpleNamespace(
                movie=SimpleNamespace(
                    title_token="{title_clean} (global movie)",  # noqa: S106
                    title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
                    parse_filename_attributes=True,
                ),
                series=SimpleNamespace(
                    multi_episode_style=MultiEpisodeStyle.RANGE,
                    standard_title_token="{title_clean} (global series)",  # noqa: S106
                    daily_title_token="{title_clean} (global daily)",  # noqa: S106
                    anime_title_token="{title_clean} (global anime)",  # noqa: S106
                    title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
                    parse_filename_attributes=True,
                ),
                user_tokens=SimpleNamespace(tokens={}),
                global_management=SimpleNamespace(
                    title_clean_rules=None,
                    video_dynamic_range=None,
                ),
            ),
            defaults=SimpleNamespace(
                trackers=SimpleNamespace(
                    by_selection=lambda: {
                        TrackerSelection.AITHER: packaged_default,
                        # REQUIRED, but ships no series format
                        TrackerSelection.HUNO: TrackerInfo(
                            mvr_title_override_enabled=True,
                            mvr_title_token_override="{title_clean} (enforced movie)",  # noqa: S106 - template token string, not a credential
                        ),
                    }
                )
            ),
        ),
    )
    return backend


def _series_release_info(context: ProcessingContext) -> SeriesReleaseInfo:
    return SeriesReleaseInfo(
        media_type=MediaType.SERIES,
        input_path=context.media_input.input_path,
        primary_file=context.media_input.input_path,
        title_path=context.media_input.input_path,
        season=1,
        episode_start=1,
        episode_count=1,
        episode_format=EpisodeFormat.STANDARD,
    )


def test_the_live_series_override_governs() -> None:
    """The series path follows the movie path: the profile's own entry wins
    over the packaged one and over the global series template."""
    context = _context()
    packaged_default = TrackerInfo(
        tvr_title_overrides={
            EpisodeFormat.STANDARD: TitleOverridePayload(
                enabled=True,
                colon_replace=ColonReplace.REPLACE_WITH_DASH,
                token="{title_clean} (packaged series)",  # noqa: S106
            )
        }
    )
    backend = _series_backend(packaged_default)
    live = TrackerInfo(
        tvr_title_overrides={
            EpisodeFormat.STANDARD: TitleOverridePayload(
                enabled=True,
                colon_replace=ColonReplace.REPLACE_WITH_DASH,
                token="{title_clean} (user override)",  # noqa: S106
            )
        }
    )

    output = backend.generate_tracker_title(
        TrackerSelection.AITHER,
        live,
        context,
        _series_release_info(context),
    )

    assert output is not None
    assert "(user override)" in output
    assert "(packaged series)" not in output
    assert "(global series)" not in output


def test_a_tracker_with_a_movie_format_only_reads_the_live_series_override() -> None:
    """HUNO ships a movie title and no tvr_title_overrides. Its series title
    comes from the profile like any other."""
    context = _context()
    backend = _series_backend(TrackerInfo())
    live = TrackerInfo(
        tvr_title_overrides={
            EpisodeFormat.STANDARD: TitleOverridePayload(
                enabled=True,
                colon_replace=ColonReplace.REPLACE_WITH_DASH,
                token="{title_clean} (user override)",  # noqa: S106 - template token string, not a credential
            )
        }
    )

    output = backend.generate_tracker_title(
        TrackerSelection.HUNO,
        live,
        context,
        _series_release_info(context),
    )

    assert output is not None
    assert "(user override)" in output
    assert "(global series)" not in output


def test_no_live_series_override_falls_back_to_the_global() -> None:
    """Same tracker, nothing set in the profile: the global series template."""
    context = _context()
    backend = _series_backend(TrackerInfo())

    output = backend.generate_tracker_title(
        TrackerSelection.HUNO,
        TrackerInfo(),
        context,
        _series_release_info(context),
    )

    assert output is not None
    assert "(global series)" in output


_ATTRIBUTE_TOKEN = "{title_clean}{:opt= :re_release}{:opt= :remux}"  # noqa: S105


def _parse_attributes_backend(enabled: bool) -> ProcessBackEnd:
    """A _backend whose movie config carries the given
    parse_filename_attributes setting."""
    backend = _backend(TrackerInfo())
    backend.config.settings.movie.parse_filename_attributes = enabled
    return backend


def _attribute_live_info() -> TrackerInfo:
    return TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override=_ATTRIBUTE_TOKEN,
        mvr_title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
    )


def test_filename_attributes_reach_the_tracker_title() -> None:
    """{re_release}, {remux} and {hybrid} are gated on
    parse_filename_attributes, and generate_tracker_title never passed it --
    so those tokens resolved to nothing on every upload, even though the
    packaged Aither/LST/ReelFliX templates ask for {re_release} and the
    rename page (which does pass it) displayed the value.

    The example payload's filename carries both REPACK and REMUX.
    """
    context = _context()

    output = _parse_attributes_backend(True).generate_tracker_title(
        TrackerSelection.AITHER,
        _attribute_live_info(),
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie Name REPACK REMUX"


def test_the_user_setting_is_honored_rather_than_forced_on() -> None:
    """Turning the setting off means "do not infer these from the filename",
    and a tracker title has to respect that the same way a rename does --
    otherwise the two disagree about the same release."""
    context = _context()

    output = _parse_attributes_backend(False).generate_tracker_title(
        TrackerSelection.AITHER,
        _attribute_live_info(),
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie Name"


def test_audio_codec_override_reaches_split_tracker_audio_tokens() -> None:
    """Tracker templates can split Atmos from the codec even though the
    wizard exposes the combined ``audio_codec`` token for editing."""
    context = _context()
    context.shared_data.dynamic_data["override_tokens"] = {
        "audio_codec": "DD+ Atmos",
        "audio_channel_s": "5.1",
    }
    live = TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override=(  # noqa: S106
            "{audio_codec_no_atmos} {audio_channel_s} {atmos}"
        ),
        mvr_title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
    )

    output = _backend(TrackerInfo()).generate_tracker_title(
        TrackerSelection.LST,
        live,
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "DD+ 5.1 Atmos"
