"""Which stages a release goes through, and in what order.

This is the route the desktop wizard walks page by page, and the one a
headless run walks without pages. It lives here so both follow the same rules:
the wizard maps each stage to a page, and nothing else decides the order.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from nfoforge.enums.media_type import MediaType

if TYPE_CHECKING:
    from nfoforge.config.models import AppConfig


class Stage(StrEnum):
    """One step of preparing and uploading a release.

    String values, because a stage is recorded in saved jobs and reported to
    whatever is watching a run.
    """

    INPUT = "input"
    SEARCH = "search"
    SERIES_MATCH = "series_match"
    RENAME = "rename"
    SCREENSHOTS = "screenshots"
    TRACKERS = "trackers"
    PRE_UPLOAD = "pre_upload"
    PROCESS = "process"


@dataclass(frozen=True, slots=True)
class RoutingOptions:
    """The settings that decide which optional stages run."""

    rename_movies: bool
    rename_series: bool
    screenshots: bool

    @classmethod
    def from_settings(cls, settings: AppConfig) -> RoutingOptions:
        return cls(
            rename_movies=settings.movie.enabled,
            rename_series=settings.series.enabled,
            screenshots=settings.screenshots.enabled,
        )


def plan_stages(media_type: MediaType | None, options: RoutingOptions) -> list[Stage]:
    """Every stage a release of `media_type` goes through, in order.

    `media_type` is only known once the release has been identified, so a
    route planned before then (`None`) is right up to `Stage.SEARCH` and should
    be planned again afterwards. It is planned as a movie, which has no stages
    a series lacks.
    """
    is_series = media_type is MediaType.SERIES
    stages = [Stage.INPUT, Stage.SEARCH]
    if is_series:
        stages.append(Stage.SERIES_MATCH)
    if options.rename_series if is_series else options.rename_movies:
        stages.append(Stage.RENAME)
    if options.screenshots:
        stages.append(Stage.SCREENSHOTS)
    stages += [Stage.TRACKERS, Stage.PRE_UPLOAD, Stage.PROCESS]
    return stages


def next_stage(
    current: Stage, media_type: MediaType | None, options: RoutingOptions
) -> Stage | None:
    """The stage after `current`, or `None` when `current` is the last.

    A stage the route for this release skips (say, `Stage.RENAME` with renaming
    turned off) still has a successor: the next stage in the full order that
    the route does include. That keeps a caller that arrived at a stage by some
    other way -- a resumed job, a setting changed mid-run -- moving forward
    rather than stuck.
    """
    route = plan_stages(media_type, options)
    order = list(Stage)
    for stage in order[order.index(current) + 1 :]:
        if stage in route:
            return stage
    return None
