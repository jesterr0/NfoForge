from dataclasses import dataclass, field
from typing import Self

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
    specific_params: dict[str, str | bool] = field(default_factory=dict)


class QBittorrentSavePathSettingsError(ValueError):
    """Raised when qBittorrent save-path configuration cannot be parsed."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"Invalid qBittorrent setting: {field}")


@dataclass(frozen=True, slots=True)
class QBittorrentSavePathSettings:
    """Typed view over qBittorrent's persisted save-path parameters."""

    save_path_mode: QBittorrentSavePathMode
    save_path_template: str

    @classmethod
    def from_client(cls, client: TorrentClient) -> Self:
        raw_mode = client.specific_params.get("save_path_mode")
        if not isinstance(raw_mode, str):
            raise QBittorrentSavePathSettingsError("save_path_mode")
        try:
            mode = QBittorrentSavePathMode(raw_mode)
        except ValueError as error:
            raise QBittorrentSavePathSettingsError("save_path_mode") from error

        template = client.specific_params.get("save_path_template")
        if not isinstance(template, str):
            raise QBittorrentSavePathSettingsError("save_path_template")
        if mode is QBittorrentSavePathMode.TEMPLATE and not template.strip():
            raise QBittorrentSavePathSettingsError("save_path_template")

        return cls(
            save_path_mode=mode,
            save_path_template=template,
        )


@dataclass(slots=True)
class TorrentClientRunOptions:
    """Overrides that apply only to the current processing run."""

    save_path_overrides: dict[TorrentClientSelection, str] = field(default_factory=dict)
