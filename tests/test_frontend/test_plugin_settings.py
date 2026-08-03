from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.frontend.stacked_windows.settings.plugins import PluginsSettings
from src.plugins.api import PluginDefinition, TokenReplaceRequest
from tests.repo_paths import DEFAULT_CONFIG_DIR


class _FakeSettingsWindow(QWidget):
    re_load_settings = Signal()


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


def _make_plugin_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[PluginsSettings, ConfigManager]:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))

    def replace_tokens(request: TokenReplaceRequest) -> str:
        return request.text

    manager.plugin_manager.register(
        "example.tokens",
        PluginDefinition(
            display_name="Example Tokens",
            version="1.2.3",
            description="Example token replacement plugin.",
            token_replacer=replace_tokens,
        ),
        "test source",
    )
    manager.plugin_manager.record_load_issue("broken.plugin", "invalid definition")
    manager.settings.general.enable_plugins = False
    manager.settings.plugins.token_replacer = "example.tokens"  # noqa: S105 - plugin capability name used as test fixture data, not a credential
    manager.settings.plugins.metadata_transformer = "missing.metadata"

    widget = PluginsSettings(
        config=manager,
        main_window=None,  # type: ignore[arg-type]
        parent=_FakeSettingsWindow(),  # type: ignore[arg-type]
    )
    return widget, manager


def test_plugin_settings_preserve_selections_while_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, manager = _make_plugin_settings(tmp_path, monkeypatch)

    assert not widget.plugin_token_replacer_combo.isEnabled()
    assert widget.plugin_token_replacer_combo.currentData() == "example.tokens"
    assert widget.plugin_metadata_transformer_combo.currentData() == "missing.metadata"

    widget.enable_plugins.setChecked(True)
    widget._save_settings()

    assert manager.settings.general.enable_plugins is True
    assert manager.settings.plugins.token_replacer == "example.tokens"  # noqa: S105 - plugin capability name used as test fixture data, not a credential
    assert manager.settings.plugins.metadata_transformer == "missing.metadata"


def test_plugin_status_lists_loaded_failed_and_missing_plugins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_plugin_settings(tmp_path, monkeypatch)
    widget.enable_plugins.setChecked(True)
    widget._load_plugin_status()

    rows = {
        widget.plugin_status.topLevelItem(index).text(  # type: ignore[reportOptionalMemberAccess]
            0
        ): widget.plugin_status.topLevelItem(index).text(3)  # type: ignore[reportOptionalMemberAccess]
        for index in range(widget.plugin_status.topLevelItemCount())
    }

    assert rows["Example Tokens"] == "Loaded"
    assert rows["broken.plugin"] == "Failed: invalid definition"
    assert rows["missing.metadata"] == "Configured but unavailable"


def test_plugin_status_explains_that_disabled_plugins_were_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_plugin_settings(tmp_path, monkeypatch)

    assert widget.plugin_status.topLevelItemCount() == 1
    item = widget.plugin_status.topLevelItem(0)
    assert item is not None
    assert item.text(0) == "External plugins disabled"
    assert item.text(3) == "Not loaded"
