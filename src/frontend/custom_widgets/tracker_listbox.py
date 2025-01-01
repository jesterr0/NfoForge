from enum import Enum
from typing import Type

from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QWidget,
    QLabel,
    QCheckBox,
    QFormLayout,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QMenu,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction

from src.enums.trackers import MTVSourceOrigin, BHDPromo, BHDLiveRelease
from src.enums.tracker_selection import TrackerSelection
from src.payloads.trackers import TrackerInfo
from src.config.config import Config
from src.frontend.utils import build_h_line
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.frontend.custom_widgets.combo_box import CustomComboBox


class TrackerEditBase(QFrame):
    load_data = Signal()
    save_data = Signal()

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)

        self.config = config
        self.load_data.connect(self.load_settings)
        self.save_data.connect(self.save_settings)

        self.upload_enabled_lbl = QLabel("Upload Enabled", self)
        self.upload_enabled = QCheckBox(self)

        self.announce_url_lbl = QLabel("Announce URL", self)
        self.announce_url = MaskedQLineEdit(masked=True, parent=self)

        self.comments_lbl = QLabel("Torrent Comments", self)
        self.comments = QLineEdit(self)

        self.source_lbl = QLabel("Torrent Source", self)
        self.source = QLineEdit(self)

        self.settings_layout = QVBoxLayout()
        self.settings_layout.addLayout(
            self.build_form_layout(self.upload_enabled_lbl, self.upload_enabled)
        )
        self.settings_layout.addLayout(
            self.build_form_layout(self.announce_url_lbl, self.announce_url)
        )
        self.settings_layout.addLayout(
            self.build_form_layout(self.comments_lbl, self.comments)
        )
        self.settings_layout.addLayout(
            self.build_form_layout(self.source_lbl, self.source)
        )
        self.settings_layout.addWidget(build_h_line((0, 1, 0, 1)))

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addLayout(self.settings_layout)
        self.setLayout(self.main_layout)

    def add_pair_to_layout(self, label: QLabel, widget: QWidget) -> QFormLayout:
        layout = self.build_form_layout(label, widget)
        self.settings_layout.addLayout(layout)
        return layout

    def load_settings(self) -> None:
        raise NotImplementedError("Must be implemented this per tracker")

    def save_settings(self) -> None:
        raise NotImplementedError("Must be implemented this per tracker")

    @staticmethod
    def build_form_layout(lbl: QLabel | str, widget: QWidget) -> QFormLayout:
        layout = QFormLayout()
        if isinstance(lbl, QLabel):
            layout.addWidget(lbl)
        else:
            layout.addWidget(QLabel(lbl))
        layout.addWidget(widget)
        return layout

    @staticmethod
    def load_combo_box(
        widget: CustomComboBox, enum: Type[Enum], saved_data: Enum
    ) -> None:
        """Clears CustomComboBox and reloads it with fresh data, setting the default value if available"""
        widget.clear()
        for item in enum:
            widget.addItem(str(item), item)
        current_index = widget.findText(str(enum(saved_data)))
        if current_index >= 0:
            widget.setCurrentIndex(current_index)


class MTVTrackerEdit(TrackerEditBase):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(config, parent)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        username_lbl = QLabel("Username", self)
        self.username = MaskedQLineEdit(parent=self)

        password_lbl = QLabel("Password", self)
        self.password = MaskedQLineEdit(parent=self, masked=True)

        totp_lbl = QLabel("TOTP", self)
        self.totp = MaskedQLineEdit(parent=self, masked=True)

        group_description_lbl = QLabel("Group Description", self)
        self.group_description = MaskedQLineEdit(parent=self)

        additional_tags_lbl = QLabel("Additional Tags", self)
        self.additional_tags = MaskedQLineEdit(parent=self)

        source_origin_lbl = QLabel("Source Origin", self)
        self.source_origin = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(username_lbl, self.username)
        self.add_pair_to_layout(password_lbl, self.password)
        self.add_pair_to_layout(totp_lbl, self.totp)
        self.add_pair_to_layout(group_description_lbl, self.group_description)
        self.add_pair_to_layout(additional_tags_lbl, self.additional_tags)
        self.add_pair_to_layout(source_origin_lbl, self.source_origin)

    def load_settings(self) -> None:
        tracker_data = self.config.cfg_payload.mtv_tracker
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.username.setText(tracker_data.username if tracker_data.username else "")
        self.password.setText(tracker_data.password if tracker_data.password else "")
        self.totp.setText(tracker_data.totp if tracker_data.totp else "")
        self.group_description.setText(
            tracker_data.group_description if tracker_data.group_description else ""
        )
        self.additional_tags.setText(
            tracker_data.additional_tags if tracker_data.additional_tags else ""
        )
        self.load_combo_box(
            self.source_origin, MTVSourceOrigin, tracker_data.source_origin
        )

    def save_settings(self) -> None:
        self.config.cfg_payload.mtv_tracker.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.cfg_payload.mtv_tracker.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.cfg_payload.mtv_tracker.comments = self.comments.text().strip()
        self.config.cfg_payload.mtv_tracker.source = self.source.text().strip()
        self.config.cfg_payload.mtv_tracker.anonymous = int(self.anonymous.isChecked())
        self.config.cfg_payload.mtv_tracker.api_key = self.api_key.text().strip()
        self.config.cfg_payload.mtv_tracker.username = self.username.text().strip()
        self.config.cfg_payload.mtv_tracker.password = self.password.text().strip()
        self.config.cfg_payload.mtv_tracker.totp = self.totp.text().strip()
        self.config.cfg_payload.mtv_tracker.group_description = (
            self.group_description.text().strip()
        )
        self.config.cfg_payload.mtv_tracker.additional_tags = (
            self.additional_tags.text().strip()
        )
        self.config.cfg_payload.mtv_tracker.source_origin = MTVSourceOrigin(
            self.source_origin.currentData()
        )


class TLTrackerEdit(TrackerEditBase):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(config, parent)

        username_lbl = QLabel("Username", self)
        self.username = MaskedQLineEdit(parent=self)

        password_lbl = QLabel("Password", self)
        self.password = MaskedQLineEdit(parent=self, masked=True)

        torrent_passkey_lbl = QLabel("Torrent Passkey", self)
        self.torrent_passkey = MaskedQLineEdit(parent=self, masked=True)

        alt_2_fa_token_lbl = QLabel("Alt2FaToken", self)
        self.alt_2_fa_token = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(username_lbl, self.username)
        self.add_pair_to_layout(password_lbl, self.password)
        self.add_pair_to_layout(torrent_passkey_lbl, self.torrent_passkey)
        self.add_pair_to_layout(alt_2_fa_token_lbl, self.alt_2_fa_token)

    def load_settings(self) -> None:
        tracker_data = self.config.cfg_payload.tl_tracker
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.username.setText(tracker_data.username if tracker_data.username else "")
        self.password.setText(tracker_data.password if tracker_data.password else "")
        self.torrent_passkey.setText(
            tracker_data.torrent_passkey if tracker_data.torrent_passkey else ""
        )
        self.alt_2_fa_token.setText(
            tracker_data.alt_2_fa_token if tracker_data.alt_2_fa_token else ""
        )

    def save_settings(self) -> None:
        self.config.cfg_payload.tl_tracker.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.cfg_payload.tl_tracker.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.cfg_payload.tl_tracker.comments = self.comments.text().strip()
        self.config.cfg_payload.tl_tracker.source = self.source.text().strip()
        self.config.cfg_payload.tl_tracker.username = self.username.text().strip()
        self.config.cfg_payload.tl_tracker.password = self.password.text().strip()
        self.config.cfg_payload.tl_tracker.torrent_passkey = (
            self.torrent_passkey.text().strip()
        )
        self.config.cfg_payload.tl_tracker.alt_2_fa_token = (
            self.alt_2_fa_token.text().strip()
        )


class BHDTrackerEdit(TrackerEditBase):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(config, parent)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        rss_key_lbl = QLabel("RSS Key", self)
        self.rss_key = MaskedQLineEdit(parent=self, masked=True)

        promo_lbl = QLabel("Promo", self)
        self.promo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        live_release_lbl = QLabel("Live Release", self)
        self.live_release = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(rss_key_lbl, self.rss_key)
        self.add_pair_to_layout(promo_lbl, self.promo)
        self.add_pair_to_layout(live_release_lbl, self.live_release)
        self.add_pair_to_layout(internal_lbl, self.internal)

    def load_settings(self) -> None:
        tracker_data = self.config.cfg_payload.bhd_tracker
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.rss_key.setText(tracker_data.rss_key if tracker_data.rss_key else "")
        self.load_combo_box(self.promo, BHDPromo, tracker_data.promo)
        self.load_combo_box(
            self.live_release, BHDLiveRelease, tracker_data.live_release
        )
        self.internal.setChecked(bool(tracker_data.internal))

    def save_settings(self) -> None:
        self.config.cfg_payload.bhd_tracker.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.cfg_payload.bhd_tracker.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.cfg_payload.bhd_tracker.comments = self.comments.text().strip()
        self.config.cfg_payload.bhd_tracker.source = self.source.text().strip()
        self.config.cfg_payload.bhd_tracker.anonymous = int(self.anonymous.isChecked())
        self.config.cfg_payload.bhd_tracker.api_key = self.api_key.text().strip()
        self.config.cfg_payload.bhd_tracker.rss_key = self.rss_key.text().strip()
        self.config.cfg_payload.bhd_tracker.promo = BHDPromo(self.promo.currentData())
        self.config.cfg_payload.bhd_tracker.live_release = BHDLiveRelease(
            self.live_release.currentData()
        )
        self.config.cfg_payload.bhd_tracker.internal = int(self.internal.isChecked())


class PTPTrackerEdit(TrackerEditBase):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(config, parent)

        api_user_lbl = QLabel("API User", self)
        self.api_user = MaskedQLineEdit(parent=self, masked=True)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        username_lbl = QLabel("Username", self)
        self.username = MaskedQLineEdit(parent=self)

        password_lbl = QLabel("Password", self)
        self.password = MaskedQLineEdit(parent=self, masked=True)

        totp_lbl = QLabel("TOTP", self)
        self.totp = MaskedQLineEdit(parent=self, masked=True)

        ptpimg_api_key_lbl = QLabel("PTPIMG Api Key", self)
        self.ptpimg_api_key = MaskedQLineEdit(parent=self, masked=True)

        reupload_images_to_ptp_img_lbl = QLabel("Reupload all images to PTPIMG", self)
        self.reupload_images_to_ptp_img = QCheckBox(self)

        self.add_pair_to_layout(api_user_lbl, self.api_user)
        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(username_lbl, self.username)
        self.add_pair_to_layout(password_lbl, self.password)
        self.add_pair_to_layout(totp_lbl, self.totp)
        self.add_pair_to_layout(ptpimg_api_key_lbl, self.ptpimg_api_key)
        self.add_pair_to_layout(
            reupload_images_to_ptp_img_lbl, self.reupload_images_to_ptp_img
        )

    def load_settings(self) -> None:
        tracker_data = self.config.cfg_payload.ptp_tracker
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_user.setText(tracker_data.api_user if tracker_data.api_user else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.username.setText(tracker_data.username if tracker_data.username else "")
        self.password.setText(tracker_data.password if tracker_data.password else "")
        self.totp.setText(tracker_data.totp if tracker_data.totp else "")
        self.ptpimg_api_key.setText(
            tracker_data.ptpimg_api_key if tracker_data.ptpimg_api_key else ""
        )
        self.reupload_images_to_ptp_img.setChecked(
            bool(tracker_data.reupload_images_to_ptp_img)
        )

    def save_settings(self) -> None:
        self.config.cfg_payload.ptp_tracker.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.cfg_payload.ptp_tracker.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.cfg_payload.ptp_tracker.comments = self.comments.text().strip()
        self.config.cfg_payload.ptp_tracker.source = self.source.text().strip()
        self.config.cfg_payload.ptp_tracker.api_user = self.api_user.text().strip()
        self.config.cfg_payload.ptp_tracker.api_key = self.api_key.text().strip()
        self.config.cfg_payload.ptp_tracker.username = self.username.text().strip()
        self.config.cfg_payload.ptp_tracker.password = self.password.text().strip()
        self.config.cfg_payload.ptp_tracker.totp = self.totp.text().strip()
        self.config.cfg_payload.ptp_tracker.ptpimg_api_key = (
            self.ptpimg_api_key.text().strip()
        )
        self.config.cfg_payload.ptp_tracker.reupload_images_to_ptp_img = (
            self.reupload_images_to_ptp_img.isChecked()
        )


class TrackerListWidget(QWidget):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)

        self.config = config

        self.tree = QTreeWidget(self)
        self.tree.setFrameShape(QFrame.Shape.Box)
        self.tree.setFrameShadow(QFrame.Shadow.Sunken)
        self.tree.setHeaderHidden(True)
        self.tree.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.tree.verticalScrollBar().setSingleStep(5)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)
        self.tree.itemChanged.connect(self._toggle_tracker)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)

    def add_items(self, items: dict[TrackerSelection, TrackerInfo]) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()

        for tracker, tracker_info in items.items():
            parent_item = QTreeWidgetItem(self.tree)
            parent_item.setText(0, str(tracker))

            # add checkbox to the parent item
            parent_item.setCheckState(
                0,
                Qt.CheckState.Checked
                if tracker_info.enabled
                else Qt.CheckState.Unchecked,
            )

            self.add_child_widget(parent_item, tracker)

        self.tree.blockSignals(False)

    def add_child_widget(self, parent_item, tracker: TrackerSelection) -> None:
        tracker_widget = None
        if tracker is TrackerSelection.MORE_THAN_TV:
            tracker_widget = MTVTrackerEdit(self.config, self)
        elif tracker is TrackerSelection.TORRENT_LEECH:
            tracker_widget = TLTrackerEdit(self.config, self)
        elif tracker is TrackerSelection.BEYOND_HD:
            tracker_widget = BHDTrackerEdit(self.config, self)
        elif tracker is TrackerSelection.PASS_THE_POPCORN:
            tracker_widget = PTPTrackerEdit(self.config, self)

        if tracker_widget:
            tracker_widget.load_data.emit()
            child_item = QTreeWidgetItem(parent_item)
            self.tree.setItemWidget(child_item, 0, tracker_widget)

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
        tracker_attributes: TrackerInfo = self.config.tracker_map[
            TrackerSelection(item.text(column))
        ]
        tracker_attributes.enabled = (
            True if item.checkState(column) == Qt.CheckState.Checked else False
        )

    @Slot(object)
    def save_tracker_info(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                tracker_edit = self.tree.itemWidget(child, 0)
                if tracker_edit and isinstance(tracker_edit, TrackerEditBase):
                    tracker_edit.save_data.emit()

    def get_selected_trackers(self) -> list[TrackerSelection] | None:
        selected_items = []

        for i in range(self.tree.topLevelItemCount()):
            parent_item = self.tree.topLevelItem(i)
            name = parent_item.text(0)
            check_state = parent_item.checkState(0)
            if check_state == Qt.CheckState.Checked:
                selected_items.append(TrackerSelection(name))

        return selected_items if selected_items else None

    def clear(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.blockSignals(False)

    @staticmethod
    def _tracker_announce_url_check(tracker: TrackerSelection, url: str) -> str:
        if tracker in (TrackerSelection.MORE_THAN_TV, TrackerSelection.TORRENT_LEECH):
            if not url.endswith("/announce"):
                url = f"{url}/announce"
        return url
