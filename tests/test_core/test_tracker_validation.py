"""Whether the chosen trackers can take a release."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nfoforge.backend.jobs import template_fingerprint
from nfoforge.backend.trackers.media_support import (
    UNIT3D_TRACKERS,
    UNSUPPORTED_SERIES_TRACKERS,
)
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.trackers.validate import (
    job_profile_problems,
    missing_nfo_templates,
    multi_season_pack_warning,
    series_unsupported_trackers,
    stale_template_warnings,
    tracker_profile_problems,
)
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.tracker_selection import TrackerSelection
from tests.job_helpers import populate_context, write_sample_media

AITHER = TrackerSelection.AITHER
HUNO = TrackerSelection.HUNO


def _tracker(*, upload_enabled: bool = True, nfo_template: str = "") -> Any:
    return SimpleNamespace(upload_enabled=upload_enabled, nfo_template=nfo_template)


def _selector(templates: dict[str, str]) -> Any:
    return SimpleNamespace(
        load_templates=lambda: {name: Path(name) for name in templates},
        read_template=lambda name: templates.get(name),
    )


@pytest.fixture
def context(tmp_path: Path) -> ProcessingContext:
    context = ProcessingContext()
    populate_context(context, write_sample_media(tmp_path))
    return context


def test_a_healthy_profile_has_no_problems() -> None:
    problems = tracker_profile_problems(
        [AITHER], {AITHER: _tracker(nfo_template="default")}, _selector({"default": ""})
    )

    assert problems == []


def test_profile_problems_name_each_tracker_and_reason() -> None:
    problems = tracker_profile_problems(
        [AITHER, HUNO, TrackerSelection.LST],
        {
            AITHER: _tracker(upload_enabled=False),
            HUNO: _tracker(nfo_template="deleted"),
        },
        _selector({}),
    )

    assert problems == [
        f"{AITHER}: uploads are disabled in this config",
        f"{HUNO}: NFO template 'deleted' no longer exists",
        f"{TrackerSelection.LST}: not configured in this config",
    ]


def test_no_template_at_all_is_left_to_missing_nfo_templates() -> None:
    tracker_map = {AITHER: _tracker(nfo_template="")}

    assert tracker_profile_problems([AITHER], tracker_map, _selector({})) == []
    assert missing_nfo_templates([AITHER], tracker_map) == [AITHER]


def test_a_template_edited_since_preparing_is_flagged(
    context: ProcessingContext,
) -> None:
    """Frozen NFOs win, so the change must at least be said out loud."""
    context.shared_data.template_fingerprints["default"] = "a-stale-digest"

    warnings = stale_template_warnings(
        context, _selector({"default": "the template changed"})
    )

    assert len(warnings) == 1
    assert "default" in warnings[0]
    assert "saved NFO will be uploaded" in warnings[0]


def test_an_unchanged_or_deleted_template_is_not_flagged(
    context: ProcessingContext,
) -> None:
    body = "the template body"
    context.shared_data.template_fingerprints["default"] = template_fingerprint(body)
    context.shared_data.template_fingerprints["gone"] = "whatever"

    assert stale_template_warnings(context, _selector({"default": body})) == []


def test_a_job_with_no_frozen_templates_is_not_flagged(
    context: ProcessingContext,
) -> None:
    """An unprepared job froze nothing, so there is nothing to go stale."""
    assert stale_template_warnings(context, _selector({"default": "anything"})) == []


def test_job_problems_cover_the_jobs_trackers_and_its_templates(
    context: ProcessingContext,
) -> None:
    context.shared_data.template_fingerprints["default"] = "a-stale-digest"

    problems = job_profile_problems(
        context, {}, _selector({"default": "the template changed"})
    )

    assert problems[0] == f"{AITHER}: not configured in this config"
    assert "changed since this job was prepared" in problems[1]


def test_series_unsupported_trackers_only_applies_to_series() -> None:
    unsupported = next(iter(UNSUPPORTED_SERIES_TRACKERS))

    assert series_unsupported_trackers([unsupported, AITHER], MediaType.SERIES) == [
        unsupported
    ]
    assert series_unsupported_trackers([unsupported], MediaType.MOVIE) == []
    assert series_unsupported_trackers([unsupported], None) == []


def test_multi_season_warning_needs_a_unit3d_tracker(
    context: ProcessingContext,
) -> None:
    assert AITHER in UNIT3D_TRACKERS
    non_unit3d = [TrackerSelection.PASS_THE_POPCORN]
    assert non_unit3d[0] not in UNIT3D_TRACKERS

    assert multi_season_pack_warning(non_unit3d, context) is None
    # a single-file movie is never a multi-season pack
    assert multi_season_pack_warning([AITHER], context) is None
