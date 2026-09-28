"""What can be checked about a run before any of its work is done.

A headless run reads MediaInfo, searches TMDB, renames files and generates
screenshots before it reaches the trackers. A request that names a tracker
the profile does not have, or an image host it cannot use, would otherwise be
refused only after all of that. Everything here depends on nothing but the
request and the profile, so it is checked first and reported all at once.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from nfoforge.backend.template_selector import TemplateSelectorBackEnd
from nfoforge.core.trackers.image_hosts import available_image_hosts, find_image_host
from nfoforge.core.trackers.validate import (
    missing_nfo_templates,
    resolve_tracker_names,
    tracker_profile_problems,
)
from nfoforge.core.workflow.decisions import DecisionKind
from nfoforge.core.workflow.request import ReleaseRequest
from nfoforge.core.workflow.steps import (
    WorkflowError,
    collect_media_files,
    screenshot_dir_images,
)
from nfoforge.enums.automation import AutomationMode
from nfoforge.enums.tracker_selection import TrackerSelection

if TYPE_CHECKING:
    from nfoforge.config.config import ConfigManager

UnresolvedPromptTokens = Callable[
    [Iterable[TrackerSelection], Mapping[str, str]], list[str]
]


def preflight_problems(
    request: ReleaseRequest,
    config: ConfigManager,
    *,
    screenshots: bool,
    answers: Mapping[str, Any],
    unresolved_prompt_tokens: UnresolvedPromptTokens,
    template_selector: TemplateSelectorBackEnd | None = None,
) -> list[str]:
    """Every reason `request` cannot succeed that is knowable up front.

    `screenshots` is whether the run will take screenshots at all; the image
    host and screenshot options only matter when it will.
    """
    settings = config.settings
    problems: list[str] = []

    try:
        collect_media_files(request.path.expanduser())
    except WorkflowError as error:
        problems.append(str(error))

    if not settings.api_keys.tmdb_api_key:
        problems.append("No TMDB API key is set in this config profile")

    trackers = _tracker_problems(
        request, settings, problems, template_selector or TemplateSelectorBackEnd()
    )

    if screenshots:
        if request.screenshot_dir is not None:
            try:
                screenshot_dir_images(request.screenshot_dir)
            except WorkflowError as error:
                problems.append(str(error))
        elif request.screenshot_count is not None and request.screenshot_count < 1:
            problems.append("The screenshot count must be at least 1")
        if request.image_host is not None:
            try:
                find_image_host(
                    request.image_host,
                    available_image_hosts(settings, config.plugin_manager),
                )
            except ValueError as error:
                problems.append(str(error))

    # only an unattended run is refused over a missing answer; an interactive
    # run asks at upload and a safe one saves a job that can be answered later
    if (
        trackers
        and request.mode is AutomationMode.UNATTENDED
        and str(DecisionKind.PROMPT_TOKENS) not in answers
    ):
        unanswered = unresolved_prompt_tokens(trackers, request.prompt_tokens)
        if unanswered:
            problems.append(
                "The NFO templates ask for: "
                + ", ".join(unanswered)
                + " (pass --token NAME=VALUE for each)"
            )
    return problems


def _tracker_problems(
    request: ReleaseRequest,
    settings: Any,
    problems: list[str],
    template_selector: TemplateSelectorBackEnd,
) -> list[TrackerSelection]:
    """Add what is wrong with the named trackers to `problems`.

    Returns the trackers, or nothing when any of them has a problem, since the
    later checks read their templates.
    """
    if not request.trackers:
        problems.append(
            "No trackers were named for this release (pass --trackers, or a "
            "preset that names them)"
        )
        return []
    tracker_map = settings.trackers.by_selection()
    trackers, unknown = resolve_tracker_names(
        request.trackers, tracker_map, settings.trackers.order
    )
    if unknown:
        known = ", ".join(sorted(tracker.name for tracker in tracker_map))
        problems.append(
            f"Unknown tracker(s): {', '.join(unknown)} (known trackers: {known})"
        )
    found = [
        *tracker_profile_problems(trackers, tracker_map, template_selector),
        *(
            f"{tracker}: no NFO template is assigned"
            for tracker in missing_nfo_templates(trackers, tracker_map)
        ),
    ]
    problems.extend(found)
    return [] if unknown or found else trackers
