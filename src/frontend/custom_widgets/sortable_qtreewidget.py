from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QFrame,
)


class SortableQTreeWidget(QTreeWidget):
    """
    Custom `QTreeWidget` that that provides a signal `items_re_arranged` that returns
    a tuple of tuple(s), letting the user know the rows in order. This signal is
    called each time a user re-arranges the rows and they are different than before
    the user moved them.

    Raises:
        ValueError: Invalid headers are supplied or invalid row data is added with
        `add_rows`

    Usage:
    >>> @Slot(list)
    >>> def items_updated(e: list) -> None:
    >>>     print(e)
    >>>
    >>> sortable_tree = SortableQTreeWidget(headers=("col1", "col2"))
    >>> sortable_tree.items_re_arranged.connect(items_updated)
    >>> sortable_tree.add_rows(("row1_col1", "row1_col2"), ("row2_col1", "row2_col2")))
    >>> sortable_tree.update_value("row1_col1", 1, "new information")
    """

    items_re_arranged = Signal(tuple)

    def __init__(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Sunken)
        self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.setRootIsDecorated(False)
        self.header_len = self._add_headers(headers)
        self.add_rows(rows)

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
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.setColumnCount(len(headers))
        self.setHeaderLabels(headers)
        return len(headers)

    def add_rows(self, items: Sequence[Sequence[str]] | None) -> None:
        """
        Updates the rows with data

        Args:
            items (Sequence[Sequence[str]]): Sequence of Sequence(s) containing strings for
            each row

        Raises:
            ValueError: If Sequence doesn't contain the correct amount of strings
        """
        if items:
            for item in items:
                if len(item) != self.header_len:
                    raise ValueError(
                        f"Error adding items (Input={len(item)} Required={self.header_len})"
                    )
                self._add_row(item)

    def _add_row(self, headers: Sequence[str]) -> None:
        item = QTreeWidgetItem(headers)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        self.addTopLevelItem(item)

    def get_item_values(self) -> list[tuple[str, ...]]:
        """Quickly returns a list of all elements in order how they are currently displayed"""
        return [
            tuple(self.topLevelItem(idx).text(i) for i in range(self.header_len))
            for idx in range(self.topLevelItemCount())
        ]

    def dropEvent(self, event) -> None:
        old_values = self.get_item_values()
        super().dropEvent(event)
        new_values = self.get_item_values()
        if old_values != new_values:
            self.items_re_arranged.emit(tuple(new_values))


if __name__ == "__main__":

    @Slot(list)
    def items_updated(e: list) -> None:
        print(e)

    app = QApplication([])
    tree = SortableQTreeWidget(headers=("Tracker", "Status", "Jack"))
    tree.show()
    tree.add_rows([("MTV", "Queued", "Blah"), ("TL", "Queued", "Blah")])
    tree.update_value("MTV", 2, "Howdyyyyy")
    tree.items_re_arranged.connect(items_updated)
    app.exec()
