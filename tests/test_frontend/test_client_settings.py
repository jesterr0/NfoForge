from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QWidget
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.torrent_client import TorrentClientSelection
from src.frontend.custom_widgets.client_listbox import QBittorrentClientEdit
from src.frontend.custom_widgets.client_settings import ClientSettingsWidget
from src.frontend.stacked_windows.settings.clients import ClientsSettings


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


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    return ConfigManager("test", _paths(tmp_path))


def test_client_settings_builds_fixed_dual_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    widget = ClientSettingsWidget(config)
    widget.load_from_config()

    assert widget.client_list.count() == len(TorrentClientSelection)
    assert widget.client_stack.count() == len(TorrentClientSelection)
    assert [
        widget.client_list.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(widget.client_list.count())
    ] == list(TorrentClientSelection)
    assert (
        widget.client_list.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
    )
    assert widget.client_list.dragEnabled() is False
    assert widget.client_list.acceptDrops() is False
    assert all(
        not bool(widget.client_list.item(index).flags() & Qt.ItemFlag.ItemIsDragEnabled)
        for index in range(widget.client_list.count())
    )


def test_client_settings_changes_are_transactional_until_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    parent = QWidget()
    settings = ClientsSettings(
        config,
        main_window=cast(Any, None),
        parent=cast(Any, parent),
    )
    editor = cast(
        QBittorrentClientEdit,
        settings.client_widget._editor_map[TorrentClientSelection.QBITTORRENT],
    )
    live_config = config.settings.torrent_clients.qbittorrent
    original_category = live_config.category

    editor.category.setText("Movies")
    assert live_config.category == original_category

    settings._save_settings()

    assert live_config.category == "Movies"
