import weakref

from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QColor, QCursor, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.backend.tokens import MOVIE_CLEAN_TITLE_REPLACE_DEFAULTS
from src.frontend.custom_widgets.replacement_list_widget import (
    LoadedReplacementListWidget,
)


class TokenTable(QWidget):
    def __init__(
        self,
        tokens: list,
        remove_brackets: bool = False,
        allow_edits: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.search_bar = QLineEdit(self)
        self.search_bar.setPlaceholderText("Search tokens...")
        self.search_bar.textChanged.connect(self.filter_table)

        self.allow_edits = allow_edits

        self.table = QTableWidget(self)
        self.table.setRowCount(len(tokens))
        self.table.setColumnCount(2)
        self.table.setMinimumHeight(180)
        self.table.setHorizontalHeaderLabels(("Token", "Description"))
        self.table.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.populate_table(tokens, remove_brackets)
        self.setup_table_properties()

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(self.search_bar)
        self.main_layout.addWidget(self.table)

        if self.allow_edits:
            movie_clean_title_custom_str = """\
                <h4 style="margin: 0; margin-bottom: 6px;">Character Map</h4>
                <span>The character map allows users to customize any necessary character replacements required 
                for use with the <span style="font-weight: 500;">{movie_clean_title}</span> token. The default 
                rules are already added, and can be restored with the <span style="font-weight: 500;">Reset</span> button.</span> 
                <br><br>
                The table requires the use of regex, except for the special characters identified here:
                <ul style="margin: 0; padding-left: 20px;">
                    <li style="margin-top: 4px;"><span style="font-weight: 500;">[unidecode]</span> - Unidecode input (should only be used alone).</li>
                    <li><span style="font-weight: 500;">[space]</span> - Adds a single space.</li>
                    <li><span style="font-weight: 500;">[remove]</span> - Replaces characters with nothing.</li>
                </ul>
                <br>
                <span style="font-style: italic; font-size: small;">Rules are processed in row order from top to bottom. 
                Use the arrow buttons to adjust row order.</span>"""
            replacement_list_widget_lbl = QLabel(movie_clean_title_custom_str)
            replacement_list_widget_lbl.setWordWrap(True)

            self.replacement_list_widget = LoadedReplacementListWidget(
                MOVIE_CLEAN_TITLE_REPLACE_DEFAULTS, self
            )
            self.main_layout.addSpacerItem(
                QSpacerItem(
                    1, 12, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
                )
            )
            self.main_layout.addWidget(replacement_list_widget_lbl)
            self.main_layout.addWidget(self.replacement_list_widget)

    def populate_table(self, tokens: list, remove_brackets: bool) -> None:
        for i, token in enumerate(tokens):
            token_name = (
                token.token
                if not remove_brackets
                else token.token.replace("{", "").replace("}", "")
            )
            self.table.setItem(
                i,
                0,
                QTableWidgetItem(token_name),
            )
            description_item = QTableWidgetItem(token.description)
            description_item.setToolTip(token.description)
            self.table.setItem(i, 1, description_item)

    def setup_table_properties(self) -> None:
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setAutoScroll(False)
        self.table.setToolTip("Click on a Token to copy it to the clipboard")
        self.table.cellPressed.connect(self.copy_token_to_clipboard)

    @Slot(str)
    def filter_table(self, text: str) -> None:
        for row in range(self.table.rowCount()):
            match = False
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item and text.lower() in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(row, not match)

    @Slot(int, int)
    def copy_token_to_clipboard(self, row: int, _: int):
        token = self.table.item(row, 0)
        if not token:
            return
        token_text = token.text()
        if token_text == "Copied!":
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(token_text)
        table_item = QTableWidgetItem("Copied!")
        table_item.setForeground(QColor("#e1401d"))
        self.table.setItem(row, 0, table_item)

        # use a weakref here to prevent runtime errors if the window is destroyed before the singleShot fires
        self_ref = weakref.ref(self)

        def restore():
            self_obj = self_ref()
            if self_obj and self_obj.table:
                self_obj.copy_status(row, 0, token_text)

        QTimer.singleShot(1000, restore)

    def copy_status(self, row: int, column: int, text: str):
        self.table.setItem(row, column, QTableWidgetItem(text))

    def load_replacement_rules(self, mvr_replace_rules: list[tuple[str, str]]) -> None:
        if self.allow_edits:
            self.replacement_list_widget.reset()
            self.replacement_list_widget.replacement_list_widget.add_rows(
                mvr_replace_rules
            )

    def reset(self) -> None:
        if self.allow_edits:
            self.replacement_list_widget.reset()
            self.replacement_list_widget.apply_defaults()
