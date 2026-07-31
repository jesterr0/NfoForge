from collections.abc import Callable, Mapping
from typing import TypeAlias

from PySide6.QtWidgets import QWidget

from src.enums.torrent_client import TorrentClientSelection
from src.frontend.custom_widgets.client_listbox import (
    ClientEditBase,
    DelugeClientEdit,
    QBittorrentClientEdit,
    RTorrentClientEdit,
    TransmissionClientEdit,
    WatchFolderClientEdit,
)
from src.payloads.clients import (
    DelugeConfig,
    NetworkTorrentClientConfig,
    QBittorrentConfig,
    RTorrentConfig,
    TransmissionConfig,
)
from src.payloads.watch_folder import WatchFolder

ClientConfig: TypeAlias = NetworkTorrentClientConfig | WatchFolder
ClientEditorFactory: TypeAlias = Callable[[ClientConfig, QWidget], ClientEditBase]


def _qbit_editor(config: ClientConfig, parent: QWidget) -> ClientEditBase:
    if not isinstance(config, QBittorrentConfig):
        raise TypeError("Configuration type does not match QBittorrent")
    return QBittorrentClientEdit(config, parent)


def _deluge_editor(config: ClientConfig, parent: QWidget) -> ClientEditBase:
    if not isinstance(config, DelugeConfig):
        raise TypeError("Configuration type does not match Deluge")
    return DelugeClientEdit(config, parent)


def _rtorrent_editor(config: ClientConfig, parent: QWidget) -> ClientEditBase:
    if not isinstance(config, RTorrentConfig):
        raise TypeError("Configuration type does not match rTorrent")
    return RTorrentClientEdit(config, parent)


def _transmission_editor(config: ClientConfig, parent: QWidget) -> ClientEditBase:
    if not isinstance(config, TransmissionConfig):
        raise TypeError("Configuration type does not match Transmission")
    return TransmissionClientEdit(config, parent)


def _watch_folder_editor(config: ClientConfig, parent: QWidget) -> ClientEditBase:
    if not isinstance(config, WatchFolder):
        raise TypeError("Configuration type does not match Watch Folder")
    return WatchFolderClientEdit(config, parent)


CLIENT_EDITOR_FACTORIES: Mapping[TorrentClientSelection, ClientEditorFactory] = {
    TorrentClientSelection.QBITTORRENT: _qbit_editor,
    TorrentClientSelection.DELUGE: _deluge_editor,
    TorrentClientSelection.RTORRENT: _rtorrent_editor,
    TorrentClientSelection.TRANSMISSION: _transmission_editor,
    TorrentClientSelection.WATCH_FOLDER: _watch_folder_editor,
}


__all__ = ["CLIENT_EDITOR_FACTORIES", "ClientConfig", "ClientEditorFactory"]
