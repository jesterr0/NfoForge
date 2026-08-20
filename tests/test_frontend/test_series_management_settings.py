from pathlib import Path

from PySide6.QtWidgets import QWidget
import pytest

from src.backend.trackers.media_support import (
    NO_RELEASE_NAME_FIELD,
    UNSUPPORTED_SERIES_TRACKERS,
)
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.config.tv_tokens import SUPPORTED_TVR_FORMATS
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection
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


def test_movie_only_trackers_are_not_offered_as_series_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only series-capable trackers that accept a name are offered."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    assert UNSUPPORTED_SERIES_TRACKERS, "expected at least one movie-only tracker"
    all_trackers = set(manager.settings.trackers.by_selection().keys())
    expected_offered = (
        all_trackers - UNSUPPORTED_SERIES_TRACKERS - NO_RELEASE_NAME_FIELD
    )

    for fmt, fmt_widgets in widget._format_widgets.items():
        override_trackers = set(fmt_widgets["tracker_override_map"].keys())
        combo = fmt_widgets["tracker_selection"]
        combo_trackers = {combo.itemData(i) for i in range(combo.count())}

        assert override_trackers == expected_offered, fmt
        assert combo_trackers == expected_offered, fmt
        assert override_trackers.isdisjoint(UNSUPPORTED_SERIES_TRACKERS), fmt


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


def test_every_tracker_with_a_title_field_is_editable_on_the_series_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aither and LST ship a packaged series format and used to be locked to
    it on every episode-format tab. Unlocked now, so a profile can carry a
    different series title -- and the row shows the profile's value, not the
    packaged one.
    """
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    for tracker in (TrackerSelection.AITHER, TrackerSelection.LST):
        live = manager.settings.trackers.by_selection()[tracker]
        for fmt in SUPPORTED_TVR_FORMATS:
            tfo = widget._format_widgets[fmt]["tracker_override_map"][tracker]
            expected = (live.tvr_title_overrides or {})[fmt]
            assert tfo.over_ride_format_title.text() == expected.token
            assert tfo.enabled_checkbox.isEnabled()
            assert tfo.over_ride_format_title.isEnabled()
            assert tfo.title_colon_replace.isEnabled()


def test_huno_auto_mode_offers_no_series_title_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HUNO generates its name and has no auto-mode name input to override."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    packaged = manager.defaults.trackers.by_selection()[TrackerSelection.HUNO]
    for fmt in SUPPORTED_TVR_FORMATS:
        entry = (packaged.tvr_title_overrides or {})[fmt]
        assert not entry.token
        assert not entry.replace_map

    for fmt in SUPPORTED_TVR_FORMATS:
        controls = widget._format_widgets[fmt]
        assert TrackerSelection.HUNO not in controls["tracker_override_map"]
        combo = controls["tracker_selection"]
        combo_trackers = {combo.itemData(i) for i in range(combo.count())}
        assert TrackerSelection.HUNO not in combo_trackers


def test_huno_existing_series_override_is_left_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hiding the inert control must not destructively rewrite old profiles."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    live = manager.settings.trackers.by_selection()[TrackerSelection.HUNO]
    assert live.tvr_title_overrides is not None
    existing = live.tvr_title_overrides[EpisodeFormat.STANDARD]
    existing.enabled = True
    existing.token = "{title_clean} (untouched)"  # noqa: S105

    widget._save_settings()

    saved = (live.tvr_title_overrides or {})[EpisodeFormat.STANDARD]
    assert saved.enabled is True
    assert saved.token == "{title_clean} (untouched)"  # noqa: S105


def test_a_formerly_locked_tracker_now_persists_what_the_user_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The save path used to skip these trackers on every episode-format tab.
    Now the widget contents are what gets stored."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    tfo = widget._format_widgets[EpisodeFormat.STANDARD]["tracker_override_map"][
        TrackerSelection.AITHER
    ]
    tfo.enabled_checkbox.setChecked(True)
    tfo.over_ride_format_title.setText("{title_clean} (my own)")

    widget._save_settings()

    live = manager.settings.trackers.by_selection()[TrackerSelection.AITHER]
    assert live.tvr_title_overrides is not None
    stored = live.tvr_title_overrides[EpisodeFormat.STANDARD]
    assert stored.enabled is True
    assert stored.token == "{title_clean} (my own)"  # noqa: S105


def test_override_preview_follows_the_enable_checkbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The series preview mirrors the same enabled/fallback semantics as the
    backend and refreshes immediately when the checkbox is toggled."""
    widget, _manager = _make_series_management_settings(tmp_path, monkeypatch)
    controls = widget._format_widgets[EpisodeFormat.STANDARD]
    override = controls["tracker_override_map"][TrackerSelection.LST]
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        widget, "_update_example", lambda **kwargs: calls.append(kwargs) or ""
    )
    controls["title_token"].setText("GLOBAL")
    override.over_ride_format_title.setText("OVERRIDE")
    override.blockSignals(False)
    override.enabled_checkbox.setChecked(True)

    calls.clear()
    override.enabled_checkbox.setChecked(False)
    assert calls[-1]["token_str"] == "GLOBAL"  # noqa: S105
    assert calls[-1]["override_title_rules"] is None

    override.enabled_checkbox.setChecked(True)
    assert calls[-1]["token_str"] == "OVERRIDE"  # noqa: S105
    assert calls[-1]["override_title_rules"] == (
        override.over_ride_replacement_table.get_replacements()
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
