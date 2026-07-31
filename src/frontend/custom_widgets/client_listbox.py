from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.backend.torrent_clients.deluge import DelugeClient
from src.backend.torrent_clients.qbittorrent import QBittorrentClient
from src.backend.torrent_clients.rtorrent import RTorrentClient
from src.backend.torrent_clients.transmission import TransmissionClient
from src.enums.torrent_client import QBittorrentSavePathMode
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.payloads.clients import (
    DelugeConfig,
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
    MAX_CONTROL_WIDTH = 650
    MAX_LABEL_WIDTH = 280

    testing_started = Signal()
    testing_ended = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config: TorrentClient | WatchFolder
        self.client_test_worker: ClientTestWorker | None = None

    def save(self) -> None:
        raise NotImplementedError

    def load(self) -> None:
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

    @classmethod
    def build_form_layout(cls) -> QFormLayout:
        layout = QFormLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(6)
        return layout

    @classmethod
    def add_form_row(
        cls, layout: QFormLayout, label_text: str, widget: QWidget
    ) -> None:
        label = QLabel(label_text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setMaximumWidth(cls.MAX_LABEL_WIDTH)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        widget.setMaximumWidth(cls.MAX_CONTROL_WIDTH)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addRow(label, widget)
        layout.setAlignment(widget, Qt.AlignmentFlag.AlignTop)

    def finish_layout(
        self, layout: QFormLayout, test_button: QPushButton | None
    ) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        main_layout.addLayout(layout)
        if test_button is not None:
            main_layout.addWidget(
                test_button,
                alignment=Qt.AlignmentFlag.AlignRight,
            )


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

    def add_connection_fields(self, layout: QFormLayout) -> None:
        self.add_form_row(layout, "Host", self.host)
        self.add_form_row(layout, "Port", self.port)
        self.add_form_row(layout, "User", self.user)
        self.add_form_row(layout, "Password", self.password)

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

    def add_uri_field(self, layout: QFormLayout) -> None:
        self.add_form_row(layout, "Host", self.host)


class LabelPathUriClientEditBase(UriClientEditBase):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = QLineEdit(self)
        self.path = QLineEdit(self)
        self.test_button = QPushButton("Test", self)

    def build_layout(self) -> None:
        settings_layout = self.build_form_layout()
        self.add_uri_field(settings_layout)
        self.add_form_row(settings_layout, "Label", self.label)
        self.add_form_row(settings_layout, "Path", self.path)
        self.finish_layout(settings_layout, self.test_button)


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

        settings_layout = self.build_form_layout()
        self.add_connection_fields(settings_layout)
        self.add_form_row(settings_layout, "Category", self.category)
        self.add_form_row(
            settings_layout,
            "Add new torrents in super seeding mode",
            self.super_seeding,
        )
        self.add_form_row(settings_layout, "Save location mode", self.save_path_mode)
        self.add_form_row(
            settings_layout,
            "Save location template",
            self.save_path_template,
        )
        self.finish_layout(settings_layout, self.test_button)
        self.load()

    def load(self) -> None:
        config = cast(QBittorrentConfig, self.config)
        self.load_connection(config)
        self.category.setText(config.category)
        self.super_seeding.setChecked(config.super_seeding)
        mode_index = self.save_path_mode.findData(config.save_path_mode.value)
        self.save_path_mode.setCurrentIndex(max(mode_index, 0))
        self.save_path_template.setText(config.save_path_template)
        self._sync_save_path_template_state()

    def save(self) -> None:
        config = cast(QBittorrentConfig, self.config)
        self.save_connection(config)
        config.category = self.category.text().strip()
        config.super_seeding = self.super_seeding.isChecked()
        config.save_path_mode = QBittorrentSavePathMode(
            str(self.save_path_mode.currentData())
        )
        config.save_path_template = self.save_path_template.text().strip()

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

        settings_layout = self.build_form_layout()
        self.add_connection_fields(settings_layout)
        self.add_form_row(settings_layout, "Label", self.label)
        self.add_form_row(settings_layout, "Path", self.path)
        self.finish_layout(settings_layout, self.test_button)
        self.load()

    def load(self) -> None:
        config = cast(DelugeConfig, self.config)
        self.load_connection(config)
        self.label.setText(config.label)
        self.path.setText(config.path)

    def save(self) -> None:
        config = cast(DelugeConfig, self.config)
        self.save_connection(config)
        config.label = self.label.text().strip()
        config.path = self.path.text().strip()

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
        self.load()

    def load(self) -> None:
        config = cast(RTorrentConfig, self.config)
        self.host.setText(config.host or "")
        self.label.setText(config.label)
        self.path.setText(config.path)

    def save(self) -> None:
        config = cast(RTorrentConfig, self.config)
        config.host = self.host.text().strip()
        config.label = self.label.text().strip()
        config.path = self.path.text().strip()

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
        self.load()

    def load(self) -> None:
        config = cast(TransmissionConfig, self.config)
        self.host.setText(config.host or "")
        self.label.setText(config.label)
        self.path.setText(config.path)

    def save(self) -> None:
        config = cast(TransmissionConfig, self.config)
        config.host = self.host.text().strip()
        config.label = self.label.text().strip()
        config.path = self.path.text().strip()

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

        settings_layout = self.build_form_layout()
        self.add_form_row(settings_layout, "Path", self.path)
        self.finish_layout(settings_layout, None)
        self.load()

    def load(self) -> None:
        config = cast(WatchFolder, self.config)
        self.path.setText(str(config.path) if config.path else "")

    def save(self) -> None:
        config = cast(WatchFolder, self.config)
        path = self.path.text().strip()
        config.path = Path(path) if path else None
