from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
import pytest

from src.backend.rename_files import RenameExecutor, RenamePlan, RenameResult
from src.frontend.global_signals import GSigs
from src.frontend.utils.rename_operation import RenameOperationController


def test_controller_restores_ui_and_emits_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = RenameResult(
        success=True,
        path_mapping={Path("old.mkv"): Path("new.mkv")},
        updated_input_path=Path("new.mkv"),
    )
    monkeypatch.setattr(RenameExecutor, "execute", lambda plan: expected)

    parent = QObject()
    controller = RenameOperationController(parent)
    completed: list[RenameResult] = []
    disabled_states: list[bool] = []
    cleared: list[bool] = []
    on_disabled = disabled_states.append
    on_cleared = lambda: cleared.append(True)
    controller.completed.connect(completed.append)
    GSigs().main_window_set_disabled.connect(on_disabled)
    GSigs().main_window_clear_status_tip.connect(on_cleared)

    try:
        started = controller.start(
            RenamePlan.build({}, input_path=Path("old.mkv")),
            "Renaming media...",
        )
        for _ in range(40):
            if completed and not controller.is_running:
                break
            QTest.qWait(25)
    finally:
        GSigs().main_window_set_disabled.disconnect(on_disabled)
        GSigs().main_window_clear_status_tip.disconnect(on_cleared)

    assert started is True
    assert completed == [expected]
    assert disabled_states == [True, False]
    assert cleared == [True]
    assert controller.is_running is False


def test_controller_restores_ui_after_unexpected_worker_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(plan: RenamePlan) -> RenameResult:
        del plan
        raise RuntimeError("unexpected")

    monkeypatch.setattr(RenameExecutor, "execute", fail)

    parent = QObject()
    controller = RenameOperationController(parent)
    completed: list[RenameResult] = []
    disabled_states: list[bool] = []
    on_disabled = disabled_states.append
    controller.completed.connect(completed.append)
    GSigs().main_window_set_disabled.connect(on_disabled)

    try:
        controller.start(
            RenamePlan.build({}, input_path=Path("old.mkv")),
            "Renaming media...",
        )
        for _ in range(40):
            if completed and not controller.is_running:
                break
            QTest.qWait(25)
    finally:
        GSigs().main_window_set_disabled.disconnect(on_disabled)

    assert len(completed) == 1
    assert completed[0].success is False
    assert "unexpected" in (completed[0].message or "")
    assert disabled_states == [True, False]
    assert controller.is_running is False
