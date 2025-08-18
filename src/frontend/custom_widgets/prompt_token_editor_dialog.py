from collections.abc import Sequence
from functools import partial
from typing import Any

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.frontend.custom_widgets.list_box_editor import ListBoxEditor
from src.frontend.utils import set_top_parent_geometry


class PromptTokenEditorDialog(QDialog):
    def __init__(
        self,
        items: Sequence[str] | dict[str, Any],
        warn_missing: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("promptTokenEditorDialog")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setWindowTitle("Prompt Token Editor")
        set_top_parent_geometry(self)

        self._results_data: dict[str, str] | None = None
        # key: QListWidgetItem, value: QTimer
        self._flash_timers = {}

        lbl = QLabel(
            '<h4 style="margin: 0; margin-bottom: 3px; padding: 0;">Prompt Tokens:</h4>'
            "<span>Select the token to edit the corresponding value in the editor.</span>",
            parent=self,
            wordWrap=True,
        )

        self.editor = ListBoxEditor(self)
        if items:
            self.editor.load_items(items)

        self.warn_on_missing = QCheckBox("Warn On Missing", self)
        self.warn_on_missing.setToolTip(
            "If disabled you will not be warned when tokens are unfilled"
        )
        self.warn_on_missing.setChecked(warn_missing)

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setFixedWidth(150)

        ok_btn = QPushButton("Okay", self)
        ok_btn.clicked.connect(self._on_accept)
        ok_btn.setFixedWidth(150)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(lbl)
        self.main_layout.addWidget(self.editor, stretch=1)
        self.main_layout.addWidget(
            self.warn_on_missing, alignment=Qt.AlignmentFlag.AlignLeft
        )
        self.main_layout.addLayout(btn_layout)

    @Slot()
    def _on_accept(self):
        # retrieve edited data from the editor
        self._results_data = self.editor.get_data()
        if self.warn_on_missing.isChecked():
            empty_keys = [k for k, v in self._results_data.items() if not v]
            if empty_keys:
                self.editor.listbox.clearSelection()
                self.editor.listbox.clearFocus()

                reply = QMessageBox.question(
                    self,
                    "Continue?",
                    f"The following tokens have no value:\n\n{', '.join(empty_keys)}\n\nContinue anyway?",
                )
                if reply is not QMessageBox.StandardButton.Yes:
                    for key in empty_keys:
                        item = self.editor.get_item_widget(key)
                        if item:
                            self._set_flash_color(item)
                            # stop any existing timer for this key
                            if key in self._flash_timers:
                                self._flash_timers[key].stop()
                            timer = QTimer(self, singleShot=True, interval=2000)
                            timer.timeout.connect(partial(self._reset_color, item, key))
                            timer.start()
                            self._flash_timers[key] = timer
                    return
        self.accept()

    def get_results(self):
        return self._results_data

    def _reset_color(self, item: QListWidgetItem, key: str) -> None:
        item.setForeground(QBrush())
        item.setBackground(QBrush())
        # remove timer reference
        if key in self._flash_timers:
            del self._flash_timers[key]

    @staticmethod
    def _set_flash_color(item: QListWidgetItem) -> None:
        item.setBackground(Qt.GlobalColor.yellow)
        item.setForeground(Qt.GlobalColor.black)
