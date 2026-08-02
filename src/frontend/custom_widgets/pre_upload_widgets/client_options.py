from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.torrent_clients.qbittorrent.save_path import (
    get_qbittorrent_save_path_warning,
    resolve_configured_qbittorrent_save_path,
)
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.torrent_client import TorrentClientSelection
from src.exceptions import TrackerClientError


class ClientOptionsSection(QGroupBox):
    """Per-run torrent-client options shown during pre-upload review."""

    def __init__(
        self,
        config: ConfigManager,
        context: ProcessingContext,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("qBittorrent", parent)
        self.config = config
        self.context = context
        self.setObjectName("clientOptionsPage")

        self._configured_path: str | None = None
        self._resolution_error: str | None = None
        self._loading = False

        explanation = QLabel(
            "The destination is interpreted by qBittorrent. It does not need "
            "to exist on this computer, but the qBittorrent host or service "
            "account must be able to access it.",
            self,
            wordWrap=True,
        )

        self.mode_value = QLabel(self)
        self.destination_entry = QLineEdit(self)
        self.destination_entry.setPlaceholderText(
            "Managed by qBittorrent and its category settings"
        )
        self.destination_entry.setToolTip(
            "Full save location as seen by qBittorrent. This value applies "
            "only to the current processing run."
        )
        self.destination_entry.textChanged.connect(self._capture_override)

        self.browse_button = QPushButton("Browse", self)
        self.browse_button.setToolTip("Choose a directory visible on this computer")
        self.browse_button.clicked.connect(self._browse)

        self.reset_button = QPushButton("Reset to Configured Default", self)
        self.reset_button.clicked.connect(self._reset_to_configured)

        destination_layout = QHBoxLayout()
        destination_layout.addWidget(self.destination_entry, stretch=1)
        destination_layout.addWidget(self.browse_button)

        form = QFormLayout()
        form.addRow("Configured mode", self.mode_value)
        form.addRow("Save location", destination_layout)

        self.status_label = QLabel(self, wordWrap=True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addWidget(self.reset_button)
        layout.addStretch()

    def load(self) -> None:
        qbit_config = self.config.settings.torrent_clients.qbittorrent
        self._resolution_error = None
        try:
            self.mode_value.setText(str(qbit_config.save_path_mode))
            self._configured_path = resolve_configured_qbittorrent_save_path(
                self.config.settings,
                self.context,
            )
        except TrackerClientError as error:
            self.mode_value.setText("Invalid configuration")
            self._configured_path = None
            self._resolution_error = str(error)

        override_path = self.context.torrent_client_options.save_path_overrides.get(
            TorrentClientSelection.QBITTORRENT
        )
        self._loading = True
        try:
            self.destination_entry.setText(override_path or self._configured_path or "")
        finally:
            self._loading = False
        self._sync_status()

    def validation_error(self) -> str | None:
        self._capture_override(self.destination_entry.text())
        override_path = self.context.torrent_client_options.save_path_overrides.get(
            TorrentClientSelection.QBITTORRENT
        )
        if not override_path and self._resolution_error:
            return self._resolution_error

        if not override_path and self._configured_path:
            self._loading = True
            try:
                self.destination_entry.setText(self._configured_path)
            finally:
                self._loading = False
            self._sync_status()
        return None

    @Slot(str)
    def _capture_override(self, value: str) -> None:
        if self._loading:
            return
        value = value.strip()
        overrides = self.context.torrent_client_options.save_path_overrides
        if value and value != self._configured_path:
            overrides[TorrentClientSelection.QBITTORRENT] = value
        else:
            overrides.pop(TorrentClientSelection.QBITTORRENT, None)
        self._sync_status()

    @Slot()
    def _browse(self) -> None:
        current_value = self.destination_entry.text().strip()
        initial_directory = current_value
        if not initial_directory:
            input_path = self.context.media_input.input_path
            if input_path:
                initial_directory = str(
                    input_path if input_path.is_dir() else input_path.parent
                )
        selected = QFileDialog.getExistingDirectory(
            parent=self,
            caption="Select qBittorrent Save Location",
            dir=initial_directory,
        )
        if selected:
            self.destination_entry.setText(str(Path(selected)))

    @Slot()
    def _reset_to_configured(self) -> None:
        self.context.torrent_client_options.save_path_overrides.pop(
            TorrentClientSelection.QBITTORRENT,
            None,
        )
        self.load()

    def _sync_status(self) -> None:
        if self._resolution_error and not self.destination_entry.text().strip():
            self.status_label.setText(self._resolution_error)
            return
        override_path = self.context.torrent_client_options.save_path_overrides.get(
            TorrentClientSelection.QBITTORRENT
        )
        effective_path = override_path or self._configured_path
        path_warning = get_qbittorrent_save_path_warning(
            self.config.settings.torrent_clients.qbittorrent.host,
            effective_path,
        )
        if path_warning:
            self.status_label.setText(path_warning)
            return
        if override_path:
            self.status_label.setText(
                "Using a one-run override. qBittorrent automatic torrent "
                "management will be disabled for injected torrents."
            )
        elif self._configured_path:
            self.status_label.setText(
                "Using the configured destination. qBittorrent automatic "
                "torrent management will be disabled for injected torrents."
            )
        else:
            self.status_label.setText(
                "qBittorrent and its category settings will choose the destination."
            )
