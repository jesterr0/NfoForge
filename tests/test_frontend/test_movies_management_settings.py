from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection
from src.frontend.stacked_windows.settings.movies_management import (
    MoviesManagementSettings,
)


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = Path("runtime/config/defaults")
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
        config=manager, main_window=None, parent=fake_settings_window
    )
    # `_load_saved_settings` (run during __init__) defers unblocking the
    # tracker override widgets' signals via `QTimer.singleShot(1, ...)`.
    # Drain it here so it fires within this test's lifetime instead of
    # leaking a stale pending timer into whichever test happens to pump
    # the Qt event loop next (e.g. via QTest.qWait elsewhere).
    QTest.qWait(20)
    return widget, manager


def test_reelflix_offered_but_ptp_excluded_from_movie_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ReelFliX is a movie tracker and must be offered as a movie title
    override target. PassThePopcorn supports movies but not the override
    feature (strict naming), so it must be excluded."""
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)

    override_trackers = set(widget.tracker_override_map.keys())
    combo = widget.tracker_selection
    combo_trackers = {combo.itemData(i) for i in range(combo.count())}

    assert TrackerSelection.REELFLIX in override_trackers
    assert TrackerSelection.REELFLIX in combo_trackers
    assert TrackerSelection.PASS_THE_POPCORN not in override_trackers
    assert TrackerSelection.PASS_THE_POPCORN not in combo_trackers


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
