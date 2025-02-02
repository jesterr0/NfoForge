from collections.abc import Sequence
from typing import Any
from typing_extensions import override
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QFrame,
    QComboBox,
    QWidget,
    QMenu,
)
from PySide6.QtGui import QAction, Qt


class ComboBoxTreeWidget(QTreeWidget):
    def __init__(
        self,
        headers: Sequence[str],
        rows: Sequence[tuple[Sequence[str], list[tuple[int, list[tuple[str, Any]]]]]]
        | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.combo_box_map: dict[tuple[QTreeWidgetItem, int], QComboBox] = {}
        self.combo_options: list[set] = []
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Sunken)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.verticalScrollBar().setSingleStep(20)
        self.setAutoScroll(False)
        self.setRootIsDecorated(False)
        self.header_len = self._add_headers(headers)
        self.add_rows(rows)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_context_menu)
        self.setToolTip("Right click anywhere to set all menus to the same item")

    def update_value(self, key: str, col: int, new_value: str) -> str | None:
        """
        Search for the row with `key`. You can then provide the `col`
        that you'd like to update, and finally provided the `new_value`
        for the updated cell contents

        Args:
            key (str): Key to search the rows
            col (int): Column to target where we are updating based on the searched row
            new_value (str): Value to update the cell based on the key and column

        Returns:
            Optional(None): Returns the key if it was completed successfully otherwise it returns
            None.
        """
        key_exists = None
        for idx in range(self.topLevelItemCount()):
            sub_item = self.topLevelItem(idx)
            if sub_item.text(0) == key:
                sub_item.setText(col, new_value)
                return key
        return key_exists

    def _add_headers(self, headers: Sequence[str]) -> int:
        if not headers:
            raise ValueError("You must supply at least one header")
        self.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setColumnCount(len(headers))
        self.setHeaderLabels(headers)
        return len(headers)

    def add_rows(
        self,
        items: Sequence[tuple[Sequence[str], list[tuple[int, list[tuple[str, Any]]]]]]
        | None,
    ) -> None:
        if items:
            for row_data, combo_data in items:
                if len(row_data) != self.header_len:
                    raise ValueError(
                        f"Error adding items (Input={len(row_data)} Required={self.header_len})"
                    )
                self._add_row(row_data, combo_data)

    def add_row(
        self,
        headers: Sequence[str],
        combo_data: list[tuple[int, list[tuple[str, Any]]]] | None = None,
    ) -> None:
        if len(headers) != self.header_len:
            raise ValueError(
                f"Error adding row (Input={len(headers)} Required={self.header_len})"
            )
        self._add_row(headers, combo_data)

    def _add_row(
        self,
        headers: Sequence[str],
        combo_data: list[tuple[int, list[tuple[str, Any]]]] | None,
    ) -> None:
        item = QTreeWidgetItem(headers)
        self.addTopLevelItem(item)

        if combo_data:
            for col_index, combo_items in combo_data:
                self.add_combobox_to_row(item, col_index, combo_items)

    def add_combobox_to_row(
        self, item: QTreeWidgetItem, col_index: int, combo_items: list[tuple[str, Any]]
    ) -> None:
        combo_box = QComboBox()
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(combo_box, stretch=3)
        layout.addStretch(2)

        option_set = set()
        for txt, data in combo_items:
            combo_box.addItem(txt, data)
            option_set.add(txt)

        self.combo_options.append(option_set)
        self.combo_box_map[(item, col_index)] = combo_box
        self.setItemWidget(item, col_index, widget)

    def get_common_options(self) -> set[str]:
        """Finds options that exist in **every** combo box in the widget."""
        if not self.combo_options:
            return set()
        return set.intersection(*self.combo_options)

    def set_all_comboboxes(self, value: str) -> None:
        for (_item, _idx), combo_box in self.combo_box_map.items():
            index = combo_box.findText(value)
            if index != -1:
                combo_box.setCurrentIndex(index)

    def _open_context_menu(self, position) -> None:
        """Opens the right-click context menu for setting all combo boxes in a column"""
        common_options = self.get_common_options()
        if common_options:
            menu = QMenu(self)
            for value in sorted(common_options):
                action = QAction(f"Set all to '{value}'", self)
                action.triggered.connect(lambda _, v=value: self.set_all_comboboxes(v))
                menu.addAction(action)
            menu.exec(self.mapToGlobal(position))

    @override
    def clear(self) -> None:
        super().clear()
        self.combo_box_map.clear()
        self.combo_options.clear()


if __name__ == "__main__":
    app = QApplication([])
    app.setStyle("Fusion")

    tree = ComboBoxTreeWidget(
        headers=("Tracker", "Image Host", "Status"),
        rows=[
            (
                ["MTV", "", "Queued"],
                [(1, [("Option1", 1), ("Option2", 2), ("OptionC", "data")])],
            ),
            (
                ["TL", "", "Queued"],
                [(1, [("OptionA", "A"), ("OptionB", "B"), ("OptionC", "data")])],
            ),
        ],
    )
    tree.show()

    app.exec()
