from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMessageBox, QWidget
import pytest
import tomlkit

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.frontend.stacked_windows.settings.general import GeneralSettings
from tests.repo_paths import DEFAULT_CONFIG_DIR


class _FakeSettingsWindow(QWidget):
    """Minimal stand-in for the real `Settings` window: only needs to be a
    QWidget (so it's a valid Qt parent) exposing the `re_load_settings`
    signal that `_swap_config` emits on success."""

    re_load_settings = Signal()


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


def _make_general_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[GeneralSettings, ConfigManager]:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    # `_swap_config` surfaces a modal QMessageBox on failure; stub it out so
    # the test doesn't block waiting for a user click.
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)

    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    broken_profile = paths.user_configs / "broken.toml"
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    document["schema_version"] = 99
    broken_profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    fake_settings_window = _FakeSettingsWindow()
    widget = GeneralSettings(
        config=manager, main_window=None, parent=fake_settings_window
    )
    return widget, manager


def test_swap_config_to_incompatible_profile_does_not_raise_or_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selecting a profile that fails schema validation must not crash the
    slot and must not leave `current_config` pointed at the broken profile;
    the combo box selection should revert to the previously active profile.
    """
    widget, manager = _make_general_settings(tmp_path, monkeypatch)
    assert manager.program.current_config == "test"

    widget.selected_config.setCurrentText("broken")
    widget._swap_config()  # must not raise

    assert manager.program.current_config == "test"
    assert widget.selected_config.currentText() == "test"


def test_swap_config_to_compatible_profile_switches_current_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity check the happy path still works: switching to a valid profile
    updates `current_config` and emits `re_load_settings`."""
    widget, manager = _make_general_settings(tmp_path, monkeypatch)

    # add a second, valid profile alongside "test" and "broken"
    second_profile = manager.paths.user_configs / "second.toml"
    second_profile.write_text(
        manager.paths.default_config.read_text(encoding="utf-8"), encoding="utf-8"
    )
    widget.load_selected_configs()

    reload_calls = []
    widget.settings_window.re_load_settings.connect(lambda: reload_calls.append(True))

    widget.selected_config.setCurrentText("second")
    widget._swap_config()

    assert manager.program.current_config == "second"
    assert reload_calls == [True]
