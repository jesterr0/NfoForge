"""The upload stage's shared duplicate check."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.workflow.decisions import DecisionKind
from nfoforge.core.workflow.upload import (
    DupeCheckResult,
    check_dupes,
    check_dupes_blocking,
    dupe_decision,
)
from nfoforge.enums.tracker_selection import TrackerSelection

AITHER, HUNO, LST = (
    TrackerSelection.AITHER,
    TrackerSelection.HUNO,
    TrackerSelection.LST,
)


def _backend(results: dict[TrackerSelection, tuple[Any, bool, Any]]) -> Any:
    async def dupe_checks(**_kwargs: object) -> dict:
        return results

    return SimpleNamespace(dupe_checks=dupe_checks)


def _check(backend: Any, *trackers: TrackerSelection) -> DupeCheckResult:
    return asyncio.run(check_dupes(backend, ProcessingContext(), list(trackers)))


def test_found_unverified_and_clear_are_told_apart() -> None:
    match = SimpleNamespace(name="The.Movie.2024-OTHER", url="https://x")
    result = _check(
        _backend(
            {
                AITHER: (AITHER, True, [match]),
                HUNO: (HUNO, False, "timed out"),
                LST: (LST, True, []),
            }
        ),
        AITHER,
        HUNO,
        LST,
    )

    assert result.found == [str(AITHER)]
    assert result.matches[str(AITHER)] == [match]
    assert result.unverified == [str(HUNO)]
    assert result.errors[str(HUNO)] == "timed out"
    assert result.clears(LST)
    assert not result.clears(AITHER)
    assert result.blocks_upload()
    assert result.failure is None


def test_a_tracker_the_check_never_reported_on_is_unverified() -> None:
    result = _check(_backend({AITHER: (AITHER, True, [])}), AITHER, HUNO)

    assert result.unverified == [str(HUNO)]
    assert result.errors[str(HUNO)] == "not checked"


def test_a_check_that_falls_over_leaves_everything_unverified() -> None:
    async def broken(**_kwargs: object) -> dict:
        raise ConnectionError("no route to host")

    result = check_dupes_blocking(
        cast(Any, SimpleNamespace(dupe_checks=broken)),
        ProcessingContext(),
        [AITHER, HUNO],
    )

    assert result.failure == "no route to host"
    assert result.unverified == [str(AITHER), str(HUNO)]
    assert result.blocks_upload()


def test_each_tracker_gets_its_own_decision() -> None:
    result = DupeCheckResult(
        found=[str(AITHER)],
        unverified=[str(HUNO)],
        matches={str(AITHER): [SimpleNamespace(name="Other.Release")]},
        errors={str(HUNO): "timed out"},
    )

    found = dupe_decision(AITHER, result)
    failed = dupe_decision(HUNO, result)

    assert found is not None
    assert found.kind is DecisionKind.DUPES_FOUND
    assert found.id == "dupes_found:AITHER"
    assert found.context["matches"] == ["Other.Release"]
    assert failed is not None
    assert failed.kind is DecisionKind.DUPE_CHECK_FAILED
    assert "timed out" in failed.prompt
    assert dupe_decision(LST, result) is None
