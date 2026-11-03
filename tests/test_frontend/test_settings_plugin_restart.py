from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget
import pytest

from nfoforge.config.config import ConfigManager
from nfoforge.config.paths import ConfigPaths
import nfoforge.frontend.stacked_windows.settings.settings as settings_module
from nfoforge.frontend.stacked_windows.settings.settings import Settings
from tests.repo_paths import build_app_paths


def _paths(tmp_path: Path) -> ConfigPaths:
    return build_app_paths(tmp_path)


def _make_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Settings, ConfigManager]:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    manager.settings.general.enable_plugins = False

    main_window = QWidget()
    widget = Settings(manager, main_window)  # type: ignore[arg-type]
    return widget, manager


def test_save_all_settings_prompts_and_restarts_when_plugin_flag_toggled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_settings(tmp_path, monkeypatch)

    monkeypatch.setattr(
        settings_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    restart_calls: list[object] = []
    monkeypatch.setattr(
        settings_module,
        "restart_application",
        lambda main_window: restart_calls.append(main_window),
    )

    manager.settings.general.enable_plugins = True
    widget._save_all_settings()

    assert restart_calls == [widget.main_window]


def test_save_all_settings_does_not_prompt_when_plugin_flag_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_settings(tmp_path, monkeypatch)

    question_calls: list[object] = []
    monkeypatch.setattr(
        settings_module.QMessageBox,
        "question",
        lambda *args, **kwargs: (
            question_calls.append(1) or QMessageBox.StandardButton.Yes
        ),
    )
    restart_calls: list[object] = []
    monkeypatch.setattr(
        settings_module,
        "restart_application",
        lambda main_window: restart_calls.append(main_window),
    )

    widget._save_all_settings()

    assert not question_calls
    assert not restart_calls


def test_save_all_settings_skips_restart_when_user_declines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_settings(tmp_path, monkeypatch)

    monkeypatch.setattr(
        settings_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    restart_calls: list[object] = []
    monkeypatch.setattr(
        settings_module,
        "restart_application",
        lambda main_window: restart_calls.append(main_window),
    )

    manager.settings.general.enable_plugins = True
    widget._save_all_settings()

    assert not restart_calls
