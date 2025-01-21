from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QLabel,
    QFormLayout,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QMenu,
    QSpinBox,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal, Slot, QThread
from PySide6.QtGui import QAction

from src.config.config import Config
from src.backend.torrent_clients.qbittorrent import QBittorrentClient
from src.backend.torrent_clients.deluge import DelugeClient
from src.backend.torrent_clients.transmission import TransmissionClient
from src.backend.torrent_clients.rtorrent import RTorrentClient
from src.enums.torrent_client import TorrentClientSelection
from src.payloads.watch_folder import WatchFolder
from src.payloads.clients import TorrentClient
from src.frontend.utils import build_h_line
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit


class ClientTestWorker(QThread):
    job_finished = Signal(tuple)
    job_failed = Signal(str)

    def __init__(
        self,
        test_class: Callable | None = None,
        test_args: tuple | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.test_class = test_class
        self.test_args = test_args

    def run(self) -> None:
        try:
            if self.test_class:
                if self.test_args:
                    test_class = self.test_class(*self.test_args)
                else:
                    test_class = self.test_class()
                status, message = test_class.test()
                self.job_finished.emit((status, message))
        except Exception as e:
            self.job_failed.emit(f"Error: {e}")


class ClientEditBase(QFrame):
    test_client_signal = Signal(object)
    test_client_signal_completed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.specific_params_layout = QVBoxLayout()
        self.specific_params_map: dict[str, QLineEdit] = {}

        self.test_class: Callable | None = None
        self.client_test_worker: ClientTestWorker | None = None
        self.test_client_signal.connect(self._test_client)

    def build_widgets_from_dict(self, data: dict[str, str]) -> None:
        """Builds widgets as needed dynamically"""
        for key, value in data.items():
            widget = QLineEdit(self)
            widget.setText(value)
            self.specific_params_map[key] = widget
            form = self.build_form_layout(key.title().replace("_", " "), widget)
            self.specific_params_layout.addLayout(form)

    @Slot(object)
    def _test_client(self, test_payload: TorrentClient) -> None:
        self.client_test_worker = ClientTestWorker(self.test_class, (test_payload,))
        self.client_test_worker.job_finished.connect(self._test_worker_finished)
        self.client_test_worker.job_failed.connect(self._test_worker_failed)
        self.client_test_worker.start()

    @Slot(tuple)
    def _test_worker_finished(self, result: tuple) -> None:
        _, message = result
        self.test_client_signal_completed.emit()
        QMessageBox.information(self, "Result", message)

    @Slot(str)
    def _test_worker_failed(self, msg: str) -> None:
        self.test_client_signal_completed.emit()
        QMessageBox.warning(self, "Result", msg)

    @staticmethod
    def build_form_layout(text: str, widget: QWidget) -> QFormLayout:
        layout = QFormLayout()
        layout.addWidget(QLabel(text))
        layout.addWidget(widget)
        return layout


class ClientEdit(ClientEditBase):
    def __init__(self, parent=None) -> None:
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
        self.test_client = QPushButton("Test", self)
        self.test_client.clicked.connect(self._test)

        settings_layout = QVBoxLayout()
        settings_layout.addLayout(self.build_form_layout("Host", self.host))
        settings_layout.addLayout(self.build_form_layout("Port", self.port))
        settings_layout.addLayout(self.build_form_layout("User", self.user))
        settings_layout.addLayout(self.build_form_layout("Password", self.password))
        settings_layout.addLayout(self.specific_params_layout)
        settings_layout.addWidget(
            self.test_client, alignment=Qt.AlignmentFlag.AlignRight
        )
        settings_layout.addWidget(build_h_line((0, 1, 0, 1)))

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(settings_layout)
        self.setLayout(main_layout)

    @Slot()
    def _test(self) -> None:
        test_payload = TorrentClient(
            enabled=True,
            host=self.host.text().strip(),
            port=self.port.value(),
            user=self.user.text().strip(),
            password=self.password.text().strip(),
        )
        self.test_client_signal.emit(test_payload)


class ClientEditURI(ClientEditBase):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.host = QLineEdit(parent=self)
        self.host.setToolTip("URI (http://<user>:<password>@127.0.0.1)")
        self.test_client = QPushButton("Test", self)
        self.test_client.clicked.connect(self._test)

        settings_layout = QVBoxLayout()
        settings_layout.addLayout(self.build_form_layout("Host", self.host))
        settings_layout.addLayout(self.specific_params_layout)
        settings_layout.addWidget(
            self.test_client, alignment=Qt.AlignmentFlag.AlignRight
        )
        settings_layout.addWidget(build_h_line((0, 1, 0, 1)))

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(settings_layout)
        self.setLayout(main_layout)

    @Slot()
    def _test(self) -> None:
        test_payload = TorrentClient(
            enabled=True,
            host=self.host.text().strip(),
        )
        self.test_client_signal.emit(test_payload)


class ClientEditWatchFolder(ClientEditBase):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.path = QLineEdit(parent=self)
        self.path.setToolTip("Path to watch directory")

        settings_layout = QVBoxLayout()
        settings_layout.addLayout(self.build_form_layout("Path", self.path))
        settings_layout.addWidget(build_h_line((0, 1, 0, 1)))

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(settings_layout)
        self.setLayout(main_layout)


class ClientListWidget(QWidget):
    testing_started = Signal()
    testing_ended = Signal()

    FULL_CLIENTS = (
        TorrentClientSelection.QBITTORRENT,
        TorrentClientSelection.DELUGE,
    )
    URI_CLIENTS = (
        TorrentClientSelection.RTORRENT,
        TorrentClientSelection.TRANSMISSION,
    )
    CLIENT_CLASS_MAP = {
        TorrentClientSelection.QBITTORRENT: QBittorrentClient,
        TorrentClientSelection.DELUGE: DelugeClient,
        TorrentClientSelection.RTORRENT: RTorrentClient,
        TorrentClientSelection.TRANSMISSION: TransmissionClient,
    }

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)

        self.config = config

        self._save_settings_map = {}

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.tree.verticalScrollBar().setSingleStep(5)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)

    def add_items(
        self, items: dict[TorrentClientSelection, TorrentClient | WatchFolder]
    ) -> None:
        # we'll check if this is empty, if it is we can assume there was never a signal connected
        if self._save_settings_map:
            self.tree.itemChanged.disconnect(self._toggle_client)
            self._save_settings_map.clear()

        # clear tree widget
        self.tree.clear()

        for client, client_info in items.items():
            parent_item = QTreeWidgetItem(self.tree)
            parent_item.setText(0, str(client))

            # add checkbox to the parent item
            parent_item.setCheckState(
                0,
                Qt.CheckState.Checked
                if client_info.enabled
                else Qt.CheckState.Unchecked,
            )

            self.add_child_widgets(parent_item, client, client_info)

        self.tree.itemChanged.connect(self._toggle_client)

    def add_child_widgets(
        self,
        parent_item,
        client: TorrentClientSelection,
        client_info: TorrentClient | WatchFolder,
    ) -> None:
        child_widget = QWidget()
        child_layout = QVBoxLayout(child_widget)
        child_layout.setContentsMargins(0, 0, 0, 0)

        client_widget = None
        if client in self.FULL_CLIENTS and isinstance(client_info, TorrentClient):
            client_widget = ClientEdit()
            client_widget.host.setText(client_info.host)
            client_widget.port.setValue(client_info.port)
            client_widget.user.setText(client_info.user)
            client_widget.password.setText(client_info.password)
            client_widget.build_widgets_from_dict(client_info.specific_params)
            client_widget.test_class = self.CLIENT_CLASS_MAP[client]
            client_widget.test_client_signal.connect(self._test_client)
            client_widget.test_client_signal_completed.connect(self.testing_ended.emit)

        elif client in self.URI_CLIENTS and isinstance(client_info, TorrentClient):
            client_widget = ClientEditURI()
            client_widget.host.setText(client_info.host)
            client_widget.build_widgets_from_dict(client_info.specific_params)
            client_widget.test_class = self.CLIENT_CLASS_MAP[client]
            client_widget.test_client_signal.connect(self._test_client)
            client_widget.test_client_signal_completed.connect(self.testing_ended.emit)

        elif client == TorrentClientSelection.WATCH_FOLDER and isinstance(
            client_info, WatchFolder
        ):
            client_widget = ClientEditWatchFolder()
            client_widget.path.setText(
                str(client_info.path) if client_info.path else ""
            )

        if not client_widget:
            raise AttributeError("Failed to build 'client_widget'")

        self._save_settings_map[client] = client_widget

        child_layout.addWidget(client_widget)

        # add child widget to tree under parent item
        child_item = QTreeWidgetItem(parent_item)
        self.tree.setItemWidget(child_item, 0, child_widget)

    def _open_context_menu(self, position) -> None:
        """Opens the right-click context menu for expanding and collapsing all items"""
        menu = QMenu()

        expand_action = QAction("Expand All", self)
        expand_action.triggered.connect(self.expand_all_items)
        menu.addAction(expand_action)

        collapse_action = QAction("Collapse All", self)
        collapse_action.triggered.connect(self.collapse_all_items)
        menu.addAction(collapse_action)

        # display the context menu at the mouse position
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def expand_all_items(self) -> None:
        """Expand all parent items in the QTreeWidget"""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            item.setExpanded(True)

    def collapse_all_items(self) -> None:
        """Collapse all parent items in the QTreeWidget"""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            item.setExpanded(False)

    @Slot(object)
    def _test_client(self, _: TorrentClient) -> None:
        self.testing_started.emit()

    @Slot(object, int)
    def _toggle_client(self, item: QTreeWidgetItem, column: int) -> None:
        client_attributes: TorrentClient | WatchFolder = self.config.client_map[
            TorrentClientSelection(item.text(column))
        ]
        client_attributes.enabled = (
            True if item.checkState(column) == Qt.CheckState.Checked else False
        )

    @Slot(object)
    def save_client_info(self, client: TorrentClientSelection) -> None:
        client_attributes: TorrentClient | WatchFolder = self.config.client_map[client]

        if client in self.FULL_CLIENTS and isinstance(client_attributes, TorrentClient):
            full_client_widget: ClientEdit = self._save_settings_map[client]
            client_attributes.host = full_client_widget.host.text().strip()
            client_attributes.port = full_client_widget.port.value()
            client_attributes.user = full_client_widget.user.text().strip()
            client_attributes.password = full_client_widget.password.text().strip()
            for key, val_widget in full_client_widget.specific_params_map.items():
                client_attributes.specific_params[key] = val_widget.text().strip()

        elif client in self.URI_CLIENTS and isinstance(
            client_attributes, TorrentClient
        ):
            uri_client_widget: ClientEditURI = self._save_settings_map[client]
            client_attributes.host = uri_client_widget.host.text().strip()
            for key, val_widget in uri_client_widget.specific_params_map.items():
                client_attributes.specific_params[key] = val_widget.text().strip()

        elif client == TorrentClientSelection.WATCH_FOLDER and isinstance(
            client_attributes, WatchFolder
        ):
            watch_folder: ClientEditWatchFolder = self._save_settings_map[client]
            watch_folder_path = watch_folder.path.text().strip()
            client_attributes.path = (
                Path(watch_folder_path) if watch_folder_path else None
            )

    def get_selected_clients(self) -> list[TorrentClientSelection | None]:
        selected_items = []

        for i in range(self.tree.topLevelItemCount()):
            parent_item = self.tree.topLevelItem(i)
            name = parent_item.text(0)
            check_state = parent_item.checkState(0)
            if check_state == Qt.CheckState.Checked:
                selected_items.append(TorrentClientSelection(name))

        return selected_items

    def clear(self) -> None:
        self.tree.clear()
        self._save_settings_map.clear()
