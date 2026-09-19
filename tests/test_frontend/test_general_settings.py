from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMessageBox, QWidget
import pytest
import tomlkit

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.media_search_mode import MediaSearchMode
from src.frontend.stacked_windows.settings.general import GeneralSettings
from tests.repo_paths import build_app_paths


class _FakeSettingsWindow(QWidget):
    """Minimal stand-in for the real `Settings` window: only needs to be a
    QWidget (so it's a valid Qt parent) exposing the `re_load_settings`
    signal that `_swap_config` emits on success."""

    re_load_settings = Signal()


def _paths(tmp_path: Path) -> ConfigPaths:
    return build_app_paths(tmp_path)


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


def test_media_search_mode_loads_saves_and_resets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_general_settings(tmp_path, monkeypatch)

    assert (
        MediaSearchMode(widget.media_search_mode_combo.currentData())
        is MediaSearchMode.BOTH
    )

    widget.media_search_mode_combo.setCurrentIndex(
        widget.media_search_mode_combo.findData(MediaSearchMode.TV)
    )
    widget._save_settings()
    assert manager.settings.general.media_search_mode is MediaSearchMode.TV
    manager.save()
    reloaded = ConfigManager("test", manager.paths)
    assert reloaded.settings.general.media_search_mode is MediaSearchMode.TV

    widget.apply_defaults()
    assert (
        MediaSearchMode(widget.media_search_mode_combo.currentData())
        is MediaSearchMode.BOTH
    )


def test_release_group_loads_saves_and_resets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The group tag had no UI at all before this: it round-tripped through
    the config file but could only be set by hand-editing TOML."""
    widget, manager = _make_general_settings(tmp_path, monkeypatch)

    assert widget.release_group_entry.text() == ""

    widget.release_group_entry.setText("  MYGROUP  ")
    widget._save_settings()
    assert manager.settings.general.release_group == "MYGROUP"
    manager.save()
    reloaded = ConfigManager("test", manager.paths)
    assert reloaded.settings.general.release_group == "MYGROUP"

    widget.apply_defaults()
    assert widget.release_group_entry.text() == ""


def test_the_data_folder_row_offers_export_and_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_general_settings(tmp_path, monkeypatch)

    assert widget.export_config_btn.isEnabled()
    assert widget.import_config_btn.isEnabled()


def test_a_successful_import_reloads_the_profile_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An import adds profiles, and a combo still showing the old set would
    offer names that no longer match the directory behind it."""
    widget, _ = _make_general_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.frontend.stacked_windows.settings.general.import_configuration",
        lambda parent, config: SimpleNamespace(
            written=(config.paths.user_configs / "imported.toml",)
        ),
    )
    reloaded: list[bool] = []
    monkeypatch.setattr(widget, "load_selected_configs", lambda: reloaded.append(True))

    widget._handle_import_config_click()

    assert reloaded == [True]


def test_a_cancelled_import_leaves_the_profile_list_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_general_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.frontend.stacked_windows.settings.general.import_configuration",
        lambda parent, config: None,
    )
    reloaded: list[bool] = []
    monkeypatch.setattr(widget, "load_selected_configs", lambda: reloaded.append(True))

    widget._handle_import_config_click()

    assert reloaded == []


def test_replacing_the_active_profile_reloads_manager_and_settings_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_general_settings(tmp_path, monkeypatch)
    active = manager.paths.user_configs / "test.toml"
    imported = tomlkit.parse(active.read_text(encoding="utf-8"))
    imported["general"]["release_group"] = "IMPORTED"  # type: ignore[index]
    active.write_text(tomlkit.dumps(imported), encoding="utf-8")
    monkeypatch.setattr(
        "src.frontend.stacked_windows.settings.general.import_configuration",
        lambda parent, config: SimpleNamespace(written=(active,)),
    )
    reload_calls: list[bool] = []
    widget.settings_window.re_load_settings.connect(lambda: reload_calls.append(True))

    widget._handle_import_config_click()

    assert manager.settings.general.release_group == "IMPORTED"
    assert reload_calls == [True]

    # A later, unrelated save must build on the imported document instead of
    # writing the stale pre-import manager state back over it.
    manager.settings.general.timeout += 1
    manager.save()
    saved = tomlkit.parse(active.read_text(encoding="utf-8"))
    assert saved["general"]["release_group"] == "IMPORTED"  # type: ignore[index]
