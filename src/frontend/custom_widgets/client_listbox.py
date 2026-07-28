from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QPoint, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.backend.torrent_clients.deluge import DelugeClient
from src.backend.torrent_clients.qbittorrent import QBittorrentClient
from src.backend.torrent_clients.rtorrent import RTorrentClient
from src.backend.torrent_clients.transmission import TransmissionClient
from src.config.config import ConfigManager
from src.enums.torrent_client import (
    QBittorrentSavePathMode,
    TorrentClientSelection,
)
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.frontend.utils import build_h_line
from src.payloads.clients import (
    DelugeConfig,
    NetworkTorrentClientConfig,
    QBittorrentConfig,
    RTorrentConfig,
    TorrentClient,
    TransmissionConfig,
)
from src.payloads.watch_folder import WatchFolder


class ClientTester(Protocol):
    def test(self) -> tuple[bool, str]: ...


ClientTesterFactory = Callable[[], ClientTester]


class ClientTestWorker(QThread):
    job_finished = Signal(tuple)
    job_failed = Signal(str)

    def __init__(
        self,
        test_factory: ClientTesterFactory,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.test_factory = test_factory

    def run(self) -> None:
        try:
            status, message = self.test_factory().test()
            self.job_finished.emit((status, message))
        except Exception as error:
            self.job_failed.emit(f"Error: {error}")


class ClientEditBase(QFrame):
    testing_started = Signal()
    testing_ended = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.client_test_worker: ClientTestWorker | None = None

    def save(self) -> None:
        raise NotImplementedError

    def _start_test(self, test_factory: ClientTesterFactory) -> None:
        self.testing_started.emit()
        self.client_test_worker = ClientTestWorker(test_factory, parent=self)
        self.client_test_worker.job_finished.connect(self._test_worker_finished)
        self.client_test_worker.job_failed.connect(self._test_worker_failed)
        self.client_test_worker.start()

    @Slot(tuple)
    def _test_worker_finished(self, result: tuple[bool, str]) -> None:
        _, message = result
        self.testing_ended.emit()
        QMessageBox.information(self, "Result", message)

    @Slot(str)
    def _test_worker_failed(self, message: str) -> None:
        self.testing_ended.emit()
        QMessageBox.warning(self, "Result", message)

    @staticmethod
    def build_form_layout(text: str, widget: QWidget) -> QFormLayout:
        layout = QFormLayout()
        layout.addWidget(QLabel(text))
        layout.addWidget(widget)
        return layout

    @staticmethod
    def finish_layout(layout: QVBoxLayout, test_button: QPushButton | None) -> None:
        if test_button is not None:
            layout.addWidget(test_button, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(build_h_line((0, 1, 0, 1)))


class FullConnectionClientEditBase(ClientEditBase):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = QLineEdit(parent=self)
        self.host.setToolTip("Client hostname")
        self.port = QSpinBox(self)
        self.port.setToolTip("Client port (0 = disabled)")
        self.port.setRange(0, 65535)
        self.user = QLineEdit(parent=self)
        self.user.setToolTip("Client username")
        self.password = MaskedQLineEdit(parent=self, masked=True)
        self.password.setToolTip("Client password")

    def add_connection_fields(self, layout: QVBoxLayout) -> None:
        layout.addLayout(self.build_form_layout("Host", self.host))
        layout.addLayout(self.build_form_layout("Port", self.port))
        layout.addLayout(self.build_form_layout("User", self.user))
        layout.addLayout(self.build_form_layout("Password", self.password))

    def load_connection(self, config: TorrentClient) -> None:
        self.host.setText(config.host or "")
        self.port.setValue(config.port or 0)
        self.user.setText(config.user or "")
        self.password.setText(config.password or "")

    def save_connection(self, config: TorrentClient) -> None:
        config.host = self.host.text().strip()
        config.port = self.port.value()
        config.user = self.user.text().strip()
        config.password = self.password.text().strip()


class UriClientEditBase(ClientEditBase):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = QLineEdit(parent=self)
        self.host.setToolTip("URI (http://<user>:<password>@127.0.0.1)")

    def add_uri_field(self, layout: QVBoxLayout) -> None:
        layout.addLayout(self.build_form_layout("Host", self.host))


class LabelPathUriClientEditBase(UriClientEditBase):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = QLineEdit(self)
        self.path = QLineEdit(self)
        self.test_button = QPushButton("Test", self)

    def build_layout(self) -> None:
        settings_layout = QVBoxLayout()
        self.add_uri_field(settings_layout)
        settings_layout.addLayout(self.build_form_layout("Label", self.label))
        settings_layout.addLayout(self.build_form_layout("Path", self.path))
        self.finish_layout(settings_layout, self.test_button)
        main_layout = QVBoxLayout(self)
        main_layout.addLayout(settings_layout)


class QBittorrentClientEdit(FullConnectionClientEditBase):
    def __init__(
        self,
        config: QBittorrentConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config

        self.category = QLineEdit(self)
        self.super_seeding = QCheckBox(self)
        self.save_path_mode = QComboBox(self)
        for mode in QBittorrentSavePathMode:
            self.save_path_mode.addItem(str(mode), mode.value)
        self.save_path_mode.setToolTip(
            "Choose whether qBittorrent/category settings, the selected media "
            "location, or a token template determines the save path."
        )
        self.save_path_mode.currentIndexChanged.connect(
            self._sync_save_path_template_state
        )

        self.save_path_template = QLineEdit(self)
        self.save_path_template.setPlaceholderText(
            r"\\server\media\{title_exact} {release_year_parentheses}"
        )
        self.save_path_template.setToolTip(
            "Full path as seen by qBittorrent. Existing FileTokens and "
            "configured FileToken user tokens are supported."
        )

        self.test_button = QPushButton("Test", self)
        self.test_button.clicked.connect(self._test)

        settings_layout = QVBoxLayout()
        self.add_connection_fields(settings_layout)
        settings_layout.addLayout(self.build_form_layout("Category", self.category))
        settings_layout.addLayout(
            self.build_form_layout(
                "Add new torrents in super seeding mode",
                self.super_seeding,
            )
        )
        settings_layout.addLayout(
            self.build_form_layout("Save location mode", self.save_path_mode)
        )
        settings_layout.addLayout(
            self.build_form_layout(
                "Save location template",
                self.save_path_template,
            )
        )
        self.finish_layout(settings_layout, self.test_button)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(settings_layout)

        self.load_connection(config)
        self.category.setText(config.category)
        self.super_seeding.setChecked(config.super_seeding)
        mode_index = self.save_path_mode.findData(config.save_path_mode.value)
        self.save_path_mode.setCurrentIndex(max(mode_index, 0))
        self.save_path_template.setText(config.save_path_template)
        self._sync_save_path_template_state()

    def save(self) -> None:
        self.save_connection(self.config)
        self.config.category = self.category.text().strip()
        self.config.super_seeding = self.super_seeding.isChecked()
        self.config.save_path_mode = QBittorrentSavePathMode(
            str(self.save_path_mode.currentData())
        )
        self.config.save_path_template = self.save_path_template.text().strip()

    @Slot()
    def _sync_save_path_template_state(self) -> None:
        self.save_path_template.setEnabled(
            self.save_path_mode.currentData() == QBittorrentSavePathMode.TEMPLATE.value
        )

    @Slot()
    def _test(self) -> None:
        payload = QBittorrentConfig(
            enabled=True,
            host=self.host.text().strip(),
            port=self.port.value(),
            user=self.user.text().strip(),
            password=self.password.text().strip(),
            category=self.category.text().strip(),
            super_seeding=self.super_seeding.isChecked(),
        )
        self._start_test(lambda: QBittorrentClient(payload))


class DelugeClientEdit(FullConnectionClientEditBase):
    def __init__(
        self,
        config: DelugeConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.label = QLineEdit(self)
        self.path = QLineEdit(self)
        self.test_button = QPushButton("Test", self)
        self.test_button.clicked.connect(self._test)

        settings_layout = QVBoxLayout()
        self.add_connection_fields(settings_layout)
        settings_layout.addLayout(self.build_form_layout("Label", self.label))
        settings_layout.addLayout(self.build_form_layout("Path", self.path))
        self.finish_layout(settings_layout, self.test_button)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(settings_layout)

        self.load_connection(config)
        self.label.setText(config.label)
        self.path.setText(config.path)

    def save(self) -> None:
        self.save_connection(self.config)
        self.config.label = self.label.text().strip()
        self.config.path = self.path.text().strip()

    @Slot()
    def _test(self) -> None:
        payload = DelugeConfig(
            enabled=True,
            host=self.host.text().strip(),
            port=self.port.value(),
            user=self.user.text().strip(),
            password=self.password.text().strip(),
            label=self.label.text().strip(),
            path=self.path.text().strip(),
        )
        self._start_test(lambda: DelugeClient(payload))


class RTorrentClientEdit(LabelPathUriClientEditBase):
    def __init__(
        self,
        config: RTorrentConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.test_button.clicked.connect(self._test)
        self.build_layout()
        self.host.setText(config.host or "")
        self.label.setText(config.label)
        self.path.setText(config.path)

    def save(self) -> None:
        self.config.host = self.host.text().strip()
        self.config.label = self.label.text().strip()
        self.config.path = self.path.text().strip()

    @Slot()
    def _test(self) -> None:
        payload = RTorrentConfig(
            enabled=True,
            host=self.host.text().strip(),
            label=self.label.text().strip(),
            path=self.path.text().strip(),
        )
        self._start_test(lambda: RTorrentClient(payload))


class TransmissionClientEdit(LabelPathUriClientEditBase):
    def __init__(
        self,
        config: TransmissionConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.test_button.clicked.connect(self._test)
        self.build_layout()
        self.host.setText(config.host or "")
        self.label.setText(config.label)
        self.path.setText(config.path)

    def save(self) -> None:
        self.config.host = self.host.text().strip()
        self.config.label = self.label.text().strip()
        self.config.path = self.path.text().strip()

    @Slot()
    def _test(self) -> None:
        payload = TransmissionConfig(
            enabled=True,
            host=self.host.text().strip(),
            label=self.label.text().strip(),
            path=self.path.text().strip(),
        )
        self._start_test(lambda: TransmissionClient(payload))


class WatchFolderClientEdit(ClientEditBase):
    def __init__(
        self,
        config: WatchFolder,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.path = QLineEdit(parent=self)
        self.path.setToolTip("Path to watch directory")
        self.path.setText(str(config.path) if config.path else "")

        settings_layout = QVBoxLayout()
        settings_layout.addLayout(self.build_form_layout("Path", self.path))
        self.finish_layout(settings_layout, None)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(settings_layout)

    def save(self) -> None:
        path = self.path.text().strip()
        self.config.path = Path(path) if path else None


class ClientListWidget(QWidget):
    testing_started = Signal()
    testing_ended = Signal()

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._save_settings_map: dict[TorrentClientSelection, ClientEditBase] = {}

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.tree.verticalScrollBar().setSingleStep(20)
        self.tree.setAutoScroll(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setFrameShape(QFrame.Shape.Box)
        self.tree.setFrameShadow(QFrame.Shadow.Sunken)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)

    def add_items(
        self,
        items: dict[
            TorrentClientSelection,
            NetworkTorrentClientConfig | WatchFolder,
        ],
    ) -> None:
        if self._save_settings_map:
            self.tree.itemChanged.disconnect(self._toggle_client)
            self._save_settings_map.clear()
        self.tree.clear()

        for client, client_info in items.items():
            parent_item = QTreeWidgetItem(self.tree)
            parent_item.setText(0, str(client))
            parent_item.setCheckState(
                0,
                Qt.CheckState.Checked
                if client_info.enabled
                else Qt.CheckState.Unchecked,
            )
            self.add_child_widget(parent_item, client, client_info)

        self.tree.itemChanged.connect(self._toggle_client)

    def add_child_widget(
        self,
        parent_item: QTreeWidgetItem,
        client: TorrentClientSelection,
        client_info: NetworkTorrentClientConfig | WatchFolder,
    ) -> None:
        child_widget = QWidget(self.tree)
        child_layout = QVBoxLayout(child_widget)
        child_layout.setContentsMargins(0, 0, 0, 0)

        if client is TorrentClientSelection.QBITTORRENT and isinstance(
            client_info, QBittorrentConfig
        ):
            editor: ClientEditBase = QBittorrentClientEdit(client_info, child_widget)
        elif client is TorrentClientSelection.DELUGE and isinstance(
            client_info, DelugeConfig
        ):
            editor = DelugeClientEdit(client_info, child_widget)
        elif client is TorrentClientSelection.RTORRENT and isinstance(
            client_info, RTorrentConfig
        ):
            editor = RTorrentClientEdit(client_info, child_widget)
        elif client is TorrentClientSelection.TRANSMISSION and isinstance(
            client_info, TransmissionConfig
        ):
            editor = TransmissionClientEdit(client_info, child_widget)
        elif client is TorrentClientSelection.WATCH_FOLDER and isinstance(
            client_info, WatchFolder
        ):
            editor = WatchFolderClientEdit(client_info, child_widget)
        else:
            raise TypeError(f"Configuration type does not match {client}")

        editor.testing_started.connect(self.testing_started.emit)
        editor.testing_ended.connect(self.testing_ended.emit)
        self._save_settings_map[client] = editor
        child_layout.addWidget(editor)

        child_item = QTreeWidgetItem(parent_item)
        self.tree.setItemWidget(child_item, 0, child_widget)

    def _open_context_menu(self, position: QPoint) -> None:
        menu = QMenu()
        expand_action = QAction("Expand All", self)
        expand_action.triggered.connect(self.expand_all_items)
        menu.addAction(expand_action)
        collapse_action = QAction("Collapse All", self)
        collapse_action.triggered.connect(self.collapse_all_items)
        menu.addAction(collapse_action)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def expand_all_items(self) -> None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item:
                item.setExpanded(True)

    def collapse_all_items(self) -> None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item:
                item.setExpanded(False)

    @Slot(object, int)
    def _toggle_client(self, item: QTreeWidgetItem, column: int) -> None:
        client = TorrentClientSelection(item.text(column))
        config = self.config.settings.torrent_clients.by_selection()[client]
        config.enabled = item.checkState(column) == Qt.CheckState.Checked

    @Slot(object)
    def save_client_info(self, client: TorrentClientSelection) -> None:
        self._save_settings_map[client].save()

    def get_selected_clients(self) -> list[TorrentClientSelection]:
        selected_items: list[TorrentClientSelection] = []
        for index in range(self.tree.topLevelItemCount()):
            parent_item = self.tree.topLevelItem(index)
            if not parent_item:
                continue
            if parent_item.checkState(0) == Qt.CheckState.Checked:
                selected_items.append(TorrentClientSelection(parent_item.text(0)))
        return selected_items

    def clear(self) -> None:
        self.tree.clear()
        self._save_settings_map.clear()
