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
    BHDTrackerEdit,
    LSTTrackerEdit,
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
    tracker = TrackerSelection.BEYOND_HD
    editor = cast(BHDTrackerEdit, widget._editor_map[tracker])
    editor.api_key.setText("new-api-key")

    manager.settings.trackers.beyond_hd.mvr_title_token_override = "movie-page"  # noqa: S105 - tracker settings field value used as test fixture data, not a credential
    widget._save_settings()

    assert manager.settings.trackers.beyond_hd.api_key == "new-api-key"
    assert (
        manager.settings.trackers.beyond_hd.mvr_title_token_override == "movie-page"  # noqa: S105 - tracker settings field value used as test fixture data, not a credential
    )


def test_reset_loads_tracker_defaults_into_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_tracker_settings(tmp_path, monkeypatch)
    tracker = TrackerSelection.BEYOND_HD
    editor = cast(BHDTrackerEdit, widget._editor_map[tracker])
    editor.api_key.setText("temporary")

    widget.apply_defaults()

    assert editor.api_key.text() == (manager.defaults.trackers.beyond_hd.api_key or "")


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


def _item_for(selector: TrackerSettingsWidget, tracker: TrackerSelection) -> Any:
    for index in range(selector.tracker_list.count()):
        item = selector.tracker_list.item(index)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) is tracker:
            return item
    raise AssertionError(f"{tracker} is not in the list")


def test_locked_trackers_cannot_be_picked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resumed job must not be able to upload to a tracker it already used."""
    _, manager = _make_tracker_settings(tmp_path, monkeypatch)
    locked = TrackerSelection.BEYOND_HD
    manager.settings.trackers.by_selection()[locked].enabled = True
    selector = TrackerSettingsWidget(manager)

    selector.load_from_config(locked_trackers={locked}, persist_enabled=False)

    item = _item_for(selector, locked)
    assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert item.checkState() == Qt.CheckState.Unchecked
    assert locked not in (selector.get_selected_trackers() or [])


def test_preselected_trackers_replace_the_configured_enabled_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resumed job starts from what the job carried, not from the profile."""
    _, manager = _make_tracker_settings(tmp_path, monkeypatch)
    tracker_map = manager.settings.trackers.by_selection()
    wanted = TrackerSelection.LST
    unwanted = TrackerSelection.BEYOND_HD
    tracker_map[wanted].enabled = False
    tracker_map[unwanted].enabled = True
    selector = TrackerSettingsWidget(manager)

    selector.load_from_config(preselected=[wanted], persist_enabled=False)

    assert _item_for(selector, wanted).checkState() == Qt.CheckState.Checked
    assert _item_for(selector, unwanted).checkState() == Qt.CheckState.Unchecked
    assert selector.get_selected_trackers() == [wanted]


def test_a_run_scoped_selection_never_writes_back_to_the_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise re-running an archive disables every tracker it already used.

    Two separate write paths have to stay quiet: the `itemChanged` handler,
    which fires on every toggle, and the explicit sync inside
    `save_editor_settings`.
    """
    _, manager = _make_tracker_settings(tmp_path, monkeypatch)
    tracker_map = manager.settings.trackers.by_selection()
    for tracker in TrackerSelection:
        tracker_map[tracker].enabled = True
    selector = TrackerSettingsWidget(manager)
    selector.load_from_config(preselected=[TrackerSelection.LST], persist_enabled=False)

    # A real state change, not the blocked-signal population above -- and one
    # that actually moves: setting an item to the state it already holds emits
    # nothing, so it would exercise neither write path.
    assert (
        _item_for(selector, TrackerSelection.LST).checkState() == Qt.CheckState.Checked
    )
    _item_for(selector, TrackerSelection.LST).setCheckState(Qt.CheckState.Unchecked)
    assert tracker_map[TrackerSelection.LST].enabled, (
        "the itemChanged handler wrote back"
    )

    selector.save_editor_settings()

    assert all(tracker_map[tracker].enabled for tracker in TrackerSelection)


def test_the_settings_window_selection_still_writes_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`persist_enabled` defaults to on, so nothing else changes behaviour."""
    _, manager = _make_tracker_settings(tmp_path, monkeypatch)
    tracker = TrackerSelection.BEYOND_HD
    manager.settings.trackers.by_selection()[tracker].enabled = True
    selector = TrackerSettingsWidget(manager)
    selector.load_from_config()

    _item_for(selector, tracker).setCheckState(Qt.CheckState.Unchecked)

    assert manager.settings.trackers.by_selection()[tracker].enabled is False


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
    editor = BHDTrackerEdit(manager)

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


def test_lst_freeleech_percentage_loads_and_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manager = _make_tracker_settings(tmp_path, monkeypatch)
    manager.settings.trackers.lst.free = 50
    editor = LSTTrackerEdit(manager)

    editor.load_settings()
    assert editor.free.minimum() == 0
    assert editor.free.maximum() == 100
    assert editor.free.value() == 50

    editor.free.setValue(75)
    editor.save_settings()
    assert manager.settings.trackers.lst.free == 75
