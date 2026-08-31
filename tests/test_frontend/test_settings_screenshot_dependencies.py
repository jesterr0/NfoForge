from pathlib import Path

import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.screen_shot_mode import ScreenShotMode
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

    critical_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        settings_module.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical_calls.append(args),
    )

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

    critical_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        settings_module.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical_calls.append(args),
    )

    widget._apply_settings()

    assert len(critical_calls) == 1
    assert "FFMPEG isn't detected" in str(critical_calls[0][2])
    assert manager.settings.screenshots.enabled is False
    assert manager.settings.dependencies.ffmpeg is None
    assert screenshots.ss_enabled_btn.isChecked() is True
    assert dependencies.ffmpeg_widgets[2].text() == str(missing_ffmpeg)
    assert widget.tab_widget.currentWidget() is dependencies
