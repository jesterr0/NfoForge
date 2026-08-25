from typing import Any, cast
from uuid import uuid4

from PySide6.QtCore import QPoint, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import override

from src.config.config import ConfigManager
from src.enums.image_host import ImageHost
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.packages.custom_types import ImageHostRef
from src.payloads.image_hosts import (
    CheveretoV3Payload,
    CheveretoV4Payload,
    ImagePayloadBase,
)

# The role each top-level row carries its `ImageHostRef` in. A row's *text* is
# a Chevereto instance's user-chosen label, so it cannot identify the row.
_HOST_REF_ROLE = Qt.ItemDataRole.UserRole

# Sites known to run Chevereto v4, offered when adding an instance so the URL
# does not have to be looked up. Not separate hosts: they differ from any other
# Chevereto instance only by URL.
CHEVERETO_V4_PRESETS: tuple[tuple[str, str], ...] = (
    ("PTScreens", "https://ptscreens.com/"),
)


class ImageHostEditBase(QWidget):
    load_data = Signal()
    save_data = Signal()

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
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

    def add_widget_to_layout(self, widget: QWidget, **kwargs: Any) -> None:
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


class CheveretoInstanceEditBase(ImageHostEditBase):
    """Shared editing for one user-added Chevereto site.

    Unlike the single-slot hosts below, these edit a payload handed to them
    rather than one they look up on `config`: a kind holds any number of them,
    and only the caller knows which one this row is.
    """

    # the label names the row, so the tree has to hear about a rename
    label_changed = Signal()
    remove_requested = Signal()

    def __init__(
        self,
        config: ConfigManager,
        payload: CheveretoV3Payload | CheveretoV4Payload,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(config, parent)

        self.payload = payload

        self.label_lbl = QLabel("Label", self)
        self.label = MaskedQLineEdit(parent=self)
        self.label.setPlaceholderText("Name this site, e.g. PTScreens")
        self.label.editingFinished.connect(self.label_changed.emit)

        # above Base URL: it is what names the row
        self.main_layout.insertLayout(
            0, self.build_form_layout(self.label_lbl, self.label)
        )

        # Removal lives on the site's own editor rather than only in the
        # tree's context menu: a right-click is not an affordance anyone
        # finds, and here there is no ambiguity about which site goes.
        self.remove_btn = QPushButton("Remove Site", self)
        self.remove_btn.setToolTip("Delete this Chevereto site from the list")
        self.remove_btn.clicked.connect(self.remove_requested.emit)

    def finish_layout(self) -> None:
        """Put the Remove button below the fields.

        Called by each subclass at the end of its own `__init__`, since the
        button has to land after the credential rows they add.
        """
        self.main_layout.addWidget(
            self.remove_btn, alignment=Qt.AlignmentFlag.AlignRight
        )

    @override
    def load_settings(self) -> None:
        self.label.setText(self.payload.label)
        self.base_url.setText(self.payload.base_url if self.payload.base_url else "")

    @override
    def save_settings(self) -> None:
        self.payload.label = self.label.text().strip()
        self.payload.base_url = self.base_url.text().strip()


class CheveretoV3Edit(CheveretoInstanceEditBase):
    def __init__(
        self,
        config: ConfigManager,
        payload: CheveretoV3Payload,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(config, payload, parent)
        self.payload: CheveretoV3Payload = payload

        self.username_lbl = QLabel("Username", self)
        self.username = MaskedQLineEdit(parent=self)

        self.password_lbl = QLabel("Password", self)
        self.password = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(self.username_lbl, self.username)
        self.add_pair_to_layout(self.password_lbl, self.password)
        self.finish_layout()

    @override
    def load_settings(self) -> None:
        super().load_settings()
        self.username.setText(self.payload.user if self.payload.user else "")
        self.password.setText(self.payload.password if self.payload.password else "")

    @override
    def save_settings(self) -> None:
        super().save_settings()
        self.payload.user = self.username.text().strip()
        self.payload.password = self.password.text().strip()

    @override
    def validate_data(self) -> None:
        for item in (self.label, self.base_url, self.username, self.password):
            if not item.text().strip():
                raise AttributeError("Missing required input for host Chevereto v3")


class CheveretoV4Edit(CheveretoInstanceEditBase):
    def __init__(
        self,
        config: ConfigManager,
        payload: CheveretoV4Payload,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(config, payload, parent)
        self.payload: CheveretoV4Payload = payload

        self.api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(self.api_key_lbl, self.api_key)
        self.finish_layout()

    @override
    def load_settings(self) -> None:
        super().load_settings()
        self.api_key.setText(self.payload.api_key if self.payload.api_key else "")

    @override
    def save_settings(self) -> None:
        super().save_settings()
        self.payload.api_key = self.api_key.text().strip()

    @override
    def validate_data(self) -> None:
        for item in (self.label, self.base_url, self.api_key):
            if not item.text().strip():
                raise AttributeError("Missing required input for host Chevereto v4")


class ImageBBEdit(ImageHostEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        self.base_url.setDisabled(True)

        self.api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(self.api_key_lbl, self.api_key)

    @override
    def load_settings(self) -> None:
        host = self.config.settings.image_hosts.image_bb
        self.base_url.setText(host.base_url if host.base_url else "")
        self.api_key.setText(host.api_key if host.api_key else "")

    @override
    def save_settings(self) -> None:
        self.config.settings.image_hosts.image_bb.base_url = (
            self.base_url.text().strip()
        )
        self.config.settings.image_hosts.image_bb.api_key = self.api_key.text().strip()

    @override
    def validate_data(self) -> None:
        for item in (self.base_url, self.api_key):
            if not item.text().strip():
                raise AttributeError("Missing required input for host ImageBB")


class ImageBoxEdit(ImageHostEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        self.base_url.setDisabled(True)

    @override
    def load_settings(self) -> None:
        host = self.config.settings.image_hosts.image_box
        self.base_url.setText(host.base_url if host.base_url else "")

    @override
    def save_settings(self) -> None:
        self.config.settings.image_hosts.image_box.base_url = (
            self.base_url.text().strip()
        )

    @override
    def validate_data(self) -> None:
        if not self.base_url.text().strip():
            raise AttributeError("Missing required input for host ImageBox")


class OnlyImageEdit(ImageHostEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        self.base_url.setDisabled(True)

        self.api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(self.api_key_lbl, self.api_key)

    @override
    def load_settings(self) -> None:
        host = self.config.settings.image_hosts.only_image
        self.base_url.setText(host.base_url if host.base_url else "")
        self.api_key.setText(host.api_key if host.api_key else "")

    @override
    def save_settings(self) -> None:
        self.config.settings.image_hosts.only_image.base_url = (
            self.base_url.text().strip()
        )
        self.config.settings.image_hosts.only_image.api_key = (
            self.api_key.text().strip()
        )

    @override
    def validate_data(self) -> None:
        for item in (self.base_url, self.api_key):
            if not item.text().strip():
                raise AttributeError("Missing required input for host OnlyImage")


class LensdumpEdit(ImageHostEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        self.base_url.setDisabled(True)

        self.api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(self.api_key_lbl, self.api_key)

    @override
    def load_settings(self) -> None:
        host = self.config.settings.image_hosts.lensdump
        self.base_url.setText(host.base_url if host.base_url else "")
        self.api_key.setText(host.api_key if host.api_key else "")

    @override
    def save_settings(self) -> None:
        self.config.settings.image_hosts.lensdump.base_url = (
            self.base_url.text().strip()
        )
        self.config.settings.image_hosts.lensdump.api_key = self.api_key.text().strip()

    @override
    def validate_data(self) -> None:
        for item in (self.base_url, self.api_key):
            if not item.text().strip():
                raise AttributeError("Missing required input for host Lensdump")


class PixhostEdit(ImageHostEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        self.base_url.setDisabled(True)

    @override
    def load_settings(self) -> None:
        host = self.config.settings.image_hosts.pixhost
        self.base_url.setText(host.base_url if host.base_url else "")

    @override
    def save_settings(self) -> None:
        self.config.settings.image_hosts.pixhost.base_url = self.base_url.text().strip()

    @override
    def validate_data(self) -> None:
        if not self.base_url.text().strip():
            raise AttributeError("Missing required input for host Pixhost")


class ImageHostListBox(QWidget):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.config = config
        self._reset = False

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

        # A visible control, not only the tree's context menu: with no
        # Chevereto site configured the tree has no row to right-click, so the
        # menu alone left the feature with no way in at all.
        self.add_site_btn = QToolButton(self)
        self.add_site_btn.setText("Add Chevereto Site")
        self.add_site_btn.setToolTip(
            "Add a site running Chevereto -- ptscreens.com and any other "
            "Chevereto host, as many as you like"
        )
        self.add_site_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._add_menu = QMenu(self)
        self._populate_add_menu(self._add_menu)
        self.add_site_btn.setMenu(self._add_menu)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addWidget(self.add_site_btn)
        button_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(button_row)
        layout.addWidget(self.tree)

    def add_items(
        self, items: dict[ImageHostRef, ImagePayloadBase], reset: bool = False
    ) -> None:
        self._reset = reset
        self.tree.blockSignals(True)
        self.tree.clear()

        if items:
            for host_ref, image_host_info in items.items():
                parent_item = QTreeWidgetItem(self.tree)
                parent_item.setText(0, self._row_text(host_ref))
                parent_item.setData(0, _HOST_REF_ROLE, host_ref)

                # add checkbox to the parent item
                parent_item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if (image_host_info.enabled and not reset)
                    else Qt.CheckState.Unchecked,
                )

                self.add_child_widget(parent_item, host_ref, image_host_info)

        self.tree.blockSignals(False)

    @staticmethod
    def _row_text(host_ref: ImageHostRef) -> str:
        """What one row shows.

        A Chevereto instance is named by the user, and one they have not named
        yet still has to be findable, so it falls back to its kind plus a nudge.
        """
        if host_ref.instance_id and not host_ref.label:
            return f"{host_ref.kind} (unnamed)"
        return str(host_ref)

    def add_child_widget(
        self,
        parent_item: QTreeWidgetItem,
        host_ref: ImageHostRef,
        payload: ImagePayloadBase,
    ) -> None:
        image_widget: ImageHostEditBase | None = None
        kind = host_ref.kind
        if kind is ImageHost.CHEVERETO_V3:
            image_widget = CheveretoV3Edit(
                self.config, cast(CheveretoV3Payload, payload), self
            )
        elif kind is ImageHost.CHEVERETO_V4:
            image_widget = CheveretoV4Edit(
                self.config, cast(CheveretoV4Payload, payload), self
            )
        elif kind is ImageHost.IMAGE_BOX:
            image_widget = ImageBoxEdit(self.config, self)
        elif kind is ImageHost.IMAGE_BB:
            image_widget = ImageBBEdit(self.config, self)
        elif kind is ImageHost.ONLY_IMAGE:
            image_widget = OnlyImageEdit(self.config, self)
        elif kind is ImageHost.PIXHOST:
            image_widget = PixhostEdit(self.config, self)
        elif kind is ImageHost.LENSDUMP:
            image_widget = LensdumpEdit(self.config, self)
        if image_widget:
            if isinstance(image_widget, CheveretoInstanceEditBase):
                instance_edit = image_widget
                image_widget.label_changed.connect(
                    lambda item=parent_item: self._rename_row(item, instance_edit)
                )
                # Deferred: removing rebuilds the tree, which deletes the very
                # widget whose button is still emitting. Let the signal unwind
                # first.
                image_widget.remove_requested.connect(
                    lambda ref=host_ref: QTimer.singleShot(
                        0, lambda: self.remove_chevereto_instance(ref)
                    )
                )
            image_widget.load_data.emit()
            child_item = QTreeWidgetItem(parent_item)
            self.tree.setItemWidget(child_item, 0, image_widget)

    def validate_settings(self) -> None:
        """If host is checked, we'll call the `validate_data()` method"""
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            if not parent:
                return None
            if parent.checkState(0) == Qt.CheckState.Checked:
                for j in range(parent.childCount()):
                    child = parent.child(j)
                    image_edit = self.tree.itemWidget(child, 0)
                    if image_edit and isinstance(image_edit, ImageHostEditBase):
                        image_edit.validate_data()

    def _open_context_menu(self, position: QPoint) -> None:
        """Opens the right-click context menu for managing and expanding hosts"""
        menu = QMenu()

        self._populate_add_menu(menu.addMenu("Add Chevereto Site"))

        removable = self._instance_ref(self.tree.itemAt(position))
        if removable is not None:
            remove_action = QAction(f"Remove {self._row_text(removable)}", self)
            remove_action.triggered.connect(
                lambda _checked=False, host_ref=removable: (
                    self.remove_chevereto_instance(host_ref)
                )
            )
            menu.addAction(remove_action)

        menu.addSeparator()

        expand_action = QAction("Expand All", self)
        expand_action.triggered.connect(self.expand_all_items)
        menu.addAction(expand_action)

        collapse_action = QAction("Collapse All", self)
        collapse_action.triggered.connect(self.collapse_all_items)
        menu.addAction(collapse_action)

        # display the context menu at the mouse position
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _populate_add_menu(self, menu: QMenu) -> None:
        """Fill an "add a Chevereto site" menu.

        Shared by the button above the tree and the tree's context menu, so
        the two cannot drift apart.
        """
        for kind, text in (
            (ImageHost.CHEVERETO_V3, "Blank Chevereto v3 Site"),
            (ImageHost.CHEVERETO_V4, "Blank Chevereto v4 Site"),
        ):
            action = QAction(text, self)
            action.triggered.connect(
                lambda _checked=False, host_kind=kind: self.add_chevereto_instance(
                    host_kind
                )
            )
            menu.addAction(action)
        menu.addSeparator()
        for preset_label, preset_url in CHEVERETO_V4_PRESETS:
            preset_action = QAction(f"{preset_label} (Chevereto v4)", self)
            preset_action.triggered.connect(
                lambda _checked=False, name=preset_label, url=preset_url: (
                    self.add_chevereto_instance(
                        ImageHost.CHEVERETO_V4, label=name, base_url=url
                    )
                )
            )
            menu.addAction(preset_action)

    def _instance_ref(self, item: QTreeWidgetItem | None) -> ImageHostRef | None:
        """The Chevereto instance `item` belongs to, if any.

        Right-clicking a host's editor rather than its header should still
        offer to remove that host, so a child row answers with its parent's.
        """
        while item is not None:
            host_ref = item.data(0, _HOST_REF_ROLE)
            if isinstance(host_ref, ImageHostRef) and host_ref.instance_id:
                return host_ref
            item = item.parent()
        return None

    def add_chevereto_instance(
        self, kind: ImageHost, label: str = "", base_url: str = ""
    ) -> ImageHostRef:
        """Add a Chevereto site and show it.

        The id is generated and never shown: it is what a per-tracker selection
        and a saved job point at, so it has to outlive any rename of `label`.
        """
        # keep what is on screen -- a rebuild reads config, and unapplied edits
        # live in the editors until `save_host_info`
        self.save_host_info()

        instance_id = uuid4().hex[:12]
        if kind is ImageHost.CHEVERETO_V3:
            self.config.settings.image_hosts.chevereto_v3.append(
                CheveretoV3Payload(
                    base_url=base_url, instance_id=instance_id, label=label
                )
            )
        else:
            self.config.settings.image_hosts.chevereto_v4.append(
                CheveretoV4Payload(
                    base_url=base_url, instance_id=instance_id, label=label
                )
            )

        self._rebuild()
        return ImageHostRef(kind=kind, instance_id=instance_id, label=label)

    def remove_chevereto_instance(self, host_ref: ImageHostRef) -> None:
        """Drop one Chevereto site, and anything still pointing at it.

        A per-tracker last-used entry left behind would name a host that no
        longer exists, which the process page then reports as an unavailable
        host on every run.
        """
        self.save_host_info()

        hosts = self.config.settings.image_hosts
        if host_ref.kind is ImageHost.CHEVERETO_V3:
            hosts.chevereto_v3 = [
                instance
                for instance in hosts.chevereto_v3
                if instance.instance_id != host_ref.instance_id
            ]
        else:
            hosts.chevereto_v4 = [
                instance
                for instance in hosts.chevereto_v4
                if instance.instance_id != host_ref.instance_id
            ]

        last_used = self.config.settings.trackers.last_used_image_host
        for tracker in [
            tracker for tracker, host in last_used.items() if host == host_ref
        ]:
            del last_used[tracker]

        self._rebuild()

    def _rename_row(
        self, item: QTreeWidgetItem, widget: CheveretoInstanceEditBase
    ) -> None:
        """Retitle one row as its label is edited, without a full rebuild.

        Rebuilding here would destroy the editor the user is still working in.
        """
        host_ref = item.data(0, _HOST_REF_ROLE)
        if not isinstance(host_ref, ImageHostRef):
            return
        new_label = widget.label.text().strip()
        renamed = ImageHostRef(
            kind=host_ref.kind, instance_id=host_ref.instance_id, label=new_label
        )
        widget.payload.label = new_label
        self.tree.blockSignals(True)
        item.setData(0, _HOST_REF_ROLE, renamed)
        item.setText(0, self._row_text(renamed))
        self.tree.blockSignals(False)

    def _rebuild(self) -> None:
        self.add_items(self.config.settings.image_hosts.by_selection(), self._reset)

    def expand_all_items(self) -> None:
        """Expand all parent items in the QTreeWidget"""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item:
                item.setExpanded(True)

    def collapse_all_items(self) -> None:
        """Collapse all parent items in the QTreeWidget"""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item:
                item.setExpanded(False)

    @Slot(object, int)
    def _toggle_tracker(self, item: QTreeWidgetItem, column: int) -> None:
        host_ref = item.data(column, _HOST_REF_ROLE)
        if not isinstance(host_ref, ImageHostRef):
            return
        image_host_attributes = self.config.settings.image_hosts.by_selection().get(
            host_ref
        )
        if image_host_attributes is None:
            return
        image_host_attributes.enabled = (
            True if item.checkState(column) == Qt.CheckState.Checked else False
        )

    def save_host_info(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            if not parent:
                return None
            for j in range(parent.childCount()):
                child = parent.child(j)
                image_edit = self.tree.itemWidget(child, 0)
                if image_edit and isinstance(image_edit, ImageHostEditBase):
                    image_edit.save_data.emit()

    def clear(self) -> None:
        self.tree.clear()
