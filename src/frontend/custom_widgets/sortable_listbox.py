from collections.abc import Sequence

from PySide6.QtCore import QModelIndex, QSize, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap


class SortableListBox(QWidget):
    item_moved = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sortableListBox")

        self.list_box = QListWidget(self)
        self.list_box.setFrameShape(QFrame.Shape.Box)
        self.list_box.setFrameShadow(QFrame.Shadow.Sunken)
        self.list_box.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_box.model().rowsMoved.connect(self._signal_move)

        self.move_up_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.move_up_btn, "ph.arrow-up-light", icon_size=QSize(20, 20)
        )
        self.move_up_btn.clicked.connect(self._move_up)

        self.move_down_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.move_down_btn, "ph.arrow-down-light", icon_size=QSize(20, 20)
        )
        self.move_down_btn.clicked.connect(self._move_down)

        button_layout = QVBoxLayout()
        button_layout.addWidget(self.move_up_btn)
        button_layout.addSpacerItem(
            QSpacerItem(
                1, 1, QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
            )
        )
        button_layout.addWidget(self.move_down_btn)

        self.main_layout = QHBoxLayout(self)
        self.main_layout.addWidget(self.list_box, stretch=1)
        self.main_layout.addLayout(button_layout)

    def load_items(self, items: Sequence[str]) -> None:
        self.list_box.clear()
        if items:
            self.list_box.addItems(items)

    def get_items(self) -> list[str]:
        items = (
            [self.list_box.item(i).text() for i in range(self.list_box.count())]
            if self.list_box.count() > 0
            else []
        )

        return items

    @Slot()
    def _move_up(self) -> None:
        self._move_item(1)

    @Slot()
    def _move_down(self) -> None:
        self._move_item(-1)

    def _move_item(self, move: int) -> None:
        current_row = self.list_box.currentRow()
        if current_row == -1:
            return

        new_row = current_row - move
        if 0 <= new_row < self.list_box.count():
            item = self.list_box.takeItem(current_row)
            self.list_box.insertItem(new_row, item)

            # keep selection on moved item
            self.list_box.setCurrentRow(new_row)

            # emit moved signal
            self._signal_move()

    @Slot(QModelIndex, int, int, QModelIndex, int)
    def _signal_move(
        self,
        _sourceParent: QModelIndex | None = None,
        _sourceStart: int | None = None,
        _sourceEnd: int | None = None,
        _destinationParent: QModelIndex | None = None,
        _destinationRow: int | None = None,
    ) -> None:
        self.item_moved.emit()
