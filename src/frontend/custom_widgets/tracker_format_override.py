from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.backend.token_replacer import ColonReplace
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.replacement_list_widget import (
    LoadedReplacementListWidget,
)
from src.frontend.utils import build_h_line


class TrackerFormatOverride(QWidget):
    setting_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.enabled_checkbox = QCheckBox("Enable Override", self)
        self.enabled_checkbox.checkStateChanged.connect(self._enabled_toggled)

        title_colon_replace_lbl, self.title_colon_replace = (
            self._build_colon_replace_combo("Colon Replacement", self)
        )
        self.title_colon_replace.currentIndexChanged.connect(
            self._colon_replace_changed
        )

        over_ride_format_title_lbl = QLabel("Token", self)
        over_ride_format_title_lbl.setToolTip(
            "Select which tokens are used to generate the renamed file name"
        )
        self.over_ride_format_title = QLineEdit(self)
        self.over_ride_format_title.textChanged.connect(self._format_title_changed)

        over_ride_format_file_name_token_example_lbl = QLabel("Example", self)
        self.over_ride_format_file_name_token_example = QLineEdit(self)
        self.over_ride_format_file_name_token_example.setDisabled(True)

        over_ride_table_str = """\
            <h4 style="margin: 0; margin-bottom: 6px;">Character Map</h4>
            <span>The character map allows users to customize any necessary character replacements required 
            for use with the <span style="font-weight: 500;">Release Title</span>. The default 
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

        self.over_ride_replacement_table_lbl = QLabel(over_ride_table_str, self)
        self.over_ride_replacement_table_lbl.setWordWrap(True)
        self.over_ride_replacement_table = LoadedReplacementListWidget(parent=self)
        self.over_ride_replacement_table.main_layout.setContentsMargins(0, 0, 0, 0)
        self.over_ride_replacement_table.rows_changed.connect(self._rules_changed)
        self.over_ride_replacement_table.cell_changed.connect(self._cell_changed)

        self.over_ride_inner_widget = QWidget()
        self.over_ride_inner_widget.hide()  # default to hidden
        self.over_ride_inner_layout = QVBoxLayout(self.over_ride_inner_widget)
        self.over_ride_inner_layout.setContentsMargins(6, 0, 0, 0)
        self.over_ride_inner_layout.addWidget(title_colon_replace_lbl)
        self.over_ride_inner_layout.addWidget(self.title_colon_replace)
        self.over_ride_inner_layout.addWidget(build_h_line((6, 1, 6, 1)))
        self.over_ride_inner_layout.addWidget(over_ride_format_title_lbl)
        self.over_ride_inner_layout.addWidget(self.over_ride_format_title)

        self.over_rider_inner_nested_layout = QVBoxLayout()
        self.over_rider_inner_nested_layout.setContentsMargins(20, 0, 0, 0)
        self.over_rider_inner_nested_layout.addWidget(
            over_ride_format_file_name_token_example_lbl
        )
        self.over_rider_inner_nested_layout.addWidget(
            self.over_ride_format_file_name_token_example
        )
        self.over_rider_inner_nested_layout.addWidget(
            self.over_ride_replacement_table_lbl
        )
        self.over_rider_inner_nested_layout.addWidget(self.over_ride_replacement_table)

        self.over_ride_inner_layout.addLayout(self.over_rider_inner_nested_layout)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.enabled_checkbox)
        self.main_layout.addWidget(self.over_ride_inner_widget)

    @Slot(Qt.CheckState)
    def _enabled_toggled(self, check_state: Qt.CheckState) -> None:
        if check_state is Qt.CheckState.Checked:
            self.over_ride_inner_widget.show()
        else:
            self.over_ride_inner_widget.hide()

    @Slot(int)
    def _colon_replace_changed(self, _idx: int) -> None:
        self.setting_changed.emit()

    @Slot(str)
    def _format_title_changed(self, _txt: str) -> None:
        self.setting_changed.emit()

    @Slot(int, int)
    def _cell_changed(self, _row: int, _col: int) -> None:
        self.setting_changed.emit()

    @Slot(list)
    def _rules_changed(self, _data: list) -> None:
        self.setting_changed.emit()

    def set_colon_replace(self, item: str) -> None:
        selection = self.title_colon_replace.findText(item)
        if selection > -1:
            self.title_colon_replace.setCurrentIndex(selection)

    @staticmethod
    def _build_colon_replace_combo(
        lbl_txt: str,
        parent: QWidget,
    ) -> tuple[QLabel, CustomComboBox]:
        colon_replacement_lbl = QLabel(lbl_txt, parent)
        colon_replacement_lbl.setToolTip(
            "Select how NfoForge handles colon replacement"
        )
        colon_replacement_combo = CustomComboBox(
            disable_mouse_wheel=True, parent=parent
        )
        colon_replacement_combo.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        for colon_enum in ColonReplace:
            colon_replacement_combo.addItem(str(colon_enum), colon_enum.value)
        return colon_replacement_lbl, colon_replacement_combo
