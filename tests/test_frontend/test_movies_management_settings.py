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


def test_filename_colon_combo_offers_three_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Five ColonReplace members produce at most three distinct filenames.
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)

    labels = [
        widget.fn_colon_replace.itemText(i)
        for i in range(widget.fn_colon_replace.count())
    ]

    assert labels == ["Dot", "Remove", "Dash"]


def test_filename_colon_combo_still_offers_three_after_a_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `load_combo_box` clears the combo and repopulates it from the whole
    # enum, so a filename combo built with three options and then loaded
    # through it silently grows back to five.
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)

    widget._load_saved_settings()

    assert widget.fn_colon_replace.count() == 3


def test_title_colon_combo_still_offers_five(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The title side is untouched by this pass; only the filename side
    # reduces.
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)

    assert widget.title_colon_replace.count() == 5


def test_filename_colon_combo_round_trips_each_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_movies_management_settings(tmp_path, monkeypatch)

    for expected in (
        ColonReplace.KEEP,
        ColonReplace.DELETE,
        ColonReplace.REPLACE_WITH_DASH,
    ):
        index = widget.fn_colon_replace.findData(expected)
        assert index > -1, expected
        widget.fn_colon_replace.setCurrentIndex(index)
        widget._save_settings()

        assert manager.settings.movie.filename_colon_replace is expected


def test_illegal_chars_checkbox_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)

    assert not hasattr(widget, "replace_illegal_chars")


def test_every_claim_switch_is_offered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)

    assert set(widget.claim_checks) == {
        "edition",
        "frame_size",
        "localization",
        "re_release",
        "remux",
        "hybrid",
        "release_group",
    }


def test_claim_switches_grey_out_when_master_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Greyed at their current values rather than hidden or cleared, so
    # turning master back on restores what the user had.
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)
    widget.claims_master.setChecked(True)
    widget.claim_checks["edition"].setChecked(True)

    widget.claims_master.setChecked(False)

    assert widget.claim_checks["edition"].isEnabled() is False
    assert widget.claim_checks["edition"].isChecked() is True


def test_claim_switches_round_trip_through_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_movies_management_settings(tmp_path, monkeypatch)
    widget.claims_master.setChecked(True)
    widget.claim_checks["frame_size"].setChecked(False)
    widget.claim_checks["remux"].setChecked(True)

    widget._save_settings()

    assert manager.settings.movie.claims.enabled is True
    assert manager.settings.movie.claims.frame_size is False
    assert manager.settings.movie.claims.remux is True


def test_preview_shows_claims_the_example_filename_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)
    widget.claims_master.setChecked(True)
    for check in widget.claim_checks.values():
        check.setChecked(True)

    widget.format_file_name_token_input.setText("{edition}|{frame_size}|{hybrid}")

    example = widget.format_file_name_token_example.text()
    assert "Directors.Cut" in example
    assert "IMAX" in example
    assert "HYBRID" in example


def test_preview_drops_a_switched_off_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The switches are inputs to the detector the preview feeds, so ticking
    # one changes the rendered example. This could not work until the token
    # engine stopped re-detecting the claim from the filename downstream.
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)
    widget.claims_master.setChecked(True)
    for check in widget.claim_checks.values():
        check.setChecked(True)
    widget.format_file_name_token_input.setText("{edition}|{frame_size}|{hybrid}")

    # `click()` rather than `setChecked()`: the preview refresh is wired to
    # `clicked`, which only fires on user interaction.
    widget.claim_checks["frame_size"].click()

    example = widget.format_file_name_token_example.text()
    assert "IMAX" not in example
    assert "Directors.Cut" in example


def test_preview_drops_every_category_when_the_master_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_movies_management_settings(tmp_path, monkeypatch)
    widget.claims_master.setChecked(True)
    for check in widget.claim_checks.values():
        check.setChecked(True)
    # `{title_clean}` keeps the render non-empty. `_update_example` leaves
    # the previous example in place when a token string resolves to nothing,
    # so a claims-only token would show stale text rather than an empty one.
    widget.format_file_name_token_input.setText(
        "{title_clean}|{edition}|{frame_size}|{hybrid}"
    )

    widget.claims_master.click()

    example = widget.format_file_name_token_example.text()
    assert "IMAX" not in example
    assert "Directors.Cut" not in example
    assert "HYBRID" not in example


def test_the_preview_shows_the_configured_group_tag_not_the_examples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The example filename ends in -SomeGroup, which stage 1 detects and
    supplies as an override. Without the tag winning over it, a user with a
    group configured saw someone else's in the one place that exists to show
    them their own output.
    """
    widget, manager = _make_movies_management_settings(tmp_path, monkeypatch)
    token = "{release_group}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential

    manager.settings.general.release_group = ""
    assert (
        widget._update_example(
            token,
            manager.settings.movie.filename_colon_replace,
            True,
            widget.format_file_name_token_example,
        )
        == "SomeGroup.mkv"
    )

    manager.settings.general.release_group = "MYGROUP"
    assert (
        widget._update_example(
            token,
            manager.settings.movie.filename_colon_replace,
            True,
            widget.format_file_name_token_example,
        )
        == "MYGROUP.mkv"
    )
