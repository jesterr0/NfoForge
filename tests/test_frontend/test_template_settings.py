from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget
import pytest

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


def test_warning_swatch_change_live_previews_the_editor_highlight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The embedded editor must recolor from the widget, not from config --
    # config is only written in `_save_settings`, so this is what proves the
    # sample line and the editor stay in sync before the user saves.
    widget, _ = _make_templates_settings(tmp_path, monkeypatch)
    widget.template_selector.text_edit.setPlainText("{{ mi_video_codec }}")
    widget.template_selector._refresh_unknown_tokens()

    widget.warning_syntax_color.update_color(QColor("#00ff00"))
    widget.warning_syntax_color.color_changed.emit(QColor("#00ff00"))

    applied = widget.template_selector.text_edit.highlighter.patterns_colors
    assert applied[-1].color.lower() == "#00ff00"


def test_color_changed_signal_is_wired_to_the_live_preview_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pins the `color_changed.connect(...)` wiring itself, rather than only
    # the effect of manually emitting the signal: a test that only emits
    # `color_changed` and checks the result would stay green even if that
    # connect call were deleted, since nothing forces the emit to travel
    # through the real connection. `SignalInstance.disconnect` returns
    # whether it actually removed a connection, so this fails loudly if the
    # slot was never wired up.
    widget, _ = _make_templates_settings(tmp_path, monkeypatch)
    was_connected = widget.warning_syntax_color.color_changed.disconnect(
        widget._update_warning_entry_text_color
    )
    assert was_connected
    # restore the connection so the widget behaves normally if reused
    widget.warning_syntax_color.color_changed.connect(
        widget._update_warning_entry_text_color
    )


def test_reload_after_cancel_resyncs_the_live_preview_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guards the Cancel/reload desync: `_load_saved_settings` writes the
    # warning pair last, and `_update_warning_entry_text_color` (called
    # before the swatch itself is reset) pushes the live-preview override
    # into the selector using the swatch's PRE-reset color. Without an
    # explicit re-sync after every swatch holds its final value, the
    # embedded editor keeps highlighting with the color the user backed
    # out of.
    widget, _ = _make_templates_settings(tmp_path, monkeypatch)
    widget.template_selector.text_edit.setPlainText("{{ mi_video_codec }}")
    widget.template_selector._refresh_unknown_tokens()

    widget.warning_syntax_color.update_color(QColor("#00ff00"))
    widget.warning_syntax_color.color_changed.emit(QColor("#00ff00"))

    applied = widget.template_selector.text_edit.highlighter.patterns_colors
    assert applied[-1].color.lower() == "#00ff00"

    # Cancel calls `SettingsWindow._reload_settings()`, which emits this.
    widget.load_saved_settings.emit()

    applied = widget.template_selector.text_edit.highlighter.patterns_colors
    assert applied[-1].color.lower() == "#e1401d"
