from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
import src.frontend.stacked_windows.settings.settings as settings_module
from src.frontend.stacked_windows.settings.settings import Settings
from tests.repo_paths import DEFAULT_CONFIG_DIR


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = DEFAULT_CONFIG_DIR
    default_config = defaults / "default_config.toml"
    default_program = defaults / "default_program_conf.toml"
    default_config.write_text(
        (source_defaults / "default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    default_program.write_text(
        (source_defaults / "default_program_conf.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ConfigPaths(
        default_config=default_config,
        default_program=default_program,
        program=tmp_path / "program/conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )


def _make_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Settings, ConfigManager]:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
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
