from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
import pytest

from src.backend.trackers.media_support import UNSUPPORTED_SERIES_TRACKERS
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.tracker_management import (
    MTVTrackerEdit,
)
from src.frontend.custom_widgets.tracker_settings import (
    TrackerListDelegate,
    TrackerSettingsWidget,
)
from src.frontend.stacked_windows.settings.trackers import TrackersSettings
from tests.repo_paths import DEFAULT_CONFIG_DIR

# Qt's QWIDGETSIZE_MAX: the `maximumWidth` of a widget nobody has capped.
# PySide6 does not re-export the constant, so it is spelled out here.
_UNBOUNDED_WIDTH = 16777215


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


def _make_tracker_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TrackersSettings, ConfigManager]:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    parent = QWidget()
    return (
        TrackersSettings(
            manager,
            main_window=cast(Any, None),
            parent=cast(Any, parent),
        ),
        manager,
    )


def test_tracker_settings_builds_one_item_and_page_per_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_tracker_settings(tmp_path, monkeypatch)

    assert widget.tracker_list.count() == len(TrackerSelection)
    assert widget.tracker_stack.count() == len(TrackerSelection)
    assert [
        widget.tracker_list.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(widget.tracker_list.count())
    ] == manager.settings.trackers.order


def test_checkbox_changes_are_transactional_until_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_tracker_settings(tmp_path, monkeypatch)
    item = widget.tracker_list.item(0)
    tracker = item.data(Qt.ItemDataRole.UserRole)
    live_info = manager.settings.trackers.by_selection()[tracker]
    original = live_info.enabled

    item.setCheckState(Qt.CheckState.Unchecked if original else Qt.CheckState.Checked)
    assert live_info.enabled is original

    widget._save_settings()
    assert live_info.enabled is not original


def test_reordering_updates_tracker_priority_on_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_tracker_settings(tmp_path, monkeypatch)
    moved = widget.tracker_list.takeItem(0)
    assert moved is not None
    widget.tracker_list.addItem(moved)

    expected_order = widget._current_order()
    widget._save_settings()

    assert manager.settings.trackers.order == expected_order


def test_reload_discards_unapplied_list_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_tracker_settings(tmp_path, monkeypatch)
    item = widget.tracker_list.item(0)
    tracker = item.data(Qt.ItemDataRole.UserRole)
    original = manager.settings.trackers.by_selection()[tracker].enabled

    item.setCheckState(Qt.CheckState.Unchecked if original else Qt.CheckState.Checked)
    widget._load_saved_settings()

    assert widget.tracker_list.item(0).checkState() == (
        Qt.CheckState.Unchecked if not original else Qt.CheckState.Checked
    )
    assert manager.settings.trackers.by_selection()[tracker].enabled is original


def test_editor_values_save_without_overwriting_other_tracker_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_tracker_settings(tmp_path, monkeypatch)
    tracker = TrackerSelection.MORE_THAN_TV
    editor = cast(MTVTrackerEdit, widget._editor_map[tracker])
    editor.api_key.setText("new-api-key")

    manager.settings.trackers.more_than_tv.mvr_title_token_override = "movie-page"  # noqa: S105 - tracker settings field value used as test fixture data, not a credential
    widget._save_settings()

    assert manager.settings.trackers.more_than_tv.api_key == "new-api-key"
    assert (
        manager.settings.trackers.more_than_tv.mvr_title_token_override == "movie-page"  # noqa: S105 - tracker settings field value used as test fixture data, not a credential
    )


def test_reset_loads_tracker_defaults_into_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_tracker_settings(tmp_path, monkeypatch)
    tracker = TrackerSelection.MORE_THAN_TV
    editor = cast(MTVTrackerEdit, widget._editor_map[tracker])
    editor.api_key.setText("temporary")

    widget.apply_defaults()

    assert editor.api_key.text() == (
        manager.defaults.trackers.more_than_tv.api_key or ""
    )


def test_wizard_tracker_selector_keeps_series_filtering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manager = _make_tracker_settings(tmp_path, monkeypatch)
    selector = TrackerSettingsWidget(manager)
    selector.load_from_config(
        unsupported_trackers=UNSUPPORTED_SERIES_TRACKERS,
    )

    for index in range(selector.tracker_list.count()):
        item = selector.tracker_list.item(index)
        assert item is not None
        tracker = item.data(Qt.ItemDataRole.UserRole)
        assert isinstance(tracker, TrackerSelection)
        assert bool(item.flags() & Qt.ItemFlag.ItemIsEnabled) is (
            tracker not in UNSUPPORTED_SERIES_TRACKERS
        )


def test_tracker_editor_uses_open_bounded_form_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The form is laid out flat, and its controls are width-bounded.

    Bounded rather than a specific width: what matters is that a control
    cannot stretch the full width of a maximized settings window, leaving its
    label stranded a screen away from the field it names. The exact number is
    a design choice free to change, so asserting it here only guarantees that
    tuning the layout turns the suite red.
    """
    _, manager = _make_tracker_settings(tmp_path, monkeypatch)
    editor = MTVTrackerEdit(manager)

    assert not hasattr(editor, "common_section")
    assert not hasattr(editor, "options_section")
    # a long announce URL has to wrap rather than widen the label past its cap
    assert editor.announce_url_lbl.wordWrap()
    assert editor.screen_shot_settings is not None
    for widget in (
        editor.announce_url_lbl,
        editor.announce_url,
        editor.screen_shot_settings,
    ):
        assert 0 < widget.maximumWidth() < _UNBOUNDED_WIDTH, widget


def test_tracker_list_exposes_hover_drag_grip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manager = _make_tracker_settings(tmp_path, monkeypatch)
    selector = TrackerSettingsWidget(manager)

    assert isinstance(selector.tracker_list.itemDelegate(), TrackerListDelegate)
    assert selector.tracker_list.hasMouseTracking()
