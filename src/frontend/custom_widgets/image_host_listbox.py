from typing_extensions import override
from PySide6.QtWidgets import (
    QFrame,
    QLayout,
    QVBoxLayout,
    QWidget,
    QLabel,
    QFormLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QMenu,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction

from src.config.config import Config
from src.enums.image_host import ImageHost
from src.payloads.image_hosts import ImagePayloadBase
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit


class ImageHostEditBase(QWidget):
    load_data = Signal()
    save_data = Signal()

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)

        self.config = config

        self.load_data.connect(self.load_settings)
        self.save_data.connect(self.save_settings)

        self.base_url_lbl = QLabel("Base URL", self)
        self.base_url = MaskedQLineEdit(parent=self)

        self.main_layout = QVBoxLayout(self)

        self.add_pair_to_layout(self.base_url_lbl, self.base_url)

    def load_settings(self) -> None:
        raise NotImplementedError("Must be implemented this per image host")

    def save_settings(self) -> None:
        raise NotImplementedError("Must be implemented this per image host")

    def validate_data(self) -> None:
        raise NotImplementedError("Must be implemented this per image host")

    def add_pair_to_layout(self, label: QLabel, widget: QWidget) -> QFormLayout:
        layout = self.build_form_layout(label, widget)
        self.main_layout.addLayout(layout)
        return layout

    def add_widget_to_layout(self, widget: QWidget, **kwargs) -> None:
        self.main_layout.addWidget(widget, **kwargs)

    def add_layout_to_layout(self, layout: QLayout) -> None:
        self.main_layout.addLayout(layout)

    @staticmethod
    def build_form_layout(lbl: QLabel | str, widget: QWidget) -> QFormLayout:
        layout = QFormLayout()
        if isinstance(lbl, QLabel):
            layout.addWidget(lbl)
        else:
            layout.addWidget(QLabel(lbl))
        layout.addWidget(widget)
        return layout


class CheveretoV3Edit(ImageHostEditBase):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(config, parent)

        self.username_lbl = QLabel("Username", self)
        self.username = MaskedQLineEdit(parent=self)

        self.password_lbl = QLabel("Password", self)
        self.password = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(self.username_lbl, self.username)
        self.add_pair_to_layout(self.password_lbl, self.password)

    @override
    def load_settings(self) -> None:
        host = self.config.cfg_payload.chevereto_v3
        self.base_url.setText(host.base_url if host.base_url else "")
        self.username.setText(host.user if host.user else "")
        self.password.setText(host.password if host.password else "")

    @override
    def save_settings(self) -> None:
        self.config.cfg_payload.chevereto_v3.base_url = self.base_url.text().strip()
        self.config.cfg_payload.chevereto_v3.user = self.username.text().strip()
        self.config.cfg_payload.chevereto_v3.password = self.password.text().strip()

    @override
    def validate_data(self) -> None:
        for item in (
            self.base_url,
            self.username,
            self.password,
        ):
            if not item.text().strip():
                raise AttributeError("Missing required input for host Chevereto v3")


class CheveretoV4Edit(ImageHostEditBase):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(config, parent)

        self.api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(self.base_url_lbl, self.base_url)
        self.add_pair_to_layout(self.api_key_lbl, self.api_key)

    @override
    def load_settings(self) -> None:
        host = self.config.cfg_payload.chevereto_v4
        self.base_url.setText(host.base_url if host.base_url else "")
        self.api_key.setText(host.api_key if host.api_key else "")

    @override
    def save_settings(self) -> None:
        self.config.cfg_payload.chevereto_v4.base_url = self.base_url.text().strip()
        self.config.cfg_payload.chevereto_v4.api_key = self.api_key.text().strip()

    @override
    def validate_data(self) -> None:
        for item in (self.base_url, self.api_key):
            if not item.text().strip():
                raise AttributeError("Missing required input for host Chevereto v4")


class ImageBBEdit(ImageHostEditBase):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(config, parent)

        self.base_url.setDisabled(True)

        self.api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(self.api_key_lbl, self.api_key)

    @override
    def load_settings(self) -> None:
        host = self.config.cfg_payload.image_bb
        self.base_url.setText(host.base_url if host.base_url else "")
        self.api_key.setText(host.api_key if host.api_key else "")

    @override
    def save_settings(self) -> None:
        self.config.cfg_payload.image_bb.base_url = self.base_url.text().strip()
        self.config.cfg_payload.image_bb.api_key = self.api_key.text().strip()

    @override
    def validate_data(self) -> None:
        for item in (self.base_url, self.api_key):
            if not item.text().strip():
                raise AttributeError("Missing required input for host ImageBB")


class ImageBoxEdit(ImageHostEditBase):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(config, parent)

        self.base_url.setDisabled(True)

    @override
    def load_settings(self) -> None:
        host = self.config.cfg_payload.image_box
        self.base_url.setText(host.base_url if host.base_url else "")

    @override
    def save_settings(self) -> None:
        self.config.cfg_payload.image_box.base_url = self.base_url.text().strip()

    @override
    def validate_data(self) -> None:
        if not self.base_url.text().strip():
            raise AttributeError("Missing required input for host ImageBox")


class ImageHostListBox(QWidget):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)

        self.config = config

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
        self.tree.itemChanged.connect(self._toggle_tracker)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)

    def add_items(self, items: dict[ImageHost, ImagePayloadBase]) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()

        if items:
            for image_host, image_host_info in items.items():
                parent_item = QTreeWidgetItem(self.tree)
                parent_item.setText(0, str(image_host))

                # add checkbox to the parent item
                parent_item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if image_host_info.enabled
                    else Qt.CheckState.Unchecked,
                )

                self.add_child_widget(parent_item, image_host)

        self.tree.blockSignals(False)

    def add_child_widget(self, parent_item, image_host: ImageHost) -> None:
        image_widget = None
        if image_host is ImageHost.CHEVERETO_V3:
            image_widget = CheveretoV3Edit(self.config, self)
        elif image_host is ImageHost.CHEVERETO_V4:
            image_widget = CheveretoV4Edit(self.config, self)
        elif image_host is ImageHost.IMAGE_BOX:
            image_widget = ImageBoxEdit(self.config, self)
        elif image_host is ImageHost.IMAGE_BB:
            image_widget = ImageBBEdit(self.config, self)

        if image_widget:
            image_widget.load_data.emit()
            child_item = QTreeWidgetItem(parent_item)
            self.tree.setItemWidget(child_item, 0, image_widget)

    def validate_settings(self) -> None:
        """If host is checked, we'll call the `validate_data()` method"""
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            if parent.checkState(0) == Qt.CheckState.Checked:
                for j in range(parent.childCount()):
                    child = parent.child(j)
                    image_edit = self.tree.itemWidget(child, 0)
                    if image_edit and isinstance(image_edit, ImageHostEditBase):
                        image_edit.validate_data()

    def _open_context_menu(self, position) -> None:
        """Opens the right-click context menu for expanding and collapsing all trackers"""
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

    @Slot(object, int)
    def _toggle_tracker(self, item: QTreeWidgetItem, column: int) -> None:
        image_host_attributes = self.config.image_host_map[ImageHost(item.text(column))]
        image_host_attributes.enabled = (
            True if item.checkState(column) == Qt.CheckState.Checked else False
        )

    def save_host_info(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                image_edit = self.tree.itemWidget(child, 0)
                if image_edit and isinstance(image_edit, ImageHostEditBase):
                    image_edit.save_data.emit()

    def clear(self) -> None:
        self.tree.clear()
