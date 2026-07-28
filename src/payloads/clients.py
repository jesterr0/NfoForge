from dataclasses import dataclass, field
from typing import TypeAlias

from src.enums.torrent_client import (
    QBittorrentSavePathMode,
    TorrentClientSelection,
)


@dataclass(slots=True)
class TorrentClient:
    enabled: bool = False
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None


@dataclass(slots=True)
class QBittorrentConfig(TorrentClient):
    category: str = ""
    super_seeding: bool = False
    save_path_mode: QBittorrentSavePathMode = QBittorrentSavePathMode.CLIENT_DEFAULT
    save_path_template: str = ""


@dataclass(slots=True)
class DelugeConfig(TorrentClient):
    label: str = ""
    path: str = ""


@dataclass(slots=True)
class RTorrentConfig(TorrentClient):
    label: str = ""
    path: str = ""


@dataclass(slots=True)
class TransmissionConfig(TorrentClient):
    label: str = ""
    path: str = ""


NetworkTorrentClientConfig: TypeAlias = (
    QBittorrentConfig | DelugeConfig | RTorrentConfig | TransmissionConfig
)


@dataclass(slots=True)
class TorrentClientRunOptions:
    """Overrides that apply only to the current processing run."""

    save_path_overrides: dict[TorrentClientSelection, str] = field(default_factory=dict)
