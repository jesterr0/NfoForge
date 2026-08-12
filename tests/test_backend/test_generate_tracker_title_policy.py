"""Proves generate_tracker_title's title-format-policy enforcement: a
REQUIRED tracker (e.g. Aither) always uses the packaged default even if the
live, user-editable tracker_info has been tampered with, and an UNSUPPORTED
tracker (PTP) never applies an override at all, no matter what the live
tracker_info claims.

REQUIRED is resolved per media type, so a tracker that dictates a movie format
but ships no series format (HUNO) enforces nothing on the series path and reads
the live override there. See src/backend/trackers/title_format_policy.py.
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
                ),
                series=SimpleNamespace(
                    multi_episode_style=MultiEpisodeStyle.RANGE,
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


def test_required_tracker_ignores_a_tampered_live_override() -> None:
    """Aither is REQUIRED: even if the live tracker_info has the override
    disabled and its token blanked, the packaged default must still win."""
    context = _context()
    packaged_default = TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override="{title_clean} (enforced)",  # noqa: S106
        mvr_title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
    )
    backend = _backend(packaged_default)
    tampered_live = TrackerInfo(
        mvr_title_override_enabled=False,
        mvr_title_token_override="",
    )

    output = backend.generate_tracker_title(
        TrackerSelection.AITHER,
        tampered_live,
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie Name (enforced)"


def test_unsupported_tracker_ignores_a_faked_live_override() -> None:
    """PTP is UNSUPPORTED: even if the live tracker_info fakes an enabled
    override, it must be ignored in favor of the global template."""
    context = _context()
    backend = _backend(TrackerInfo())
    faked_live = TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override="{title_clean} (should be ignored)",  # noqa: S106
    )

    output = backend.generate_tracker_title(
        TrackerSelection.PASS_THE_POPCORN,
        faked_live,
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie Name (global)"


def test_free_tracker_still_reads_the_live_override() -> None:
    """A FREE tracker (e.g. BeyondHD) is unaffected by this policy -- its
    live tracker_info is used exactly as before."""
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
                ),
                series=SimpleNamespace(
                    multi_episode_style=MultiEpisodeStyle.RANGE,
                    standard_title_token="{title_clean} (global series)",  # noqa: S106
                    daily_title_token="{title_clean} (global daily)",  # noqa: S106
                    anime_title_token="{title_clean} (global anime)",  # noqa: S106
                    title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
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


def test_required_tracker_uses_the_packaged_series_override() -> None:
    """Aither is REQUIRED. On the series path its packaged tvr_title_overrides
    entry must win over both the live user override and the global series
    template."""
    context = _context()
    packaged_default = TrackerInfo(
        tvr_title_overrides={
            EpisodeFormat.STANDARD: TitleOverridePayload(
                enabled=True,
                colon_replace=ColonReplace.REPLACE_WITH_DASH,
                token="{title_clean} (enforced series)",  # noqa: S106
            )
        }
    )
    backend = _series_backend(packaged_default)
    tampered_live = TrackerInfo(
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
        tampered_live,
        context,
        _series_release_info(context),
    )

    assert output is not None
    assert "(enforced series)" in output
    assert "(user override)" not in output
    assert "(global series)" not in output


def test_required_tracker_without_a_series_format_reads_the_live_override() -> None:
    """HUNO is REQUIRED and dictates a movie format, but ships no
    tvr_title_overrides. There is nothing to enforce on the series path, so
    locking the user out would gain nothing -- the live override wins."""
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


def test_required_tracker_without_a_series_format_falls_back_to_the_global() -> None:
    """Same tracker, no live override: the global series template, exactly as
    before this resolved per media type."""
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
