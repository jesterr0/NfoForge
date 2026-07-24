from pathlib import Path

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.frontend.stacked_windows.settings.templates import TemplatesSettings


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


def _make_templates_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TemplatesSettings, ConfigManager]:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    fake_settings_window = QWidget()
    widget = TemplatesSettings(
        config=manager, main_window=None, parent=fake_settings_window
    )
    return widget, manager


def test_warning_color_loads_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_templates_settings(tmp_path, monkeypatch)
    assert widget.warning_syntax_color.get_hex_color().lower() == "#e1401d"


def test_apply_defaults_restores_warning_color(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_templates_settings(tmp_path, monkeypatch)
    widget.warning_syntax_color.update_color(QColor("#123456"))
    assert widget.warning_syntax_color.get_hex_color().lower() == "#123456"

    widget.apply_defaults()

    assert widget.warning_syntax_color.get_hex_color().lower() == "#e1401d"
