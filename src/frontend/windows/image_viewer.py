from os import PathLike
from pathlib import Path
import re

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtGui import QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.enums.screen_shot_mode import ScreenShotMode
from src.frontend.custom_widgets.image_comparison import SideBySideImage
from src.frontend.custom_widgets.image_label import ImageLabel
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap


class ImageViewer(QWidget):
    re_sync_images = Signal(int)
    exit_viewer = Signal(list)

    def __init__(
        self,
        image_base_dir: PathLike[str],
        comparison_mode: ScreenShotMode,
        min_required_selected_screens: int = 0,
        max_required_selected_screens: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("imageViewer")
        self.setWindowTitle("Image Viewer")

        # TODO: allow user customization for this
        self.resize(800, 600)
        self.setWindowFlag(Qt.WindowType.Window)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.showMaximized()

        # folder vars
        # TODO add missing checks potentially for folder vars
        self.img_comparison_dir = Path(image_base_dir) / "img_comparison"
        self.img_sync_dir = Path(image_base_dir) / "img_sync"
        self.img_selected_dir = Path(image_base_dir) / "img_selected"
        self.comparison_images = sorted(
            [x for x in self.img_comparison_dir.glob("*.png")]
        )
        self.comparison_images_total = len(self.comparison_images)
        self.current_selected_index = 0
        self.moving_image_s = False

        self.comparison_mode = comparison_mode
        self.min_required_selected_screens = min_required_selected_screens
        self.max_required_selected_screens = max_required_selected_screens
        self.ignore_requirements = False

        # image tab vars (these will be defined in _build_image_tab)
        self.img_path_lbl: QLabel = None  # pyright: ignore [reportAttributeAccessIssue]
        self.resolution_lbl: QLabel = None  # pyright: ignore [reportAttributeAccessIssue]
        self.img_selection_lbl: QLabel = None  # pyright: ignore [reportAttributeAccessIssue]
        self.selected_image_count: QLabel = None  # pyright: ignore [reportAttributeAccessIssue]
        self.selection_listbox: QListWidget = None  # pyright: ignore [reportAttributeAccessIssue]
        self.mini_preview_lbl: ImageLabel = None  # pyright: ignore [reportAttributeAccessIssue]
        self.seek_left_btn: QToolButton = None  # pyright: ignore [reportAttributeAccessIssue]
        self.seek_right_btn: QToolButton = None  # pyright: ignore [reportAttributeAccessIssue]
        self.de_select_images_btn: QToolButton = None  # pyright: ignore [reportAttributeAccessIssue]
        self.select_images_btn: QToolButton = None  # pyright: ignore [reportAttributeAccessIssue]
        self.confirm_selection_btn: QToolButton = None  # pyright: ignore [reportAttributeAccessIssue]

        # images vars
        self.image_path = None
        if self.comparison_images:
            self.image_path = self.comparison_images[self.current_selected_index]
        self.image_label = ImageLabel()
        self.image_label.setImage(QImage(self.image_path))

        self.tabbed_widget = QTabWidget()
        tab1 = self._build_image_tab()
        self.tabbed_widget.addTab(tab1, "Images")

        if self.comparison_mode in {
            ScreenShotMode.SIMPLE_SS_COMP,
            ScreenShotMode.ADV_SS_COMP,
        }:
            self.sync_images = [x for x in self.img_sync_dir.glob("*.png")]
            self.sync_image_index = 0
            self.sync_image = self.sync_images[self.sync_image_index]
            self.reference_label = ImageLabel()
            self.reference_label.setImage(QImage(self.sync_image))

            tab2 = self._build_sync_tab()
            tab2.offset_applied.connect(self.accept_offset)
            self.tabbed_widget.addTab(tab2, "Sync")

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabbed_widget)

    def _build_image_tab(self):
        if not self.image_path:
            raise AttributeError("Cannot build image tab with invalid image_path")
        image_info_box = QGroupBox("Image Info")
        self.img_path_lbl = QLabel(self.image_path.name)
        self.resolution_lbl = QLabel()
        self.img_selection_lbl = QLabel(f"1 of {self.comparison_images_total}")

        image_info_box_layout = QHBoxLayout(image_info_box)
        image_info_box_layout.addWidget(self.img_path_lbl)
        image_info_box_layout.addWidget(
            self.resolution_lbl, stretch=2, alignment=Qt.AlignmentFlag.AlignRight
        )
        image_info_box_layout.addSpacing(20)
        image_info_box_layout.addWidget(
            self.img_selection_lbl, alignment=Qt.AlignmentFlag.AlignRight
        )

        info_box = QGroupBox("Info")
        info_box.setMinimumWidth(200)

        self.selected_image_count = QLabel()

        info_box_layout = QHBoxLayout(info_box)
        info_box_layout.addWidget(self.selected_image_count)

        preview_box = QGroupBox("Image Preview")
        preview_box_layout = QVBoxLayout(preview_box)
        preview_box_layout.addWidget(self.image_label)

        selection_box = QGroupBox("Selection")
        selection_box.setMinimumWidth(200)
        self.selection_listbox = QListWidget()
        self.selection_listbox.setFrameShape(QFrame.Shape.NoFrame)
        self.selection_listbox.itemSelectionChanged.connect(self._update_preview_img)
        selection_box_layout = QVBoxLayout(selection_box)
        selection_box_layout.setContentsMargins(0, 0, 0, 0)
        selection_box_layout.addWidget(self.selection_listbox)

        mini_preview_box = QGroupBox("Preview")
        self.mini_preview_lbl = ImageLabel()
        mini_preview_box_layout = QVBoxLayout(mini_preview_box)
        mini_preview_box_layout.addWidget(self.mini_preview_lbl)

        self.seek_left_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.seek_left_btn, "ph.arrow-left-light", icon_size=QSize(24, 24)
        )
        self.seek_left_btn.clicked.connect(self._previous_image)

        self.seek_right_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.seek_right_btn, "ph.arrow-right-light", icon_size=QSize(24, 24)
        )
        self.seek_right_btn.clicked.connect(self._next_image)

        left_btn_layout = QHBoxLayout()
        left_btn_layout.addWidget(
            self.seek_left_btn, stretch=1, alignment=Qt.AlignmentFlag.AlignRight
        )
        left_btn_layout.addWidget(
            self.seek_right_btn, stretch=1, alignment=Qt.AlignmentFlag.AlignLeft
        )

        self.de_select_images_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.de_select_images_btn,
            "ph.arrow-line-left-light",
            icon_size=QSize(24, 24),
        )
        if self.comparison_mode == ScreenShotMode.BASIC_SS_GEN:
            self.de_select_images_btn.clicked.connect(self._remove_single_image)
        else:
            self.de_select_images_btn.clicked.connect(self._remove_image_pair)

        self.select_images_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.select_images_btn, "ph.arrow-line-right-light", icon_size=QSize(24, 24)
        )
        if self.comparison_mode == ScreenShotMode.BASIC_SS_GEN:
            self.select_images_btn.clicked.connect(self._select_single_image)
        else:
            self.select_images_btn.clicked.connect(self._select_image_pair)

        self.confirm_selection_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.confirm_selection_btn, "ph.check-light", icon_size=QSize(24, 24)
        )
        if self.min_required_selected_screens != 0:
            self.confirm_selection_btn.setEnabled(False)
        self.confirm_selection_btn.clicked.connect(self.close)

        right_btn_layout = QHBoxLayout()
        right_btn_layout.addWidget(
            self.de_select_images_btn, stretch=1, alignment=Qt.AlignmentFlag.AlignRight
        )
        right_btn_layout.addWidget(
            self.select_images_btn, stretch=1, alignment=Qt.AlignmentFlag.AlignLeft
        )
        right_btn_layout.addWidget(
            self.confirm_selection_btn,
            stretch=1,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        main_widget = QWidget()
        inner_layout = QGridLayout(main_widget)
        inner_layout.addWidget(image_info_box, 0, 0, 1, 2)
        inner_layout.addWidget(info_box, 0, 2, 1, 1)
        inner_layout.addWidget(preview_box, 1, 0, 2, 2)
        inner_layout.addWidget(selection_box, 1, 2, 1, 1)
        inner_layout.addWidget(mini_preview_box, 2, 2, 1, 1)
        inner_layout.addLayout(left_btn_layout, 3, 0, 1, 2)
        inner_layout.addLayout(right_btn_layout, 3, 2, 1, 1)
        inner_layout.setColumnStretch(0, 8)
        inner_layout.setColumnStretch(2, 2)
        inner_layout.setRowStretch(1, 5)
        inner_layout.setRowStretch(2, 3)

        self.setup_key_binds()

        return main_widget

    def show_image(self):
        self.image_path = self.comparison_images[self.current_selected_index]
        self.image_label.setImage(QImage(self.image_path))

    @Slot()
    def _next_image(self):
        if 0 <= self.current_selected_index < self.comparison_images_total - 1:
            self.current_selected_index += 1
            self.show_image()
            self._update_image_info_labels()

    @Slot()
    def _previous_image(self):
        if 0 < self.current_selected_index < self.comparison_images_total:
            self.current_selected_index -= 1
            self.show_image()
            self._update_image_info_labels()

    def _update_image_info_labels(self):
        if not self.image_path:
            raise AttributeError("Cannot build image tab with invalid image_path")
        self.img_path_lbl.setText(self.image_path.name)
        self.img_selection_lbl.setText(
            f"{self.current_selected_index + 1} of {self.comparison_images_total}"
        )

    def _clear_image_info_labels(self):
        self.img_path_lbl.clear()
        self.img_selection_lbl.clear()
        self.resolution_lbl.clear()

    @Slot()
    def _select_image_pair(self):
        if self.comparison_images_total != 0:
            # ensure we're not still in the process of moving an image
            if self.moving_image_s:
                return
            else:
                self.moving_image_s = True

            selected_index_var = None

            # find the pair
            try:
                find_image_pair = re.search(
                    r"(\d+)[ab]_\w+(?:__\d+?\]?)?.png",
                    str(Path(self.comparison_images[self.current_selected_index]).name),
                )
            except IndexError:
                self.moving_image_s = False
                return

            for full_name in self.comparison_images:
                if not find_image_pair:
                    raise AttributeError("Failed to find image pair")
                get_pair = re.findall(
                    rf"{find_image_pair.group(1)}[ab]_\w+(?:__\d+?\]?)?.png",
                    full_name.name,
                )

                # once a pair is found use pathlib rename to move them from the comparison list/dir to the selected dir/list
                if get_pair:
                    Path(Path(self.img_comparison_dir) / get_pair[0]).rename(
                        Path(self.img_selected_dir) / Path(get_pair[0]).name
                    )

                    # take the last item that is moved and update the selected index var
                    selected_index_var = (
                        int(
                            self.comparison_images.index(
                                Path(self.img_comparison_dir) / get_pair[0]
                            )
                        )
                        - 1
                    )

            if not selected_index_var:
                raise AttributeError("Failed to find selected_index_var")

            self._move_image_cleanup(selected_index_var)

        self.moving_image_s = False

    @Slot()
    def _select_single_image(self):
        if self.comparison_images_total != 0:
            # ensure we're not still in the process of moving an image
            if self.moving_image_s:
                return
            else:
                self.moving_image_s = True

            selected_index_var = None

            # move selected image
            found_image = Path(self.comparison_images[self.current_selected_index])

            # take the last item that is moved and update the selected index var
            selected_index_var = max(0, self.comparison_images.index(found_image) - 1)

            found_image.rename(Path(self.img_selected_dir) / found_image.name)

            self._move_image_cleanup(selected_index_var)

        self.moving_image_s = False

    def _move_image_cleanup(self, selected_index_var: int):
        # clear and update the listbox
        self.selection_listbox.clear()
        # TODO handle more extensions
        self.selection_listbox.addItems(
            sorted([x.name for x in Path(self.img_selected_dir).glob("*.png")])
        )

        # clear the comparison image list
        self.comparison_images.clear()

        # update the comparison image list with everything in the directory
        self.comparison_images = sorted(
            [x_img for x_img in Path(self.img_comparison_dir).glob("*.png")],
            key=lambda x: self._custom_numerical_sort(x.name),
        )
        self.comparison_images_total = len(self.comparison_images)

        # if there is anything left in the comparison img list
        if self.comparison_images:
            # attempt to use the same index (to keep position the same/close to the same) and update the image viewer
            try:
                self.current_selected_index = selected_index_var
                self.show_image()
            # if unable to use that index, subtract 2 from it (this prevents errors at the end of the list)
            except IndexError:
                self.current_selected_index = selected_index_var - 2
                self.show_image()

            # update labels
            self.img_path_lbl.setText(
                f"{Path(self.comparison_images[self.current_selected_index]).name}"
            )
            self.selected_image_count.setText(str(self.selection_listbox.count()))
            self._update_image_info_labels()

        # if there is nothing left in the comparison image box, clear the box and all the labels
        else:
            self.selected_image_count.setText(str(self.selection_listbox.count()))
            self._update_image_info_labels()
            self.image_label.clearImage()
            self._clear_image_info_labels()

        self._button_control()

    @Slot()
    def hotkey_remove_single_image_from_listbox(self):
        """Selects last moved image to be removed from listbox"""
        # check if we're moving still moving an image currently
        if self.moving_image_s:
            return
        else:
            self.moving_image_s = True

        try:
            count = self.selection_listbox.count()
            if count > 0:
                last_img = self.selection_listbox.item(count - 1).text()
                # move image back
                Path(Path(self.img_selected_dir) / last_img).rename(
                    Path(Path(self.img_comparison_dir) / last_img)
                )
                self.selection_listbox.takeItem(count - 1)
                self._remove_image_cleanup()
            self.moving_image_s = False
        except IndexError:
            self.moving_image_s = False

    @Slot()
    def hotkey_remove_image_pair_from_listbox(self):
        """Selects last moved image pair to be removed from listbox"""
        # check if we're moving still moving an image currently
        if self.moving_image_s:
            return
        else:
            self.moving_image_s = True

        try:
            count = self.selection_listbox.count()
            if count >= 2:
                # move images back
                # get the frame number to match the pairs
                get_frame_number = re.search(
                    r"(\d+)[ab]_\w+(?:__\d+?\]?)?.png",
                    self.selection_listbox.item(count - 1).text(),
                )

                if not get_frame_number:
                    raise AttributeError("Failed to determine get_frame_number")

                # get pairs
                get_pair = self.selection_listbox.findItems(
                    get_frame_number.group(1), Qt.MatchFlag.MatchContains
                )

                # once pair is found we'll iterate and move them back
                if get_pair:
                    for item in get_pair:
                        Path(Path(self.img_selected_dir) / item.text()).rename(
                            Path(Path(self.img_comparison_dir) / item.text())
                        )

                self._remove_image_cleanup()
                self.selection_listbox.takeItem(count - 1)
                self.selection_listbox.takeItem(count - 1)
            self.moving_image_s = False
        except IndexError:
            self.moving_image_s = False

    @Slot()
    def _remove_image_pair(self):
        """removes pair from listbox function"""
        if self.moving_image_s:
            return
        else:
            self.moving_image_s = True

        if self.selection_listbox.currentItem():
            current_selection = self.selection_listbox.currentItem().text()

            # get the frame number to match the pairs
            get_frame_number = re.search(
                r"(\d+)[ab]_\w+(?:__\d+?\]?)?.png", current_selection
            )

            if not get_frame_number:
                raise AttributeError("Failed to determine get_frame_number")

            # get pairs
            get_pair = self.selection_listbox.findItems(
                get_frame_number.group(1), Qt.MatchFlag.MatchContains
            )

            # once pair is found we'll iterate and move them back
            if get_pair:
                for item in get_pair:
                    Path(Path(self.img_selected_dir) / item.text()).rename(
                        Path(Path(self.img_comparison_dir) / item.text())
                    )

            self._remove_image_cleanup()

        self.moving_image_s = False

    @Slot()
    def _remove_single_image(self):
        """removes single image from listbox"""
        if self.moving_image_s:
            return
        else:
            self.moving_image_s = True

        if self.selection_listbox.currentItem():
            current_selection = self.selection_listbox.currentItem().text()

            # move image back
            Path(Path(self.img_selected_dir) / current_selection).rename(
                Path(Path(self.img_comparison_dir) / current_selection)
            )

            self._remove_image_cleanup()

        self.moving_image_s = False

    def _remove_image_cleanup(self):
        # delete the list box and update it with what ever is left
        self.selection_listbox.clear()
        for img_file in sorted(Path(self.img_selected_dir).glob("*.png")):
            self.selection_listbox.addItem(img_file.name)

        # clear the comparison image list
        self.comparison_images.clear()

        # update the comparison image list with everything in the directory
        self.comparison_images = sorted(
            [x_img for x_img in Path(self.img_comparison_dir).glob("*.png")],
            key=lambda x: self._custom_numerical_sort(x.name),
        )
        self.comparison_images_total = len(self.comparison_images)

        # if there is at least 1 item in the list
        if self.comparison_images:
            # find index of current item
            # refresh the image viewer with the updated list while retaining current position
            try:
                self.current_selected_index = int(
                    self.comparison_images.index(
                        Path(Path(self.img_comparison_dir) / self.img_path_lbl.text())
                    )
                )
            except ValueError:
                self.current_selected_index = 0
            self.show_image()

            # update labels
            self.img_path_lbl.setText(
                f"{Path(self.comparison_images[self.current_selected_index]).name}"
            )
            self.selected_image_count.setText(str(self.selection_listbox.count()))
            self._update_image_info_labels()

        self._button_control()

    def _button_control(self):
        """
        Enables/disables buttons based on min/max required selected screens.
        Confirm is enabled only if min <= count <= max (if max is set).
        Select is enabled if count < max (if max is set).
        """
        count = self.selection_listbox.count()
        min_req = self.min_required_selected_screens
        max_req = self.max_required_selected_screens

        # Select button logic
        if max_req != 0 and count >= max_req:
            self.select_images_btn.setEnabled(False)
        else:
            self.select_images_btn.setEnabled(True)

        # Confirm button logic
        if min_req != 0:
            if (count < min_req) or (max_req != 0 and count > max_req):
                self.confirm_selection_btn.setEnabled(False)
            else:
                self.confirm_selection_btn.setEnabled(True)
        else:
            self.confirm_selection_btn.setEnabled(True)

    @Slot()
    def _update_preview_img(self):
        selected_item = self.selection_listbox.currentItem()
        img_path = Path(self.img_selected_dir) / selected_item.text()
        self.mini_preview_lbl.setImage(QImage(img_path))

    def _build_sync_tab(self):
        sync_tab_widget = SideBySideImage(self.img_sync_dir, self)
        return sync_tab_widget

    @Slot(int)
    def accept_offset(self, offset: int):
        """Accepts offset from sync tab widget"""
        self.re_sync_images.emit(offset)
        self.ignore_requirements = True
        self.close()

    @Slot()
    def closeEvent(self, event):
        if self.ignore_requirements:
            event.accept()
        else:
            if self.min_required_selected_screens != 0:
                if self.selection_listbox.count() < self.min_required_selected_screens:
                    if (
                        QMessageBox.question(
                            self,
                            "Confirm",
                            f"Your configuration requires {self.min_required_selected_screens} "
                            f"image(s) and you have only selected {self.selection_listbox.count()}."
                            "\n\nAre you sure you want to exit?",
                        )
                        is QMessageBox.StandardButton.No
                    ):
                        event.ignore()
                        return

            self.exit_viewer.emit([img for img in self.img_selected_dir.glob("*.png")])
            event.accept()

    def setup_key_binds(self):
        next_image_hotkey = QShortcut(QKeySequence("Right"), self)
        next_image_hotkey.activated.connect(self._next_image)

        last_image_hotkey = QShortcut(QKeySequence("Left"), self)
        last_image_hotkey.activated.connect(self._previous_image)

        add_image_hotkey = QShortcut(QKeySequence("Shift+Right"), self)
        if self.comparison_mode == ScreenShotMode.BASIC_SS_GEN:
            add_image_hotkey.activated.connect(self._select_single_image)
        else:
            add_image_hotkey.activated.connect(self._select_image_pair)

        remove_image_hotkey = QShortcut(QKeySequence("Shift+Left"), self)
        if self.comparison_mode == ScreenShotMode.BASIC_SS_GEN:
            remove_image_hotkey.activated.connect(
                self.hotkey_remove_single_image_from_listbox
            )
        else:
            remove_image_hotkey.activated.connect(
                self.hotkey_remove_image_pair_from_listbox
            )

    @staticmethod
    def _custom_numerical_sort(filename):
        """a helper to sort the images in the viewer properly when files are over 99 images"""
        match = re.search(r"(\d+)[ab]_", filename)
        if match:
            return int(match.group(1))
        else:
            return filename


if __name__ == "__main__":
    app = QApplication([])
    app.setStyle("Fusion")

    # viewer = ImageViewer(r"input")
    # viewer.show()
    app.exec()
