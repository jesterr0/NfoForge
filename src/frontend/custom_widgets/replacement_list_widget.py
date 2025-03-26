import re
from collections.abc import Sequence
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QSizePolicy,
    QToolButton,
    QSpacerItem,
)
from PySide6.QtCore import Qt, Signal, QTimer, Slot
from PySide6.QtGui import QColor, QPalette

from src.frontend.utils import build_auto_theme_icon_buttons


class LoadedReplacementListWidget(QWidget):
    """ReplacementListWidget with button controls built in"""

    rows_changed = Signal(list)
    cell_changed = Signal(int, int)
    defaults_applied = Signal()

    def __init__(
        self, default_rules: list[tuple[str, str]] | None = None, parent=None
    ) -> None:
        """
        Args:
            default_rules Optional[(list[tuple[str, str]])]: [(r"", r"[unidecode]")]
        """
        super().__init__(parent)
        self.setObjectName("loadedReplacementListWidget")
        self.default_rules = default_rules

        self.replacement_list_widget = ReplacementListWidget(self.default_rules, self)
        self.replacement_list_widget.rows_changed.connect(self.rows_changed)
        self.replacement_list_widget.cellChanged.connect(self.cell_changed)
        # self.replacement_list_widget.chan
        self.replacement_list_widget.set_defaults.connect(self.apply_defaults)
        self.replacement_list_widget.setMinimumHeight(180)

        self.add_row_btn: QToolButton = build_auto_theme_icon_buttons(
            QToolButton,
            "add_circle.svg",
            "addRowBtn",
            20,
            20,
            parent=self,
        )
        self.add_row_btn.clicked.connect(self.replacement_list_widget.add_row)
        self.add_row_btn.setToolTip("Add a row")

        self.delete_row_btn: QToolButton = build_auto_theme_icon_buttons(
            QToolButton,
            "delete.svg",
            "deleteRowBtn",
            20,
            20,
            parent=self,
        )
        self.delete_row_btn.clicked.connect(
            self.replacement_list_widget.remove_selected_row
        )
        self.delete_row_btn.setToolTip("Remove currently selected row")

        self.reset_table_btn: QToolButton = build_auto_theme_icon_buttons(
            QToolButton,
            "reset.svg",
            "resetTableBtn",
            20,
            20,
            parent=self,
        )
        self.reset_table_btn.clicked.connect(self.reset_table)
        self.reset_table_btn.setToolTip("Reset table to defaults")

        self.row_up_btn: QToolButton = build_auto_theme_icon_buttons(
            QToolButton,
            "arrow_upward.svg",
            "rowUpBtn",
            20,
            20,
            parent=self,
        )
        self.row_up_btn.clicked.connect(self.replacement_list_widget.move_up)
        self.row_up_btn.setToolTip("Move currently selected row up")

        self.row_down_btn: QToolButton = build_auto_theme_icon_buttons(
            QToolButton,
            "arrow_downward.svg",
            "rowDownBtn",
            20,
            20,
            parent=self,
        )
        self.row_down_btn.clicked.connect(self.replacement_list_widget.move_down)
        self.row_down_btn.setToolTip("Move currently selected row down")

        self.button_layout = QVBoxLayout()
        self.button_layout.addWidget(self.add_row_btn)
        self.button_layout.addWidget(self.delete_row_btn)
        self.button_layout.addWidget(self.reset_table_btn)
        self.button_layout.addSpacerItem(
            QSpacerItem(
                1, 1, QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
            )
        )
        self.button_layout.addWidget(self.row_up_btn)
        self.button_layout.addWidget(self.row_down_btn)

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.replacement_list_widget)
        self.main_layout.addLayout(self.button_layout)

    def add_row(self, txt1: str = "", txt2: str = "") -> None:
        """Add a new row to the table with default empty text."""
        self.add_row(txt1, txt2)

    def add_rows(self, rows: Sequence[tuple[str, str]]) -> None:
        """Convenient method to easily add more than one row at a time."""
        self.replacement_list_widget.add_rows(rows)

    def set_default_rules(self, rules: list[tuple[str, str]] | None) -> None:
        if rules:
            self.default_rules = rules
            self.replacement_list_widget.default_rules = rules

    def reset(self) -> None:
        self.replacement_list_widget.clearContents()
        self.replacement_list_widget.setRowCount(0)

    def apply_defaults(self) -> None:
        if self.default_rules:
            self.replacement_list_widget.add_rows(self.default_rules)

    def get_replacements(self) -> list[tuple[str, str]]:
        """
        Retrieve all replacements from the table.

        Returns:
            list of tuples: [(replace, with), ...]
        """
        return self.replacement_list_widget.get_replacements()

    @Slot()
    def reset_table(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Defaults",
                "Would you like to set this back to the default configuration?",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.blockSignals(True)
            self.reset()
            self.apply_defaults()
            self.blockSignals(False)
            self.defaults_applied.emit()


class ReplacementListWidget(QTableWidget):
    INVALID_COLOR = QColor(255, 0, 0, 150)
    VALID_COLOR = QColor(0, 0, 0, 0)

    # signals
    rows_changed = Signal(list)
    set_defaults = Signal()

    def __init__(
        self, default_rules: list[tuple[str, str]] | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("replacementListWidget")
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["Replace", "With"])
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setDragDropMode(QTableWidget.DragDropMode.InternalMove)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setAutoScroll(False)
        self._customize_highlight_color()
        self.default_rules = default_rules

        self._validation_active = True
        self._all_valid = True
        self.start_validation()

    def _customize_highlight_color(self) -> None:
        """
        Customize the selection highlight color with transparency to make it a
        bit easier to see where you are dragging and dropping.
        """
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 70, 232, 200))
        self.setPalette(palette)

    def add_rows(self, rows: Sequence[tuple[str, str]]) -> None:
        """Convenient method to easily add more than one row at a time."""
        for row in rows:
            self.add_row(row[0], row[1])

    @Slot()
    def add_row(self, txt1: str = "", txt2: str = "") -> None:
        """Add a new row to the table with default empty text."""
        current_rows = self.rowCount()
        self.insertRow(current_rows)

        replace_item = QTableWidgetItem(txt1)
        replace_item.setFlags(replace_item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)

        with_item = QTableWidgetItem(txt2)
        with_item.setFlags(with_item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)

        self.setItem(current_rows, 0, replace_item)
        self.setItem(current_rows, 1, with_item)
        self.rows_changed.emit(self.get_replacements())

    @Slot()
    def remove_selected_row(self) -> None:
        """Remove the currently selected row."""
        current_row = self.currentRow()
        if current_row >= 0:
            self.removeRow(current_row)
            self.rows_changed.emit(self.get_replacements())
            if (
                self.default_rules
                and (self.rowCount() <= 0)
                and current_row == 0
                and QMessageBox.question(
                    self,
                    "Defaults",
                    "Would you like to set this back to the default configuration?",
                )
                == QMessageBox.StandardButton.Yes
            ):
                self.set_defaults.emit()

    @Slot()
    def move_down(self) -> None:
        row = self.currentRow()
        if row < self.rowCount() - 1:
            self.insertRow(row + 2)
            for col in range(self.columnCount()):
                item = self.takeItem(row, col)
                self.setItem(row + 2, col, item)
            self.removeRow(row)
            self.setCurrentCell(row + 1, 0)
            self.rows_changed.emit(self.get_replacements())

    @Slot()
    def move_up(self) -> None:
        row = self.currentRow()
        if row > 0:
            self.insertRow(row - 1)
            for col in range(self.columnCount()):
                item = self.takeItem(row + 1, col)
                self.setItem(row - 1, col, item)
            self.removeRow(row + 1)
            self.setCurrentCell(row - 1, 0)
            self.rows_changed.emit(self.get_replacements())

    def dragMoveEvent(self, event) -> None:
        """Override this to ensure we can only drag within the bounds of the table."""
        if self.indexAt(event.position().toPoint()).isValid():
            super().dragMoveEvent(event)
            self.rows_changed.emit(self.get_replacements())
        else:
            event.ignore()

    def validate_regex(self) -> None:
        """
        Validate the regex in the "Replace" column for each row.

        Updates:
            self._all_valid: True if all rows are valid, False otherwise.
        """
        all_valid = True

        for row in range(self.rowCount()):
            replace_item = self.item(row, 0)
            replace_text = replace_item.text().strip() if replace_item else ""

            if replace_text:
                try:
                    re.compile(replace_text)
                except re.error as e:
                    replace_item.setBackground(self.INVALID_COLOR)
                    replace_item.setToolTip(
                        f"Invalid regex:\n{replace_text}\n\nError: {str(e)}"
                    )
                    all_valid = False
                else:
                    replace_item.setBackground(self.VALID_COLOR)
                    replace_item.setToolTip("")

        self._all_valid = all_valid

        # continue validation loop if active
        if self._validation_active:
            QTimer.singleShot(100, self.validate_regex)

    def is_all_valid(self) -> bool:
        """Check if all regex patterns are valid."""
        return self._all_valid

    def start_validation(self) -> None:
        """Start the validation loop."""
        self._validation_active = True
        self.validate_regex()

    def stop_validation(self) -> None:
        """Stop the validation loop."""
        self._validation_active = False

    def hideEvent(self, event) -> None:
        """Stop validation when the widget is hidden."""
        self.stop_validation()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        """Resume validation when the widget is shown."""
        self.start_validation()
        super().showEvent(event)

    def get_replacements(self) -> list[tuple[str, str]]:
        """
        Retrieve all replacements from the table.

        Returns:
            list of tuples: [(replace, with), ...]
        """
        replacements = []
        for row in range(self.rowCount()):
            replace_item = self.item(row, 0)
            with_item = self.item(row, 1)

            replace_text = replace_item.text() if replace_item else ""
            with_text = with_item.text() if with_item else ""

            if replace_text or with_text:
                # we need to use raw text here since we're messing with regex
                replacements.append((rf"{replace_text}", rf"{with_text}"))
        return replacements


if __name__ == "__main__":
    app = QApplication([])
    app.setStyle("fusion")
    # app.styleHints().setColorScheme(Qt.ColorScheme.Dark)

    widget = ReplacementListWidget()

    # Buttons layout
    btn_layout = QHBoxLayout()

    # Add Row button
    add_row_btn = QPushButton("Add Row")
    add_row_btn.clicked.connect(widget.add_row)

    # Remove Row button
    remove_row_btn = QPushButton("Remove Selected Row")
    remove_row_btn.clicked.connect(widget.remove_selected_row)

    # Move Up button
    move_up_btn = QPushButton("↑ Move Up")
    move_up_btn.clicked.connect(widget.move_up)

    # Move Down button
    move_down_btn = QPushButton("↓ Move Down")
    move_down_btn.clicked.connect(widget.move_down)

    # Add buttons to button layout
    btn_layout.addWidget(add_row_btn)
    btn_layout.addWidget(remove_row_btn)
    btn_layout.addWidget(move_up_btn)
    btn_layout.addWidget(move_down_btn)

    main_widget = QWidget()
    main_layout = QVBoxLayout(main_widget)
    main_layout.addWidget(widget)
    main_layout.addLayout(btn_layout)

    main_widget.resize(640, 480)
    main_widget.show()

    app.exec()
