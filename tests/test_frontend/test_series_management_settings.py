from pathlib import Path

from PySide6.QtWidgets import QWidget
import pytest

from src.backend.trackers.media_support import UNSUPPORTED_SERIES_TRACKERS
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
from src.payloads.trackers import TitleOverridePayload
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
    """Movie-only trackers (ReelFliX, PassThePopcorn) can't upload series, so
    they must not be selectable as per-format title override targets on the
    Series Config screen. Every series-capable tracker must still be offered."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    assert UNSUPPORTED_SERIES_TRACKERS, "expected at least one movie-only tracker"
    all_trackers = set(manager.settings.trackers.by_selection().keys())
    expected_offered = all_trackers - UNSUPPORTED_SERIES_TRACKERS

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


def test_required_trackers_are_locked_on_the_series_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aither and LST are REQUIRED and enforce a series format, so their
    widgets show the packaged value with every control disabled, and the
    reason shown to the user claims the enforced format."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    for tracker in (TrackerSelection.AITHER, TrackerSelection.LST):
        packaged = manager.defaults.trackers.by_selection()[tracker]
        for fmt in SUPPORTED_TVR_FORMATS:
            tfo = widget._format_widgets[fmt]["tracker_override_map"][tracker]
            expected = (packaged.tvr_title_overrides or {})[fmt]
            assert tfo.over_ride_format_title.text() == expected.token
            assert not tfo.enabled_checkbox.isEnabled()
            assert not tfo.over_ride_format_title.isEnabled()
            assert not tfo.title_colon_replace.isEnabled()

            reason = tfo.over_ride_format_title.toolTip()
            assert "enforces its own title format" in reason
            assert str(tracker) in reason


def test_required_tracker_with_no_packaged_entry_is_editable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HUNO is REQUIRED but ships no packaged `tvr_title_overrides`, so the
    upload falls back to the global series template.

    Locking that row would take the override away from the user and enforce
    nothing in return, so it must be editable -- the lock follows the packaged
    data, not the tracker-wide declaration. Unticked by default, which is the
    same generated title as before it was editable.
    """
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    packaged = manager.defaults.trackers.by_selection()[TrackerSelection.HUNO]
    for fmt in SUPPORTED_TVR_FORMATS:
        entry = (packaged.tvr_title_overrides or {})[fmt]
        assert not entry.token
        assert not entry.replace_map

    for fmt in SUPPORTED_TVR_FORMATS:
        tfo = widget._format_widgets[fmt]["tracker_override_map"][TrackerSelection.HUNO]
        assert tfo.enabled_checkbox.isEnabled()
        assert tfo.over_ride_format_title.isEnabled()
        assert tfo.title_colon_replace.isEnabled()
        assert not tfo.enabled_checkbox.isChecked()
        assert not tfo.over_ride_format_title.toolTip()


def test_required_tracker_with_no_packaged_entry_persists_a_user_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of being editable: the save path must no longer skip it."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    tfo = widget._format_widgets[EpisodeFormat.STANDARD]["tracker_override_map"][
        TrackerSelection.HUNO
    ]
    tfo.enabled_checkbox.setChecked(True)
    tfo.over_ride_format_title.setText("{title_clean} (user series)")

    widget._save_settings()

    saved = (
        manager.settings.trackers.by_selection()[
            TrackerSelection.HUNO
        ].tvr_title_overrides
        or {}
    )[EpisodeFormat.STANDARD]
    assert saved.enabled
    assert saved.token == "{title_clean} (user series)"  # noqa: S105 - template token string, not a credential


def test_required_tracker_series_overrides_are_not_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale user value for a locked tracker stays in settings untouched:
    the save path must skip REQUIRED trackers rather than writing the
    widget's contents over them."""
    widget, manager = _make_series_management_settings(tmp_path, monkeypatch)

    live = manager.settings.trackers.by_selection()[TrackerSelection.AITHER]
    stale = TitleOverridePayload(
        enabled=True,
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        token="{title_clean} (stale user value)",  # noqa: S106
    )
    live.tvr_title_overrides = dict(live.tvr_title_overrides or {})
    live.tvr_title_overrides[EpisodeFormat.STANDARD] = stale

    widget._save_settings()

    assert (
        live.tvr_title_overrides[EpisodeFormat.STANDARD].token
        == "{title_clean} (stale user value)"  # noqa: S105
    )
