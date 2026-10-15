"""The route a release takes through the stages."""

import pytest

from nfoforge.core.workflow.stages import RoutingOptions, Stage, next_stage, plan_stages
from nfoforge.enums.media_type import MediaType

ALL_ON = RoutingOptions(rename_movies=True, rename_series=True, screenshots=True)
ALL_OFF = RoutingOptions(rename_movies=False, rename_series=False, screenshots=False)


def test_movie_with_everything_enabled() -> None:
    assert plan_stages(MediaType.MOVIE, ALL_ON) == [
        Stage.INPUT,
        Stage.SEARCH,
        Stage.RENAME,
        Stage.SCREENSHOTS,
        Stage.TRACKERS,
        Stage.PRE_UPLOAD,
        Stage.PROCESS,
    ]


def test_series_adds_episode_matching() -> None:
    assert plan_stages(MediaType.SERIES, ALL_ON) == [
        Stage.INPUT,
        Stage.SEARCH,
        Stage.SERIES_MATCH,
        Stage.RENAME,
        Stage.SCREENSHOTS,
        Stage.TRACKERS,
        Stage.PRE_UPLOAD,
        Stage.PROCESS,
    ]


@pytest.mark.parametrize("media_type", [MediaType.MOVIE, MediaType.SERIES])
def test_optional_stages_drop_out(media_type: MediaType) -> None:
    route = plan_stages(media_type, ALL_OFF)

    assert Stage.RENAME not in route
    assert Stage.SCREENSHOTS not in route
    assert route[-3:] == [Stage.TRACKERS, Stage.PRE_UPLOAD, Stage.PROCESS]


def test_rename_follows_the_setting_for_its_own_media_type() -> None:
    movies_only = RoutingOptions(
        rename_movies=True, rename_series=False, screenshots=False
    )

    assert Stage.RENAME in plan_stages(MediaType.MOVIE, movies_only)
    assert Stage.RENAME not in plan_stages(MediaType.SERIES, movies_only)


def test_unidentified_release_is_planned_as_a_movie() -> None:
    assert plan_stages(None, ALL_ON) == plan_stages(MediaType.MOVIE, ALL_ON)


@pytest.mark.parametrize(
    ("current", "media_type", "options", "expected"),
    [
        (Stage.INPUT, None, ALL_ON, Stage.SEARCH),
        (Stage.SEARCH, MediaType.MOVIE, ALL_ON, Stage.RENAME),
        (Stage.SEARCH, MediaType.MOVIE, ALL_OFF, Stage.TRACKERS),
        (Stage.SEARCH, MediaType.SERIES, ALL_OFF, Stage.SERIES_MATCH),
        (Stage.SERIES_MATCH, MediaType.SERIES, ALL_ON, Stage.RENAME),
        (Stage.RENAME, MediaType.MOVIE, ALL_ON, Stage.SCREENSHOTS),
        (Stage.TRACKERS, MediaType.MOVIE, ALL_ON, Stage.PRE_UPLOAD),
        (Stage.PRE_UPLOAD, MediaType.MOVIE, ALL_ON, Stage.PROCESS),
        (Stage.PROCESS, MediaType.MOVIE, ALL_ON, None),
    ],
)
def test_next_stage(
    current: Stage,
    media_type: MediaType | None,
    options: RoutingOptions,
    expected: Stage | None,
) -> None:
    assert next_stage(current, media_type, options) == expected


def test_next_stage_from_a_stage_the_route_skips_still_moves_forward() -> None:
    """A resumed job can sit on a stage its current settings would skip."""
    assert next_stage(Stage.RENAME, MediaType.MOVIE, ALL_OFF) is Stage.TRACKERS
