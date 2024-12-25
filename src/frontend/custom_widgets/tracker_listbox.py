import re
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
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction

from src.enums.trackers import MTVSourceOrigin, BHDPromo, BHDLiveRelease
from src.enums.tracker_selection import TrackerSelection
from src.payloads.trackers import TrackerInfo
from src.config.config import Config
from src.frontend.utils import build_h_line
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.frontend.custom_widgets.combo_box import CustomComboBox


class TrackerEdit(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.upload_enabled_lbl = QLabel("Upload Enabled", self)
        self.upload_enabled = QCheckBox(self)

        self.api_key_lbl = QLabel("Api Key", self)
        self.api_key = MaskedQLineEdit(masked=True, parent=self)

        self.announce_url_lbl = QLabel("Announce URL", self)
        self.announce_url = MaskedQLineEdit(masked=True, parent=self)

        self.anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        self._enum_map = {
            "enum__mtv__source_origin": MTVSourceOrigin,
            "enum__bhd__promo": BHDPromo,
            "enum__bhd__live_release": BHDLiveRelease,
        }

        self.specific_params_layout = QVBoxLayout()
        self.specific_params_map: dict[str, QWidget] = {}

        self.comments_lbl = QLabel("Torrent Comments", self)
        self.comments = QLineEdit(self)

        self.source_lbl = QLabel("Torrent Source", self)
        self.source = QLineEdit(self)

        settings_layout = QVBoxLayout()
        settings_layout.addLayout(
            self.build_form_layout(self.upload_enabled_lbl, self.upload_enabled)
        )
        settings_layout.addLayout(
            self.build_form_layout(self.api_key_lbl, self.api_key)
        )
        settings_layout.addLayout(
            self.build_form_layout(self.announce_url_lbl, self.announce_url)
        )
        settings_layout.addLayout(
            self.build_form_layout(self.anonymous_lbl, self.anonymous)
        )
        settings_layout.addWidget(build_h_line((10, 1, 10, 1)))
        settings_layout.addLayout(self.specific_params_layout)
        settings_layout.addWidget(build_h_line((10, 1, 10, 1)))
        settings_layout.addLayout(
            self.build_form_layout(self.comments_lbl, self.comments)
        )
        settings_layout.addLayout(self.build_form_layout(self.source_lbl, self.source))
        settings_layout.addWidget(build_h_line((0, 1, 0, 1)))

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(settings_layout)
        self.setLayout(main_layout)

    def build_widgets_from_dict(self, data: dict[str, str]) -> None:
        """
        Builds widgets as needed dynamically.

        Anything prefixed with 'enum_tracker__' will generate a ComboBox (control enums with '_enum_map' above).
        Anything prefixed with 'textm__' will generate a MastedQLineEdit.
        Anything prefixed with 'text__' will generate a QLineEdit.
        """
        for key, value in data.items():
            og_key = key
            widget = None
            if key.startswith("enum__"):
                mapped_enum = self._enum_map[key]
                widget = CustomComboBox(
                    completer=True, disable_mouse_wheel=True, parent=self
                )
                for enum_member in mapped_enum:
                    widget.addItem(
                        str(enum_member), (enum_member.name, enum_member.value)
                    )
                saved_index = widget.findText(str(mapped_enum(value)))
                if saved_index >= 0:
                    widget.setCurrentIndex(saved_index)
                key = re.sub(r"enum__\w+?__", "", key)

            elif key.startswith("textm__"):
                widget = MaskedQLineEdit(self, True)
                widget.setText(value)
                key = key.replace("textm__", "")

            elif key.startswith("text__"):
                widget = MaskedQLineEdit(self, False)
                widget.setText(value)
                key = key.replace("text__", "")

            elif key.startswith("check__"):
                widget = QCheckBox(self)
                if value and bool(int(value)):
                    widget.setChecked(True)
                key = key.replace("check__", "")

            if widget:
                self.specific_params_map[og_key] = widget
                form = self.build_form_layout(key.title().replace("_", " "), widget)
                self.specific_params_layout.addLayout(form)

    @staticmethod
    def build_form_layout(lbl: QLabel | str, widget: QWidget) -> QFormLayout:
        layout = QFormLayout()
        if isinstance(lbl, QLabel):
            layout.addWidget(lbl)
        else:
            layout.addWidget(QLabel(lbl))
        layout.addWidget(widget)
        return layout


class TrackerListWidget(QWidget):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)

        self.config = config

        self._save_settings_map = {}

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
        self._save_settings_map.clear()

        # clear tree widget
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

            self.add_child_widgets(parent_item, tracker, tracker_info)

        self.tree.blockSignals(False)

    def add_child_widgets(
        self, parent_item, tracker: TrackerSelection, tracker_info: TrackerInfo
    ) -> None:
        child_widget = QWidget()
        child_layout = QVBoxLayout(child_widget)
        child_layout.setContentsMargins(0, 0, 0, 0)

        # build TrackerEdit widget
        tracker_widget = TrackerEdit()
        tracker_widget.upload_enabled.setChecked(tracker_info.upload_enabled)
        tracker_widget.api_key.setText(
            tracker_info.api_key if tracker_info.api_key else ""
        )
        tracker_widget.announce_url.setText(
            tracker_info.announce_url if tracker_info.announce_url else ""
        )
        tracker_widget.anonymous.setChecked(tracker_info.anonymous)
        tracker_widget.build_widgets_from_dict(tracker_info.specific_params)
        tracker_widget.comments.setText(
            tracker_info.comments if tracker_info.comments else ""
        )
        tracker_widget.source.setText(
            tracker_info.source if tracker_info.source else ""
        )

        if tracker == TrackerSelection.TORRENT_LEECH:
            tracker_widget.api_key_lbl.setText("Torrent Passkey")

        self._save_settings_map[tracker] = tracker_widget

        child_layout.addWidget(tracker_widget)

        # add child widget to tree under parent item
        child_item = QTreeWidgetItem(parent_item)
        self.tree.setItemWidget(child_item, 0, child_widget)

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
    def save_tracker_info(self, tracker: TrackerSelection) -> None:
        tracker_attributes: TrackerInfo = self.config.tracker_map[tracker]

        # update generic tracker info
        tracker_widget: TrackerEdit = self._save_settings_map[tracker]
        tracker_attributes.upload_enabled = tracker_widget.upload_enabled.isChecked()
        tracker_attributes.api_key = tracker_widget.api_key.text().strip()
        tracker_attributes.announce_url = self._tracker_announce_url_check(
            tracker, tracker_widget.announce_url.text().strip()
        )
        tracker_attributes.anonymous = tracker_widget.anonymous.isChecked()

        # update 'specific params'
        for key, val_widget in tracker_widget.specific_params_map.items():
            if isinstance(val_widget, MaskedQLineEdit):
                tracker_attributes.specific_params[key] = val_widget.text().strip()
            elif isinstance(val_widget, QCheckBox):
                tracker_attributes.specific_params[key] = int(val_widget.isChecked())
            elif isinstance(val_widget, CustomComboBox):
                _, enum_value = val_widget.currentData()
                tracker_attributes.specific_params[key] = enum_value

        # update torrent info
        tracker_attributes.comments = tracker_widget.comments.text().strip()
        tracker_attributes.source = tracker_widget.source.text().strip()

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
        self._save_settings_map.clear()
        self.tree.blockSignals(False)

    @staticmethod
    def _tracker_announce_url_check(tracker: TrackerSelection, url: str) -> str:
        if tracker in (TrackerSelection.MORE_THAN_TV, TrackerSelection.TORRENT_LEECH):
            if not url.endswith("/announce"):
                url = f"{url}/announce"
        return url
