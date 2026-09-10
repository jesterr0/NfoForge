"""Coverage for a settings write that cannot reach disk."""

from pathlib import Path

import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.exceptions import ConfigError
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


def _refuse_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every config write fail the way a denied path or full disk does.

    Patched at `ConfigManager.save`, which is where `ConfigManager` funnels
    every failure into `ConfigError` -- so both the plain save and `save_as`
    (which calls it) fail for real rather than being stubbed out.
    """

    def _raise(*args: object, **kwargs: object) -> None:
        raise ConfigError("Error saving config file: Permission denied")

    monkeypatch.setattr(ConfigManager, "save", _raise)


def test_a_failed_write_is_reported_and_leaves_settings_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that cannot land must not close the window or crash.

    `_save_all_settings` runs as a Qt slot, so an unguarded `ConfigError` left
    it as an unhandled exception traceback. Staying open is the point: every
    tab has already applied into the live config, and closing would strand
    those values in memory with nothing said about the failure.
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
    into `_apply_settings` after a failure would immediately re-save the whole
    config under the name that just failed.
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
