from pathlib import Path

from PySide6.QtWidgets import QWidget
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.token_replacer import ColonReplace
from src.frontend.stacked_windows.settings.series_management import (
    SeriesManagementSettings,
)
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


def _make_series_management_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SeriesManagementSettings, ConfigManager]:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )

    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    fake_settings_window = QWidget()
    widget = SeriesManagementSettings(
        config=manager, main_window=None, parent=fake_settings_window
    )
    return widget, manager


def test_multi_episode_style_combo_loads_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The combo must reflect whatever is currently saved in the config,
    not just its own default."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    manager.settings.series.multi_episode_style = MultiEpisodeStyle.PREFIXED_RANGE
    widget._load_saved_settings()

    assert (
        MultiEpisodeStyle(widget.multi_episode_style_combo.currentData())
        == MultiEpisodeStyle.PREFIXED_RANGE
    )


def test_multi_episode_style_combo_saves_to_config_and_emits_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selecting a different style in the combo and saving must persist the
    value into `SeriesSettings.multi_episode_style` and must still emit
    `updated_settings_applied` so the Apply flow counter isn't stalled."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    assert manager.settings.series.multi_episode_style != MultiEpisodeStyle.SCENE

    applied_calls = []
    widget.updated_settings_applied.connect(lambda: applied_calls.append(True))

    index = widget.multi_episode_style_combo.findData(MultiEpisodeStyle.SCENE)
    assert index >= 0
    widget.multi_episode_style_combo.setCurrentIndex(index)

    widget._save_settings()

    assert manager.settings.series.multi_episode_style == MultiEpisodeStyle.SCENE
    assert applied_calls == [True]


def test_multi_episode_style_round_trips_through_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saving a non-default style then reloading the widget must show the
    saved style again, proving the control both reads from and writes to
    the config rather than only agreeing with the config by coincidence."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    index = widget.multi_episode_style_combo.findData(MultiEpisodeStyle.DUPLICATE)
    assert index >= 0
    widget.multi_episode_style_combo.setCurrentIndex(index)
    widget._save_settings()
    assert manager.settings.series.multi_episode_style == MultiEpisodeStyle.DUPLICATE

    # simulate reloading the settings page (e.g. Cancel then reopen)
    widget._load_saved_settings()

    assert (
        MultiEpisodeStyle(widget.multi_episode_style_combo.currentData())
        == MultiEpisodeStyle.DUPLICATE
    )


def test_filename_colon_combo_offers_three_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_series_management_settings(tmp_path, monkeypatch)

    labels = [
        widget.fn_colon_replace.itemText(i)
        for i in range(widget.fn_colon_replace.count())
    ]

    assert labels == ["Dot", "Remove", "Dash"]


def test_filename_colon_combo_still_offers_three_after_a_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `load_combo_box` repopulates from the whole enum, so a three-option
    # combo loaded through it silently grows back to five.
    widget, _ = _make_series_management_settings(tmp_path, monkeypatch)

    widget._load_saved_settings()

    assert widget.fn_colon_replace.count() == 3


def test_title_colon_combo_still_offers_five(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_series_management_settings(tmp_path, monkeypatch)

    assert widget.title_colon_replace.count() == 5


def test_filename_colon_combo_round_trips_each_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    for expected in (
        ColonReplace.KEEP,
        ColonReplace.DELETE,
        ColonReplace.REPLACE_WITH_DASH,
    ):
        index = widget.fn_colon_replace.findData(expected)
        assert index > -1, expected
        widget.fn_colon_replace.setCurrentIndex(index)
        widget._save_settings()

        assert manager.settings.series.filename_colon_replace is expected


def test_illegal_chars_checkbox_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_series_management_settings(tmp_path, monkeypatch)

    assert not hasattr(widget, "replace_illegal_chars")


def test_the_six_claim_switches_are_offered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_series_management_settings(tmp_path, monkeypatch)

    assert set(widget.claim_checks) == {
        "edition",
        "frame_size",
        "localization",
        "re_release",
        "remux",
        "hybrid",
    }


def test_claim_switches_grey_out_when_master_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_series_management_settings(tmp_path, monkeypatch)
    widget.claims_master.setChecked(True)
    widget.claim_checks["edition"].setChecked(True)

    widget.claims_master.setChecked(False)

    assert widget.claim_checks["edition"].isEnabled() is False
    assert widget.claim_checks["edition"].isChecked() is True


def test_claim_switches_round_trip_through_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)
    widget.claims_master.setChecked(True)
    widget.claim_checks["localization"].setChecked(False)
    widget.claim_checks["hybrid"].setChecked(True)

    widget._save_settings()

    assert manager.settings.series.claims.enabled is True
    assert manager.settings.series.claims.localization is False
    assert manager.settings.series.claims.hybrid is True


def test_preview_shows_claims_the_example_filename_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The series example filename carried REMUX and nothing else, so five of
    # the six claim switches had nothing to demonstrate on this tab.
    widget, _ = _make_series_management_settings(tmp_path, monkeypatch)
    widget.claims_master.setChecked(True)
    for check in widget.claim_checks.values():
        check.setChecked(True)

    fmt = widget._FORMAT_ORDER[0]
    widget._format_widgets[fmt]["file_token"].setText(
        "{edition}|{frame_size}|{re_release}|{hybrid}|{remux}"
    )

    example = widget._format_widgets[fmt]["file_example"].text()
    for expected in ("Directors.Cut", "IMAX", "REPACK", "HYBRID", "REMUX"):
        assert expected in example, f"{expected} missing from {example!r}"
