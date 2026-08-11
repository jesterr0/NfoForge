import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from src.backend.process import ProcessBackEnd
from src.config.config import ConfigManager
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.tracker_search_result import TrackerSearchResult
from src.plugins.api import DuplicateCheckRequest, PluginDefinition
from src.plugins.manager import PluginManager


def _backend(
    *,
    enable_plugins: bool = True,
    plugin_id: str | None,
    manager: PluginManager,
    timeout: int = 30,
) -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        ConfigManager,
        SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(enable_plugins=enable_plugins, timeout=timeout),
                plugins=SimpleNamespace(duplicate_checker=plugin_id),
            ),
            plugin_manager=manager,
        ),
    )
    return backend


def _movie_input() -> MediaInputPayload:
    file_path = Path("Movie.2024.1080p.WEB-DL.H.264-GRP.mkv")
    return MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.MOVIE,
        file_list=[file_path],
    )


# ---------------------------------------------------------------------------
# `ProcessBackEnd._run_duplicate_checker_plugin` in isolation
# ---------------------------------------------------------------------------


def test_returns_empty_when_no_plugin_is_configured() -> None:
    manager = PluginManager()
    backend = _backend(plugin_id=None, manager=manager)

    result = asyncio.run(
        backend._run_duplicate_checker_plugin(
            TrackerSelection.PASS_THE_POPCORN, _movie_input(), MediaSearchPayload()
        )
    )

    assert result == []


def test_returns_empty_when_the_configured_plugin_is_unavailable() -> None:
    manager = PluginManager()
    backend = _backend(plugin_id="missing.plugin", manager=manager)

    result = asyncio.run(
        backend._run_duplicate_checker_plugin(
            TrackerSelection.PASS_THE_POPCORN, _movie_input(), MediaSearchPayload()
        )
    )

    assert result == []


def test_returns_the_plugins_results() -> None:
    hit = TrackerSearchResult(name="Existing.Release-GROUP")
    manager = PluginManager()
    manager.register(
        "test.dupechecker",
        PluginDefinition(
            display_name="test.dupechecker",
            version="1.0.0",
            duplicate_checker=lambda request: [hit],
        ),
        "test",
    )
    backend = _backend(plugin_id="test.dupechecker", manager=manager)

    result = asyncio.run(
        backend._run_duplicate_checker_plugin(
            TrackerSelection.PASS_THE_POPCORN, _movie_input(), MediaSearchPayload()
        )
    )

    assert result == [hit]


def test_a_raising_plugin_is_logged_and_returns_empty() -> None:
    def explodes(request: DuplicateCheckRequest) -> list[TrackerSearchResult]:
        raise RuntimeError("search backend unreachable")

    manager = PluginManager()
    manager.register(
        "test.explode",
        PluginDefinition(
            display_name="test.explode", version="1.0.0", duplicate_checker=explodes
        ),
        "test",
    )
    backend = _backend(plugin_id="test.explode", manager=manager)

    result = asyncio.run(
        backend._run_duplicate_checker_plugin(
            TrackerSelection.PASS_THE_POPCORN, _movie_input(), MediaSearchPayload()
        )
    )

    assert result == []


# ---------------------------------------------------------------------------
# `ProcessBackEnd.dupe_checks` -- the merge rule
# ---------------------------------------------------------------------------


async def _stub_dupe_ptp_success(
    *, tracker_sel: TrackerSelection, file_input: Path, media_search_payload: object
) -> tuple[TrackerSelection, bool, list[TrackerSearchResult]]:
    return (tracker_sel, True, [TrackerSearchResult(name="Built-in hit")])


async def _stub_dupe_ptp_failure(
    *, tracker_sel: TrackerSelection, file_input: Path, media_search_payload: object
) -> tuple[TrackerSelection, bool, str]:
    return (tracker_sel, False, "PTP API key missing")


def test_plugin_results_are_appended_when_the_built_in_check_succeeded() -> None:
    plugin_hit = TrackerSearchResult(name="Plugin hit")
    manager = PluginManager()
    manager.register(
        "test.dupechecker",
        PluginDefinition(
            display_name="test.dupechecker",
            version="1.0.0",
            duplicate_checker=lambda request: [plugin_hit],
        ),
        "test",
    )
    backend = _backend(plugin_id="test.dupechecker", manager=manager)
    backend._dupe_ptp = _stub_dupe_ptp_success  # type: ignore[method-assign]

    results = asyncio.run(
        backend.dupe_checks(
            processing_queue=[TrackerSelection.PASS_THE_POPCORN],
            media_input_payload=_movie_input(),
            media_search_payload=MediaSearchPayload(),
        )
    )

    _, success, data = results[TrackerSelection.PASS_THE_POPCORN]
    assert success is True
    assert isinstance(data, list)
    assert [item.name for item in data] == ["Built-in hit", "Plugin hit"]


def test_plugin_results_are_not_merged_when_the_built_in_check_failed() -> None:
    manager = PluginManager()
    manager.register(
        "test.dupechecker",
        PluginDefinition(
            display_name="test.dupechecker",
            version="1.0.0",
            duplicate_checker=lambda request: [TrackerSearchResult(name="Plugin hit")],
        ),
        "test",
    )
    backend = _backend(plugin_id="test.dupechecker", manager=manager)
    backend._dupe_ptp = _stub_dupe_ptp_failure  # type: ignore[method-assign]

    results = asyncio.run(
        backend.dupe_checks(
            processing_queue=[TrackerSelection.PASS_THE_POPCORN],
            media_input_payload=_movie_input(),
            media_search_payload=MediaSearchPayload(),
        )
    )

    assert results[TrackerSelection.PASS_THE_POPCORN] == (
        TrackerSelection.PASS_THE_POPCORN,
        False,
        "PTP API key missing",
    )


def test_an_empty_plugin_contribution_changes_nothing() -> None:
    manager = PluginManager()
    manager.register(
        "test.dupechecker",
        PluginDefinition(
            display_name="test.dupechecker",
            version="1.0.0",
            duplicate_checker=lambda request: [],
        ),
        "test",
    )
    backend = _backend(plugin_id="test.dupechecker", manager=manager)
    backend._dupe_ptp = _stub_dupe_ptp_success  # type: ignore[method-assign]

    results = asyncio.run(
        backend.dupe_checks(
            processing_queue=[TrackerSelection.PASS_THE_POPCORN],
            media_input_payload=_movie_input(),
            media_search_payload=MediaSearchPayload(),
        )
    )

    _, success, data = results[TrackerSelection.PASS_THE_POPCORN]
    assert success is True
    assert [item.name for item in data] == ["Built-in hit"]  # type: ignore[reportAttributeAccessIssue]


def test_no_plugin_configured_leaves_built_in_results_untouched() -> None:
    manager = PluginManager()
    backend = _backend(plugin_id=None, manager=manager)
    backend._dupe_ptp = _stub_dupe_ptp_success  # type: ignore[method-assign]

    results = asyncio.run(
        backend.dupe_checks(
            processing_queue=[TrackerSelection.PASS_THE_POPCORN],
            media_input_payload=_movie_input(),
            media_search_payload=MediaSearchPayload(),
        )
    )

    _, success, data = results[TrackerSelection.PASS_THE_POPCORN]
    assert success is True
    assert [item.name for item in data] == ["Built-in hit"]  # type: ignore[reportAttributeAccessIssue]
