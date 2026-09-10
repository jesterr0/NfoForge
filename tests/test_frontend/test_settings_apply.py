"""Coverage for the settings window's Apply path: its gates and its write."""

from pathlib import Path
from typing import cast

import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.torrent_client import QBittorrentSavePathMode, TorrentClientSelection
from src.exceptions import ConfigError
from src.frontend.custom_widgets.client_listbox import QBittorrentClientEdit
from src.frontend.global_signals import GSigs
import src.frontend.stacked_windows.settings.settings as settings_module
from src.frontend.stacked_windows.settings.settings import Settings
from tests.repo_paths import DEFAULT_CONFIG_DIR


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    default_config = defaults / "default_config.toml"
    default_program = defaults / "default_program_conf.toml"
    default_config.write_text(
        (DEFAULT_CONFIG_DIR / "default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    default_program.write_text(
        (DEFAULT_CONFIG_DIR / "default_program_conf.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ConfigPaths(
        default_config=default_config,
        default_program=default_program,
        program=tmp_path / "program/conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )


def _make_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Settings, ConfigManager]:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    widget = Settings(manager, None)  # type: ignore[arg-type]
    return widget, manager


def _capture_criticals(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """Collect the args of every `QMessageBox.critical` the window raises."""
    critical_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        settings_module.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical_calls.append(args),
    )
    return critical_calls


@pytest.mark.parametrize(
    ("mode", "dependency_widget", "config_attribute", "executable_name"),
    (
        (ScreenShotMode.BASIC_SS_GEN, "ffmpeg_widgets", "ffmpeg", "ffmpeg.exe"),
        (
            ScreenShotMode.ADV_SS_COMP,
            "frame_forge_widgets",
            "frame_forge",
            "FrameForge.exe",
        ),
    ),
)
def test_apply_validates_current_mode_and_new_dependency_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: ScreenShotMode,
    dependency_widget: str,
    config_attribute: str,
    executable_name: str,
) -> None:
    widget, manager = _make_settings(tmp_path, monkeypatch)
    executable = tmp_path / executable_name
    executable.touch()

    screenshots = widget.screenshots_settings_content
    screenshots.ss_mode_combo.setCurrentIndex(screenshots.ss_mode_combo.findData(mode))
    screenshots.ss_enabled_btn.setChecked(True)
    dependency_entry = getattr(widget.dependencies_settings_content, dependency_widget)[
        2
    ]
    dependency_entry.setText(str(executable))

    critical_calls = _capture_criticals(monkeypatch)

    widget._apply_settings()

    assert not critical_calls
    assert manager.settings.screenshots.enabled is True
    assert manager.settings.screenshots.mode is mode
    assert getattr(manager.settings.dependencies, config_attribute) == executable


def test_invalid_pending_dependency_blocks_apply_without_discarding_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_settings(tmp_path, monkeypatch)
    missing_ffmpeg = tmp_path / "missing-ffmpeg.exe"

    screenshots = widget.screenshots_settings_content
    screenshots.ss_enabled_btn.setChecked(True)
    dependencies = widget.dependencies_settings_content
    dependencies.ffmpeg_widgets[2].setText(str(missing_ffmpeg))

    critical_calls = _capture_criticals(monkeypatch)

    widget._apply_settings()

    assert len(critical_calls) == 1
    assert "FFMPEG isn't detected" in str(critical_calls[0][2])
    assert manager.settings.screenshots.enabled is False
    assert manager.settings.dependencies.ffmpeg is None
    assert screenshots.ss_enabled_btn.isChecked() is True
    assert dependencies.ffmpeg_widgets[2].text() == str(missing_ffmpeg)
    assert widget.tab_widget.currentWidget() is dependencies


def _qbittorrent_editor(widget: Settings) -> QBittorrentClientEdit:
    """The pending qBittorrent editor behind the Clients tab."""
    return cast(
        QBittorrentClientEdit,
        widget.clients_settings_content.client_widget._editor_map[
            TorrentClientSelection.QBITTORRENT
        ],
    )


def test_template_save_path_mode_without_a_template_blocks_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply must say what is wrong rather than fail the write.

    Pins the gate and what it protects: the live config stays clean, so the
    refusal cannot strand an unsavable value there.
    """
    widget, manager = _make_settings(tmp_path, monkeypatch)
    editor = _qbittorrent_editor(widget)
    editor.save_path_mode.setCurrentIndex(
        editor.save_path_mode.findData(QBittorrentSavePathMode.TEMPLATE.value)
    )
    # whitespace only, the case a `bool(text)` guard would wave through
    editor.save_path_template.setText("   ")

    critical_calls = _capture_criticals(monkeypatch)

    widget._apply_settings()

    live = manager.settings.torrent_clients.qbittorrent
    assert len(critical_calls) == 1
    assert "save location template" in str(critical_calls[0][2])
    assert live.save_path_mode is QBittorrentSavePathMode.CLIENT_DEFAULT
    assert widget.tab_widget.currentWidget() is widget.clients_settings_content
    # the draft survives the refusal, so the fix is a keystroke away
    assert editor.save_path_template.text() == "   "


def test_apply_accepts_a_template_save_path_that_has_a_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard must only block what the config layer would actually reject.

    Pins the other side of the check: Template mode with a template set
    applies and persists, so a guard that fired on the mode alone -- or on an
    unrelated section of the live config -- fails here.
    """
    widget, manager = _make_settings(tmp_path, monkeypatch)
    editor = _qbittorrent_editor(widget)
    editor.save_path_mode.setCurrentIndex(
        editor.save_path_mode.findData(QBittorrentSavePathMode.TEMPLATE.value)
    )
    editor.save_path_template.setText(r"\\server\media\{title_exact}")

    critical_calls = _capture_criticals(monkeypatch)

    widget._apply_settings()

    live = manager.settings.torrent_clients.qbittorrent
    assert not critical_calls
    assert live.save_path_mode is QBittorrentSavePathMode.TEMPLATE
    assert live.save_path_template == r"\\server\media\{title_exact}"


def _refuse_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail every config write the way a denied path or a full disk does.

    Patched at `ConfigManager.save`, where every failure becomes a
    `ConfigError`, so `save_as` (which calls it) fails for real too.
    """

    def _raise(*args: object, **kwargs: object) -> None:
        raise ConfigError("Error saving config file: Permission denied")

    monkeypatch.setattr(ConfigManager, "save", _raise)


def test_a_failed_write_is_reported_and_leaves_settings_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that cannot land must not close the window or crash.

    Staying open is the point: every tab has already applied into the live
    config, so closing would strand those values with nothing said.
    """
    widget, _ = _make_settings(tmp_path, monkeypatch)
    critical_calls = _capture_criticals(monkeypatch)
    _refuse_writes(monkeypatch)

    closed: list[int] = []

    def _on_close() -> None:
        closed.append(1)

    GSigs().settings_close.connect(_on_close)
    try:
        widget._save_all_settings()
    finally:
        GSigs().settings_close.disconnect(_on_close)

    assert len(critical_calls) == 1
    assert "Permission denied" in str(critical_calls[0][2])
    assert not closed


def test_a_save_as_that_cannot_be_written_does_not_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Save As stops at the failed write rather than applying on top of it.

    `save_as` sets the profile it is writing before writing it, so carrying on
    into `_apply_settings` would re-save everything under the name that failed.
    """
    widget, _ = _make_settings(tmp_path, monkeypatch)
    target = tmp_path / "user" / "new-profile.toml"
    monkeypatch.setattr(
        settings_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), ""),
    )
    critical_calls = _capture_criticals(monkeypatch)
    _refuse_writes(monkeypatch)

    applied: list[int] = []
    monkeypatch.setattr(Settings, "_apply_settings", lambda self: applied.append(1))

    widget._save_new_config()

    assert len(critical_calls) == 1
    assert "Permission denied" in str(critical_calls[0][2])
    assert not applied
    assert not target.exists()
