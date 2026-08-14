from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
import pytest

from src.backend.rename_encode import RenameEncodeBackEnd
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.factory import create_processing_context
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection
from src.frontend.stacked_windows.settings.movies_management import (
    MoviesManagementSettings,
)
from src.plugins.api import PluginDefinition
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


def _make_movies_management_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[MoviesManagementSettings, ConfigManager]:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )

    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    fake_settings_window = QWidget()
    widget = MoviesManagementSettings(
        config=manager,
        main_window=None,  # type: ignore[reportArgumentType]
        parent=fake_settings_window,  # type: ignore[reportArgumentType]
    )
    # `_load_saved_settings` (run during __init__) defers unblocking the
    # tracker override widgets' signals via `QTimer.singleShot(1, ...)`.
    # Drain it here so it fires within this test's lifetime instead of
    # leaking a stale pending timer into whichever test happens to pump
    # the Qt event loop next (e.g. via QTest.qWait elsewhere).
    QTest.qWait(20)
    return widget, manager


def test_every_offered_tracker_is_editable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No tracker's title override is locked any more.

    Overrides used to be locked for the trackers that ship a packaged format.
    That lock is gone: a locked template cannot differ between profiles, so a
    user with separate encode and disc profiles could not give a tracker the
    right title for each. ReelFliX stands in for that group -- it ships a
    packaged format and used to be locked to it.
    """
    widget, manager = _make_movies_management_settings(tmp_path, monkeypatch)

    for tracker, override_widget in widget.tracker_override_map.items():
        assert override_widget.enabled_checkbox.isEnabled(), f"{tracker} is locked"
        assert override_widget.over_ride_format_title.isEnabled(), (
            f"{tracker}'s token field is locked"
        )

    combo = widget.tracker_selection
    combo_trackers = {combo.itemData(i) for i in range(combo.count())}
    assert TrackerSelection.REELFLIX in widget.tracker_override_map
    assert TrackerSelection.REELFLIX in combo_trackers

    live_reelflix = manager.settings.trackers.by_selection()[TrackerSelection.REELFLIX]
    assert (
        widget.tracker_override_map[
            TrackerSelection.REELFLIX
        ].over_ride_format_title.text()
        == live_reelflix.mvr_title_token_override
    )


def test_a_formerly_locked_tracker_now_persists_what_the_user_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The save path used to skip these trackers entirely. Now their widget
    contents are what gets stored -- otherwise unlocking the control would
    change nothing."""
    widget, manager = _make_movies_management_settings(tmp_path, monkeypatch)

    reelflix = widget.tracker_override_map[TrackerSelection.REELFLIX]
    reelflix.enabled_checkbox.setChecked(True)
    reelflix.over_ride_format_title.setText("{title_clean} (my own)")

    widget._save_settings()

    live = manager.settings.trackers.by_selection()[TrackerSelection.REELFLIX]
    assert live.mvr_title_override_enabled is True
    assert live.mvr_title_token_override == "{title_clean} (my own)"  # noqa: S105


def test_trackers_without_release_name_offer_no_title_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not offer an override that neither uploader can transmit."""
    widget, manager = _make_movies_management_settings(tmp_path, monkeypatch)

    combo = widget.tracker_selection
    combo_trackers = {combo.itemData(i) for i in range(combo.count())}
    excluded = (TrackerSelection.PASS_THE_POPCORN, TrackerSelection.HUNO)
    for tracker in excluded:
        assert tracker not in widget.tracker_override_map
        assert tracker not in combo_trackers

        # Existing profile values remain inert rather than being destroyed.
        live = manager.settings.trackers.by_selection()[tracker]
        live.mvr_title_override_enabled = True
        live.mvr_title_token_override = "{title_clean} (untouched)"  # noqa: S105

    widget._save_settings()

    for tracker in excluded:
        live = manager.settings.trackers.by_selection()[tracker]
        assert live.mvr_title_override_enabled is True
        assert live.mvr_title_token_override == "{title_clean} (untouched)"  # noqa: S105


def test_plugin_flat_filter_matches_settings_preview_and_runtime_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_movies_management_settings(tmp_path, monkeypatch)

    def append_marker(value: str, *_args: object) -> str:
        return f"{value}Plugin"

    manager.plugin_manager.register(
        "test.flat-filter",
        PluginDefinition(
            display_name="Flat filter test",
            version="1.0.0",
            flat_filters={"append_marker": append_marker},
        ),
        "test",
    )
    manager.settings.general.enable_plugins = True
    token = "{title_clean|append_marker}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential

    preview = widget._update_example(
        token,
        manager.settings.movie.filename_colon_replace,
        True,
        widget.format_file_name_token_example,
    )
    context = create_processing_context(manager.settings, manager.plugin_manager)
    runtime = RenameEncodeBackEnd(context.flat_filters).media_renamer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        mvr_token=token,
        mvr_colon_replacement=manager.settings.movie.filename_colon_replace,
        media_search_payload=EXAMPLE_SEARCH_PAYLOAD,
        title_clean_rules=manager.settings.global_management.title_clean_rules,
        video_dynamic_range=manager.settings.global_management.video_dynamic_range,
        user_tokens=None,
    )

    assert runtime is not None
    assert str(runtime) == preview
    assert "Plugin" in preview


def test_filename_and_title_examples_use_their_own_colon_replace_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The FILENAME example must reflect the FILENAME colon-replace combo
    (`fn_colon_replace`), not the TITLE colon-replace combo, and vice versa.
    Regression test for a bug where the filename preview silently mirrored
    whatever colon setting the title combo had.

    Note: in filename mode, illegal-character sanitization collapses KEEP
    and DELETE to the same (colon-less) output, and collapses all three
    dash-style options to the same dash output, since filenames can't
    contain literal colons or spaces. So the reliable signal that
    distinguishes "used fn_colon_replace" from "used title_colon_replace"
    is the presence/absence of a dash, not the colon itself.

    Both examples are exercised on a single widget instance (rather than one
    per test) to keep this test's overhead low -- constructing this widget
    schedules a deferred `QTimer.singleShot`, and building several of them
    back-to-back has been observed to slow down unrelated timing-sensitive
    tests later in the same run.
    """
    widget, _manager = _make_movies_management_settings(tmp_path, monkeypatch)

    # --- filename example must track fn_colon_replace ---
    widget.format_file_name_token_input.setText("{title}: Extended Cut")

    title_dash_idx = widget.title_colon_replace.findData(ColonReplace.REPLACE_WITH_DASH)
    fn_keep_idx = widget.fn_colon_replace.findData(ColonReplace.KEEP)
    assert title_dash_idx >= 0
    assert fn_keep_idx >= 0

    # title combo wants a dash, filename combo wants to just keep/drop the
    # colon: if the bug is present (filename example uses title's setting)
    # the example would contain a dash; with the fix it must not.
    widget.title_colon_replace.setCurrentIndex(title_dash_idx)
    widget.fn_colon_replace.setCurrentIndex(fn_keep_idx)

    widget._update_file_token_example()

    filename_example = widget.format_file_name_token_example.text()
    assert "-" not in filename_example

    # now flip the filename combo to the dash option (title combo is left
    # on KEEP); the dash must appear since the example should dynamically
    # track fn_colon_replace, not title_colon_replace
    title_keep_idx = widget.title_colon_replace.findData(ColonReplace.KEEP)
    fn_dash_idx = widget.fn_colon_replace.findData(ColonReplace.REPLACE_WITH_DASH)
    assert title_keep_idx >= 0
    assert fn_dash_idx >= 0

    widget.title_colon_replace.setCurrentIndex(title_keep_idx)
    widget.fn_colon_replace.setCurrentIndex(fn_dash_idx)

    filename_example_after = widget.format_file_name_token_example.text()
    assert "-" in filename_example_after

    # --- sibling TITLE example must still track title_colon_replace,
    # regardless of what the filename combo is set to ---
    widget.format_release_title_input.setText("{title}: Extended Cut")

    fn_keep_idx = widget.fn_colon_replace.findData(ColonReplace.KEEP)
    title_delete_idx = widget.title_colon_replace.findData(ColonReplace.DELETE)
    assert fn_keep_idx >= 0
    assert title_delete_idx >= 0

    widget.fn_colon_replace.setCurrentIndex(fn_keep_idx)
    widget.title_colon_replace.setCurrentIndex(title_delete_idx)

    widget._update_title_token_example()

    title_example = widget.format_release_title_example.text()
    assert ":" not in title_example
