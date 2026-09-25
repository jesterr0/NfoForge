"""Whether the chosen trackers can actually take this release.

Each check answers with data -- the trackers or messages at fault -- and
leaves deciding what to do about it to the caller: the wizard asks, a headless
run stops.

A job stores no settings of its own -- credentials, templates and per-tracker
toggles are all read live from whichever profile is active -- so these ask the
config, never the job.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from nfoforge.backend.jobs.assets import template_fingerprint
from nfoforge.backend.template_selector import TemplateSelectorBackEnd
from nfoforge.backend.trackers.media_support import (
    UNIT3D_TRACKERS,
    UNSUPPORTED_SERIES_TRACKERS,
)
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.payloads.series import (
    build_series_release_info,
    describe_multi_season_pack,
)


def tracker_profile_problems(
    trackers: Iterable[TrackerSelection],
    tracker_map: Mapping[TrackerSelection, Any],
    template_selector: TemplateSelectorBackEnd,
) -> list[str]:
    """Ways the *active* profile cannot fully serve `trackers`.

    Deliberately silent about a tracker with no template assigned at all: a
    prepared job uploads a frozen NFO and does not care, and an unprepared one
    is stopped by `missing_nfo_templates`, which names the trackers precisely.
    """
    available_templates = set(template_selector.load_templates())
    problems: list[str] = []
    for tracker in trackers:
        tracker_info = tracker_map.get(tracker)
        if tracker_info is None:
            problems.append(f"{tracker}: not configured in this config")
            continue
        if not tracker_info.upload_enabled:
            problems.append(f"{tracker}: uploads are disabled in this config")
        template = tracker_info.nfo_template
        if template and template not in available_templates:
            problems.append(f"{tracker}: NFO template '{template}' no longer exists")
    return problems


def stale_template_warnings(
    context: ProcessingContext, template_selector: TemplateSelectorBackEnd
) -> list[str]:
    """Name any template that has changed since this job froze its NFOs.

    A prepared job deliberately uploads the NFO it prepared, so an edited
    template does not change what goes out. That is the intended behavior --
    this exists only so the difference is visible rather than silent.
    """
    warnings: list[str] = []
    for name, digest in context.shared_data.template_fingerprints.items():
        current = template_selector.read_template(name=name)
        if current is None:
            continue
        if template_fingerprint(current) != digest:
            warnings.append(
                f"template '{name}' changed since this job was prepared; "
                "its saved NFO will be uploaded, not the new template"
            )
    return warnings


def job_profile_problems(
    context: ProcessingContext,
    tracker_map: Mapping[TrackerSelection, Any],
    template_selector: TemplateSelectorBackEnd,
) -> list[str]:
    """Everything the active profile would do differently for a restored job.

    Anything the profile has since turned off or renamed would otherwise only
    surface as a failure partway through the upload.
    """
    return [
        *tracker_profile_problems(
            context.shared_data.tracker_image_hosts, tracker_map, template_selector
        ),
        *stale_template_warnings(context, template_selector),
    ]


def missing_nfo_templates(
    trackers: Iterable[TrackerSelection],
    tracker_map: Mapping[TrackerSelection, Any],
) -> list[TrackerSelection]:
    """The trackers with no NFO template assigned.

    A tracker with no template is uploaded to with an empty NFO, which is
    worse than not uploading, so an unprepared run must not start with any.
    """
    return [tracker for tracker in trackers if not tracker_map[tracker].nfo_template]


def series_unsupported_trackers(
    trackers: Iterable[TrackerSelection], media_type: MediaType | None
) -> list[TrackerSelection]:
    """The trackers that do not take a release of this media type."""
    if media_type is not MediaType.SERIES:
        return []
    return [tracker for tracker in trackers if tracker in UNSUPPORTED_SERIES_TRACKERS]


def multi_season_pack_warning(
    trackers: Iterable[TrackerSelection], context: ProcessingContext
) -> str | None:
    """Why a multi-season pack would be misfiled, or None if it would not.

    UNIT3D records a single season per torrent, so a pack spanning seasons is
    filed under one of them while its name says "S01-S05". Only asked when a
    UNIT3D tracker is actually chosen, so a single-season release never is.
    """
    if not any(tracker in UNIT3D_TRACKERS for tracker in trackers):
        return None
    return describe_multi_season_pack(build_series_release_info(context.media_input))
