from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from nfoforge.core.rename.name_checks import (
    blocking_issues,
    release_name_issues,
    series_release_names,
    warning_issues,
)
from nfoforge.core.rename.series import SeriesRenameTargets
from nfoforge.exceptions import PluginError
from nfoforge.payloads.media_inputs import MediaInputPayload
from nfoforge.plugins.api import (
    PluginDefinition,
    ReleaseNameChecker,
    ReleaseNameCheckRequest,
    ReleaseNameIssue,
    ReleaseNameSeverity,
)
from nfoforge.plugins.manager import PluginManager


def _no_proper(request: ReleaseNameCheckRequest) -> list[ReleaseNameIssue]:
    return [
        ReleaseNameIssue(f"{name} says PROPER; use REPACK")
        for name in request.names
        if "PROPER" in name.split(".")
    ]


def _manager(**checks: ReleaseNameChecker) -> PluginManager:
    manager = PluginManager()
    for plugin_id, check in checks.items():
        manager.register(
            plugin_id,
            PluginDefinition(
                display_name=plugin_id.title(),
                version="1.0.0",
                release_name_check=check,
            ),
            "test",
        )
    return manager


def _config(manager: PluginManager, *, enabled: bool = True) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(general=SimpleNamespace(enable_plugins=enabled)),
        plugin_manager=manager,
    )


def _issues(manager: PluginManager, *names: str, enabled: bool = True) -> list[str]:
    return [
        str(issue)
        for issue in release_name_issues(
            _config(manager, enabled=enabled), cast(Any, None), names
        )
    ]


def test_a_release_name_check_alone_is_a_capability() -> None:
    assert _manager(hallowed=_no_proper).get("hallowed") is not None


def test_a_release_name_check_must_be_callable() -> None:
    with pytest.raises(PluginError, match="release_name_check must be callable"):
        _manager(hallowed=cast(Any, "nope"))


def test_issues_name_the_plugin_that_raised_them() -> None:
    manager = _manager(hallowed=_no_proper)

    assert _issues(manager, "Movie.2024.PROPER.1080p-GRP") == [
        "Hallowed: Movie.2024.PROPER.1080p-GRP says PROPER; use REPACK"
    ]
    assert _issues(manager, "Movie.2024.REPACK.1080p-GRP") == []


def test_every_plugins_check_runs() -> None:
    manager = _manager(
        first=lambda _request: [ReleaseNameIssue("one")],
        second=lambda _request: [
            ReleaseNameIssue("two", ReleaseNameSeverity.WARN),
        ],
    )

    issues = release_name_issues(_config(manager), cast(Any, None), ["Movie"])

    assert blocking_issues(issues) == ["First: one"]
    assert warning_issues(issues) == ["Second: two"]


def test_no_check_runs_with_plugins_turned_off() -> None:
    assert _issues(_manager(hallowed=_no_proper), "A.PROPER", enabled=False) == []


def test_names_reach_the_check_once_and_without_blanks() -> None:
    seen: list[tuple[str, ...]] = []

    def record(request: ReleaseNameCheckRequest) -> list[ReleaseNameIssue]:
        seen.append(request.names)
        return []

    _issues(_manager(rec=record), "A", "", "B", "A")

    assert seen == [("A", "B")]


def test_a_crashing_check_blocks() -> None:
    def crash(_request: ReleaseNameCheckRequest) -> list[ReleaseNameIssue]:
        raise RuntimeError("boom")

    issues = release_name_issues(
        _config(_manager(broken=crash)), cast(Any, None), ["Movie"]
    )

    assert len(blocking_issues(issues)) == 1
    assert "RuntimeError: boom" in blocking_issues(issues)[0]


def test_a_check_answering_in_the_wrong_shape_blocks() -> None:
    manager = _manager(wrong=cast(Any, lambda _request: "PROPER is not allowed"))

    issues = release_name_issues(_config(manager), cast(Any, None), ["Movie"])

    assert len(blocking_issues(issues)) == 1
    assert "sequence of ReleaseNameIssue" in blocking_issues(issues)[0]


def test_a_packs_names_include_what_the_rename_leaves_alone(tmp_path: Path) -> None:
    pack = tmp_path / "Show.S01.1080p-GRP"
    pack.mkdir()
    first = pack / "Show.S01E01.1080p-GRP.mkv"
    second = pack / "Show.S01E02.PROPER.1080p-GRP.mkv"
    media_input = MediaInputPayload(input_path=pack, file_list=[first, second])
    renamed = pack.with_name("Show.S01.REPACK.1080p-GRP")
    targets = SeriesRenameTargets(
        files={first: first.with_name("Show.S01E01.REPACK.1080p-GRP.mkv")},
        directories={pack: renamed},
    )

    assert series_release_names(media_input, targets) == (
        "Show.S01.REPACK.1080p-GRP",
        "Show.S01E01.REPACK.1080p-GRP",
        "Show.S01E02.PROPER.1080p-GRP",
    )
