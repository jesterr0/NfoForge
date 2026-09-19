from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMessageBox, QWidget
import pytest

from src.config.config import ConfigManager
from src.config.paths import DEV_PLUGINS_ENV_VAR, ConfigPaths
from src.frontend.stacked_windows.settings.plugins import PluginsSettings
from src.plugins.api import PluginDefinition, TokenReplaceRequest
from tests.repo_paths import build_app_paths


class _FakeSettingsWindow(QWidget):
    re_load_settings = Signal()


def _paths(tmp_path: Path) -> ConfigPaths:
    return build_app_paths(tmp_path)


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
    manager.settings.plugins.post_upload = "missing.notifier"
    manager.settings.plugins.image_host_uploader = "missing.imghost"
    manager.settings.plugins.duplicate_checker = "missing.dupechecker"

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
    assert widget.plugin_post_upload_combo.currentData() == "missing.notifier"
    assert widget.plugin_image_host_uploader_combo.currentData() == "missing.imghost"
    assert widget.plugin_duplicate_checker_combo.currentData() == "missing.dupechecker"

    widget.enable_plugins.setChecked(True)
    widget._save_settings()

    assert manager.settings.general.enable_plugins is True
    assert manager.settings.plugins.token_replacer == "example.tokens"  # noqa: S105 - plugin capability name used as test fixture data, not a credential
    assert manager.settings.plugins.metadata_transformer == "missing.metadata"
    assert manager.settings.plugins.post_upload == "missing.notifier"
    assert manager.settings.plugins.image_host_uploader == "missing.imghost"
    assert manager.settings.plugins.duplicate_checker == "missing.dupechecker"


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
    assert rows["missing.notifier"] == "Configured but unavailable"
    assert rows["missing.imghost"] == "Configured but unavailable"
    assert rows["missing.dupechecker"] == "Configured but unavailable"


def test_plugin_status_explains_that_disabled_plugins_were_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_plugin_settings(tmp_path, monkeypatch)

    assert widget.plugin_status.topLevelItemCount() == 1
    item = widget.plugin_status.topLevelItem(0)
    assert item is not None
    assert item.text(0) == "External plugins disabled"
    assert item.text(3) == "Not loaded"


def test_the_plugins_folder_is_named_on_the_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drop-in installation is the documented route, so the folder it needs
    has to be findable without reading the documentation."""
    widget, manager = _make_plugin_settings(tmp_path, monkeypatch)

    assert widget.plugin_dir_entry.text() == str(manager.paths.plugins)


def test_opening_the_plugins_folder_creates_it_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing creates it until a load runs, so on a fresh installation with
    plugins disabled there would be nothing to open."""
    widget, manager = _make_plugin_settings(tmp_path, monkeypatch)
    opened: list[Path] = []
    monkeypatch.setattr(
        "src.frontend.stacked_windows.settings.plugins.open_explorer",
        opened.append,
    )

    widget._handle_open_plugin_dir_click()

    assert manager.paths.plugins.is_dir()
    assert opened == [manager.paths.plugins]


def test_installing_a_plugin_offers_the_restart_it_needs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plugins are imported at startup, so one that arrives afterwards is on
    disk and inert until NfoForge is restarted."""
    widget, manager = _make_plugin_settings(tmp_path, monkeypatch)
    installed = manager.paths.plugins / "my-plugin"
    monkeypatch.setattr(
        "src.frontend.stacked_windows.settings.plugins.install_from_folder",
        lambda parent, paths: installed,
    )
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(
            lambda parent, title, text, *args, **kwargs: (
                asked.append(text) or QMessageBox.StandardButton.No
            )
        ),
    )

    widget._handle_install_from_folder_click()

    assert asked and "restarted" in asked[0]


def test_declining_the_folder_dialog_asks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, _ = _make_plugin_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.frontend.stacked_windows.settings.plugins.install_from_archive",
        lambda parent, paths: None,
    )

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("nothing was installed, so nothing should be asked")

    monkeypatch.setattr(QMessageBox, "question", staticmethod(refuse))

    widget._handle_install_from_archive_click()


def test_the_development_folders_are_named_when_the_override_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The field above still names where Install writes, and nothing loads there.

    Both facts have to be on screen: a developer who left the variable set in a
    shell profile would otherwise have nothing explaining why the plugin they
    just installed is absent, and the Install button beside the folder still
    writes to it.
    """
    checkouts = tmp_path / "checkouts"
    monkeypatch.setenv(DEV_PLUGINS_ENV_VAR, str(checkouts))

    widget, manager = _make_plugin_settings(tmp_path, monkeypatch)

    assert widget.dev_plugin_dirs_label.isVisibleTo(widget)
    assert str(checkouts) in widget.dev_plugin_dirs_label.text()
    assert DEV_PLUGINS_ENV_VAR in widget.dev_plugin_dirs_label.text()
    assert widget.plugin_dir_entry.text() == str(manager.paths.plugins)


def test_nothing_about_development_folders_is_shown_without_the_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Most users are not developing a plugin and should never see this."""
    widget, _ = _make_plugin_settings(tmp_path, monkeypatch)

    assert not widget.dev_plugin_dirs_label.isVisibleTo(widget)
    assert widget.dev_plugin_dirs_label.text() == ""
