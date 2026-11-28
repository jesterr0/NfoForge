from types import SimpleNamespace
from typing import Any, cast

from PySide6.QtWidgets import QMessageBox, QWidget
import pytest

from nfoforge.frontend.utils import release_name_prompt
from nfoforge.frontend.utils.release_name_prompt import confirm_release_names
from nfoforge.plugins.api import (
    PluginDefinition,
    ReleaseNameCheckRequest,
    ReleaseNameIssue,
    ReleaseNameSeverity,
)
from nfoforge.plugins.manager import PluginManager


def _config(severity: ReleaseNameSeverity | None) -> Any:
    def check(_request: ReleaseNameCheckRequest) -> list[ReleaseNameIssue]:
        return [] if severity is None else [ReleaseNameIssue("no PROPER", severity)]

    manager = PluginManager()
    manager.register(
        "rules",
        PluginDefinition(display_name="Rules", version="1", release_name_check=check),
        "test",
    )
    return SimpleNamespace(
        settings=SimpleNamespace(general=SimpleNamespace(enable_plugins=True)),
        plugin_manager=manager,
    )


def _shown(
    monkeypatch: pytest.MonkeyPatch, answer: QMessageBox.StandardButton
) -> list[tuple[str, str]]:
    shown: list[tuple[str, str]] = []

    def warning(_parent: object, title: str, text: str, *_args: object) -> object:
        shown.append((title, text))
        return answer

    monkeypatch.setattr(release_name_prompt.QMessageBox, "warning", warning)
    return shown


def _confirm(severity: ReleaseNameSeverity | None) -> bool:
    return confirm_release_names(
        QWidget(), _config(severity), cast(Any, None), ["Movie.PROPER"]
    )


def test_a_clean_name_goes_ahead_without_a_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown = _shown(monkeypatch, QMessageBox.StandardButton.Ok)

    assert _confirm(None) is True
    assert shown == []


def test_a_blocked_name_stays_on_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    shown = _shown(monkeypatch, QMessageBox.StandardButton.Ok)

    assert _confirm(ReleaseNameSeverity.BLOCK) is False
    assert shown == [("Release Name Not Allowed", "Rules: no PROPER")]


@pytest.mark.parametrize(
    ("answer", "goes_ahead"),
    [
        (QMessageBox.StandardButton.Ok, True),
        (QMessageBox.StandardButton.Cancel, False),
    ],
)
def test_a_warned_name_asks(
    monkeypatch: pytest.MonkeyPatch,
    answer: QMessageBox.StandardButton,
    goes_ahead: bool,
) -> None:
    shown = _shown(monkeypatch, answer)

    assert _confirm(ReleaseNameSeverity.WARN) is goes_ahead
    assert shown[0][0] == "Release Name Warning"
