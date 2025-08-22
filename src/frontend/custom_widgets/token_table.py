import weakref

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtGui import QColor, QCursor, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.backend.tokens import TITLE_CLEAN_REPLACE_DEF
from src.frontend.custom_widgets.dynamic_range_widget import DynamicRangeWidget
from src.frontend.custom_widgets.replacement_list_widget import (
    LoadedReplacementListWidget,
)
from src.frontend.utils import build_h_line


class TokenTable(QWidget):
    # signals for debounced state changes
    replacement_rules_changed = Signal(list)
    video_dynamic_range_changed = Signal(object)  # dict

    def __init__(
        self,
        tokens: list | None = None,
        remove_brackets: bool = False,
        show_tokens: bool = True,
        allow_edits: bool = False,
        debounce_delay: int = 300,
        parent=None,
    ) -> None:
        """
        Initialize TokenTable widget.

        Args:
            tokens: List of tokens to display
            remove_brackets: Whether to remove {} from token names
            show_tokens: Whether to show the token table
            allow_edits: Whether to allow editing of replacement rules and dynamic range
            debounce_delay: Delay in milliseconds before emitting change signals
            parent: Parent widget
        """
        super().__init__(parent)

        self.allow_edits = allow_edits

        self.main_layout = QVBoxLayout(self)

        if tokens and show_tokens:
            self.search_bar = QLineEdit(self)
            self.search_bar.setPlaceholderText("Search tokens...")
            self.search_bar.textChanged.connect(self.filter_table)

            self.table = QTableWidget(self)
            self.table.setColumnCount(2)
            self.table.setMinimumHeight(180)
            self.table.setHorizontalHeaderLabels(("Token", "Description"))
            self.table.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

            self.populate_table(tokens, remove_brackets)
            self.setup_table_properties()

            self.main_layout.addWidget(self.search_bar)
            self.main_layout.addWidget(self.table)

        if show_tokens and allow_edits:
            self.main_layout.addWidget(build_h_line((1, 6, 1, 6)))

        if self.allow_edits:
            # debounce timers for change detection
            self._replacement_rules_timer = QTimer(
                self, singleShot=True, interval=debounce_delay
            )
            self._replacement_rules_timer.timeout.connect(
                self._emit_replacement_rules_changed
            )

            self._video_dynamic_range_timer = QTimer(
                self, singleShot=True, interval=debounce_delay
            )
            self._video_dynamic_range_timer.timeout.connect(
                self._emit_video_dynamic_range_changed
            )

            movie_clean_title_custom_str = """\
                <h4 style="margin: 0; margin-bottom: 6px;">Character Map</h4>
                <span>The character map allows users to customize any necessary character replacements required 
                for use with the <span style="font-weight: bold;">{title_clean}</span> token. The default 
                rules are already added, and can be restored with the <span style="font-weight: bold;">Reset</span> button.</span> 
                <br><br>
                The table requires the use of regex, except for the special characters identified here:
                <ul style="margin: 0; padding-left: 20px;">
                    <li style="margin-top: 4px;"><span style="font-weight: bold;">[unidecode]</span> - Unidecode input (should only be used alone).</li>
                    <li><span style="font-weight: bold;">[space]</span> - Adds a single space.</li>
                    <li><span style="font-weight: bold;">[remove]</span> - Replaces characters with nothing.</li>
                </ul>
                <br>
                <span style="font-style: italic; font-size: small;">Rules are processed in row order from top to bottom. 
                Use the arrow buttons to adjust row order.</span>"""
            replacement_list_widget_lbl = QLabel(
                movie_clean_title_custom_str, parent=self, wordWrap=True
            )
            self.replacement_list_widget = LoadedReplacementListWidget(
                TITLE_CLEAN_REPLACE_DEF, self
            )

            self.replacement_list_widget.rows_changed.connect(
                self._on_replacement_rules_changed
            )
            self.replacement_list_widget.cell_changed.connect(
                self._on_replacement_cell_changed
            )
            self.replacement_list_widget.defaults_applied.connect(
                self._on_replacement_defaults_applied
            )

            self.main_layout.addWidget(replacement_list_widget_lbl)
            self.main_layout.addWidget(self.replacement_list_widget)

            video_dynamic_range_lbl_str = """\
                <h4 style="margin: 0; margin-bottom: 6px;">Dynamic Range Token</h4>
                <span>
                    Allows fine grain customization of what 
                    <span style="font-weight: bold;">{video_dynamic_range}</span> returns. 
                </span>"""
            video_dynamic_range_lbl = QLabel(
                video_dynamic_range_lbl_str, parent=self, wordWrap=True
            )
            self.video_dynamic_range = DynamicRangeWidget(parent=self)
            self.video_dynamic_range.main_layout.setContentsMargins(0, 0, 0, 0)
            self.video_dynamic_range.state_changed.connect(
                self._on_video_dynamic_range_changed
            )

            self.main_layout.addWidget(build_h_line((1, 6, 1, 6)))
            self.main_layout.addWidget(video_dynamic_range_lbl)
            self.main_layout.addWidget(self.video_dynamic_range)

    def populate_table(self, tokens: list, remove_brackets: bool) -> None:
        self.table.setRowCount(0)
        self.table.clearContents()

        self.table.setRowCount(len(tokens))

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

        self.setup_table_properties()

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

    @Slot(list)
    def _on_replacement_rules_changed(self, _rules: list) -> None:
        """Handle changes to replacement rules with debouncing"""
        self._replacement_rules_timer.start()

    @Slot(int, int)
    def _on_replacement_cell_changed(self, _row: int, _column: int) -> None:
        """Handle individual cell changes in replacement rules with debouncing"""
        self._replacement_rules_timer.start()

    @Slot()
    def _on_replacement_defaults_applied(self) -> None:
        """Handle when defaults are applied to replacement rules"""
        self._emit_replacement_rules_changed()

    @Slot(object)
    def _on_video_dynamic_range_changed(self, _data: dict) -> None:
        """Handle changes to video dynamic range with debouncing"""
        self._video_dynamic_range_timer.start()

    def _emit_replacement_rules_changed(self) -> None:
        """Emit the debounced replacement rules changed signal"""
        if self.allow_edits:
            rules = (
                self.replacement_list_widget.replacement_list_widget.get_replacements()
            )
            self.replacement_rules_changed.emit(rules)

    def _emit_video_dynamic_range_changed(self) -> None:
        """Emit the debounced video dynamic range changed signal"""
        if self.allow_edits:
            data = self.video_dynamic_range.to_dict()
            self.video_dynamic_range_changed.emit(data)
