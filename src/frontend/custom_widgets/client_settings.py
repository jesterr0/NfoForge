from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.config.config import ConfigManager
from src.config.models import TorrentClientSettings
from src.enums.torrent_client import TorrentClientSelection
from src.frontend.custom_widgets.client_editors import CLIENT_EDITOR_FACTORIES
from src.frontend.custom_widgets.client_listbox import ClientEditBase
from src.frontend.custom_widgets.custom_splitter import CustomSplitter


class ClientSettingsWidget(QWidget):
    """Dual-pane client selector and editor shared by client settings."""

    testing_started = Signal()
    testing_ended = Signal()

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config

        self.client_list = QListWidget(self)
        self.client_list.setObjectName("clientSettingsList")
        self.client_list.setFrameShape(QFrame.Shape.Box)
        self.client_list.setFrameShadow(QFrame.Shadow.Sunken)
        self.client_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.client_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.client_list.setDragEnabled(False)
        self.client_list.setAcceptDrops(False)
        self.client_list.setDropIndicatorShown(False)
        self.client_list.setMinimumWidth(190)
        self.client_list.currentRowChanged.connect(self._show_client_page)
        self.client_list.itemChanged.connect(self._client_enabled_changed)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.addWidget(self.client_list, stretch=1)
        left_panel = QWidget(self)
        left_panel.setLayout(left_layout)

        self.client_title = QLabel(self)
        self.client_title.setObjectName("clientSettingsTitle")
        title_font = self.client_title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        self.client_title.setFont(title_font)

        self.client_stack = QStackedWidget(self)
        self.client_stack.setObjectName("clientSettingsStack")

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.addWidget(self.client_title)
        right_layout.addWidget(self.client_stack, stretch=1)
        right_panel = QWidget(self)
        right_panel.setLayout(right_layout)

        self.client_splitter = CustomSplitter(Qt.Orientation.Horizontal, self)
        self.client_splitter.setObjectName("clientSettingsSplitter")
        self.client_splitter.setHandleWidth(16)
        self.client_splitter.setChildrenCollapsible(False)
        self.client_splitter.addWidget(left_panel)
        self.client_splitter.addWidget(right_panel)
        self.client_splitter.setStretchFactor(0, 0)
        self.client_splitter.setStretchFactor(1, 1)
        self.client_splitter.setMinimumHeight(500)

        self._editor_map: dict[TorrentClientSelection, ClientEditBase] = {}
        self._page_map: dict[TorrentClientSelection, int] = {}
        self._build_editor_pages()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.client_splitter)

    def _build_editor_pages(self) -> None:
        client_map = self.config.settings.torrent_clients.by_selection()
        missing = set(TorrentClientSelection) - set(CLIENT_EDITOR_FACTORIES)
        if missing:
            names = ", ".join(str(client) for client in sorted(missing, key=str))
            raise RuntimeError(f"Missing client settings editors: {names}")

        for client in TorrentClientSelection:
            editor = CLIENT_EDITOR_FACTORIES[client](client_map[client], self)
            editor.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            editor.testing_started.connect(self.testing_started.emit)
            editor.testing_ended.connect(self.testing_ended.emit)

            scroll_area = QScrollArea(self.client_stack)
            scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            scroll_area.setWidgetResizable(True)
            scroll_area.setWidget(editor)

            self._editor_map[client] = editor
            self._page_map[client] = self.client_stack.addWidget(scroll_area)

    def load_from_config(self, config: ConfigManager | None = None) -> None:
        """Load row state and editor values while retaining the save target."""
        source_config = config or self.config
        self._load_client_items(source_config.settings.torrent_clients)
        self._load_editor_values(source_config)

    def _load_client_items(self, client_settings: TorrentClientSettings) -> None:
        client_map = client_settings.by_selection()
        self.client_list.blockSignals(True)
        self.client_list.clear()
        for client in TorrentClientSelection:
            item = QListWidgetItem(str(client), self.client_list)
            item.setData(Qt.ItemDataRole.UserRole, client)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
            )
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(
                Qt.CheckState.Checked
                if client_map[client].enabled
                else Qt.CheckState.Unchecked
            )
        self.client_list.blockSignals(False)

        if self.client_list.count():
            self.client_list.setCurrentRow(0)

    def _load_editor_values(self, source_config: ConfigManager) -> None:
        source_clients = source_config.settings.torrent_clients.by_selection()
        target_clients = self.config.settings.torrent_clients.by_selection()
        for client, editor in self._editor_map.items():
            editor.config = source_clients[client]
            editor.load()
            editor.config = target_clients[client]

    @Slot(int)
    def _show_client_page(self, row: int) -> None:
        if row < 0 or row >= self.client_list.count():
            self.client_title.clear()
            return
        item = self.client_list.item(row)
        if item is None:
            self.client_title.clear()
            return
        client = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(client, TorrentClientSelection):
            self.client_title.clear()
            return
        self.client_title.setText(str(client))
        self.client_stack.setCurrentIndex(self._page_map[client])

    @Slot(QListWidgetItem)
    def _client_enabled_changed(self, item: QListWidgetItem) -> None:
        client = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(client, TorrentClientSelection):
            return
        self.config.settings.torrent_clients.by_selection()[client].enabled = (
            item.checkState() == Qt.CheckState.Checked
        )

    def sync_enabled_to_config(self) -> None:
        client_map = self.config.settings.torrent_clients.by_selection()
        for index in range(self.client_list.count()):
            item = self.client_list.item(index)
            if item is None:
                continue
            client = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(client, TorrentClientSelection):
                client_map[client].enabled = item.checkState() == Qt.CheckState.Checked

    def save_editor_settings(self) -> None:
        self.sync_enabled_to_config()
        for editor in self._editor_map.values():
            editor.save()

    def get_selected_clients(self) -> list[TorrentClientSelection]:
        selected: list[TorrentClientSelection] = []
        for index in range(self.client_list.count()):
            item = self.client_list.item(index)
            if item is None:
                continue
            client = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(client, TorrentClientSelection) and (
                item.checkState() == Qt.CheckState.Checked
            ):
                selected.append(client)
        return selected
