import re

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from src.backend.utils.working_dir import RUNTIME_DIR
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.basic_code_editor import HighlightKeywords
from src.frontend.custom_widgets.color_selection_shape import ColorSelectionShape
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.template_selector import TemplateSelector
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import (
    build_auto_theme_svg_widget,
    build_h_line,
    create_form_layout,
)


class TemplatesSettings(BaseSettings):
    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("templatesSettings")

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)
        GSigs().settings_tab_changed.connect(self._on_tab_changed)
        GSigs().settings_close.connect(self._on_settings_closed)

        self.jinja_lbl = QLabel(
            '<span>Powered by </span><a href="https://jinja.palletsprojects.com/en/stable/">jinja2</a>',
            self,
        )
        self.jinja_lbl.setOpenExternalLinks(True)
        smaller_font = QApplication.font()
        smaller_font.setPointSize(7)
        self.jinja_lbl.setFont(smaller_font)
        self.jinja_icon = build_auto_theme_svg_widget(
            str(RUNTIME_DIR / "svg" / "jinja.svg"), 20, 20, self
        )
        self.jinja_icon.setFixedSize(20, 20)

        jinja_header_layout = QHBoxLayout()
        jinja_header_layout.addWidget(
            self.jinja_lbl, stretch=1, alignment=Qt.AlignmentFlag.AlignRight
        )
        jinja_header_layout.addWidget(
            self.jinja_icon, alignment=Qt.AlignmentFlag.AlignRight
        )

        self.block_start_str_lbl = QLabel("Block Start String", self)
        self.block_start_str_lbl.setToolTip(
            "The string marking the beginning of a block. Defaults to '{%'."
        )
        self.block_start_str_entry = QLineEdit(self)
        self.block_start_str_entry.textChanged.connect(
            self.update_jinja_engine_settings
        )

        self.block_end_str_lbl = QLabel("Block End String", self)
        self.block_end_str_lbl.setToolTip(
            "The string marking the end of a block. Defaults to '%}'."
        )
        self.block_end_str_entry = QLineEdit(self)
        self.block_end_str_entry.textChanged.connect(self.update_jinja_engine_settings)
        self.block_entries = (self.block_start_str_entry, self.block_end_str_entry)

        self.block_syntax_color = ColorSelectionShape(width=14, height=14, parent=self)
        self.block_syntax_color.setToolTip("Sets syntax highlighting color for blocks")
        self.block_syntax_color.color_changed.connect(
            self._update_block_entry_text_color
        )

        self.variable_start_str_lbl = QLabel("Variable Start String", self)
        self.variable_start_str_lbl.setToolTip(
            "The string marking the beginning of a print statement. Defaults to '{{'."
        )
        self.variable_start_str_entry = QLineEdit(self)
        self.variable_start_str_entry.textChanged.connect(
            self.update_jinja_engine_settings
        )

        self.variable_end_str_lbl = QLabel("Variable End String", self)
        self.variable_end_str_lbl.setToolTip(
            "The string marking the end of a print statement. Defaults to '}}'."
        )
        self.variable_end_str_entry = QLineEdit(self)
        self.variable_end_str_entry.textChanged.connect(
            self.update_jinja_engine_settings
        )
        self.variable_entries = (
            self.variable_start_str_entry,
            self.variable_end_str_entry,
        )

        self.variable_syntax_color = ColorSelectionShape(
            width=14, height=14, parent=self
        )
        self.variable_syntax_color.setToolTip(
            "Sets syntax highlighting color for variables"
        )
        self.variable_syntax_color.color_changed.connect(
            self._update_variable_entry_text_color
        )

        self.comment_start_str_lbl = QLabel("Comment Start String", self)
        self.comment_start_str_lbl.setToolTip(
            "The string marking the beginning of a comment. Defaults to '{#'."
        )
        self.comment_start_str_entry = QLineEdit(self)
        self.comment_start_str_entry.textChanged.connect(
            self.update_jinja_engine_settings
        )

        self.comment_end_str_lbl = QLabel("Comment End String", self)
        self.comment_end_str_lbl.setToolTip(
            "The string marking the end of a comment. Defaults to '#}'."
        )
        self.comment_end_str_entry = QLineEdit(self)
        self.comment_end_str_entry.textChanged.connect(
            self.update_jinja_engine_settings
        )
        self.comment_entries = (
            self.comment_start_str_entry,
            self.comment_end_str_entry,
        )

        self.comment_syntax_color = ColorSelectionShape(
            width=14, height=14, parent=self
        )
        self.comment_syntax_color.setToolTip(
            "Sets syntax highlighting color for comments"
        )
        self.comment_syntax_color.color_changed.connect(
            self._update_comment_entry_text_color
        )

        self.line_statement_prefix_lbl = QLabel("Line Statement Prefix", self)
        self.line_statement_prefix_lbl.setToolTip(
            "Check the documentation for line statements and how they work."
        )
        self.line_statement_prefix_entry = QLineEdit(self)
        self.line_statement_prefix_entry.textChanged.connect(
            self.update_jinja_engine_settings
        )

        self.line_statement_syntax_color = ColorSelectionShape(
            width=14, height=14, parent=self
        )
        self.line_statement_syntax_color.setToolTip(
            "Sets syntax highlighting color for line statements"
        )
        self.line_statement_syntax_color.color_changed.connect(
            self._update_line_statement_entry_text_color
        )

        self.line_comment_prefix_lbl = QLabel("Line Comment Prefix", self)
        self.line_comment_prefix_lbl.setToolTip(
            "Works like line statements, check the documentation for line statements and how they work."
        )
        self.line_comment_prefix_entry = QLineEdit(self)
        self.line_comment_prefix_entry.textChanged.connect(
            self.update_jinja_engine_settings
        )

        self.line_comment_syntax_color = ColorSelectionShape(
            width=14, height=14, parent=self
        )
        self.line_comment_syntax_color.setToolTip(
            "Sets syntax highlighting color for line comments"
        )
        self.line_comment_syntax_color.color_changed.connect(
            self._update_line_comment_entry_text_color
        )

        self.trim_blocks_toggle = QCheckBox("Trim Blocks", self)
        self.trim_blocks_toggle.toggled.connect(self.update_jinja_engine_settings)
        self.trim_blocks_toggle.setToolTip(
            "If set to True (checked), the first newline after a block is removed (block, not variable tag!). "
            "Default: True."
        )

        self.lstrip_blocks_toggle = QCheckBox("L-Strip Blocks", self)
        self.lstrip_blocks_toggle.toggled.connect(self.update_jinja_engine_settings)
        self.lstrip_blocks_toggle.setToolTip(
            "If set to True (checked), leading spaces and tabs are stripped from the start of a line to a block. "
            "Default: True."
        )

        self.keep_trailing_newline_toggle = QCheckBox("Keep Trailing Newline", self)
        self.keep_trailing_newline_toggle.toggled.connect(
            self.update_jinja_engine_settings
        )
        self.keep_trailing_newline_toggle.setToolTip(
            "If set to True (checked), the trailing newline is preserved when rendering templates.\nIf set to False (unchecked), a "
            "single newline, if present, will be stripped from the end of the template.\nDefault: False."
        )
        toggle_layout = QHBoxLayout()
        toggle_layout.setContentsMargins(6, 0, 6, 0)
        toggle_layout.addWidget(self.trim_blocks_toggle)
        toggle_layout.addWidget(self.lstrip_blocks_toggle)
        toggle_layout.addWidget(self.keep_trailing_newline_toggle)

        self.newline_sequence_lbl = QLabel("Newline Sequence", self)
        self.newline_sequence_lbl.setToolTip(
            "The sequence that starts a newline. Must be one of '\\r',\n"
            "'\\n' or '\\r\\n'. The default is '\\n' which is a "
            "useful default\nfor Linux and OS X systems as well as web applications."
        )
        self.newline_sequence = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        self.newline_sequence.addItems(("\\r", "\\n", "\\r\\n"))

        self.sandbox_enable_prompt_tokens = QCheckBox(
            "Enabled Prompt Tokens on Preview in Sandbox", self
        )
        self.sandbox_enable_prompt_tokens.setToolTip(
            "Enables prompt window for prompt tokens when using Sandbox.\n\nNote: "
            "Does not effect prompt tokens during processing."
        )

        sandbox_toggle_layout = QHBoxLayout()
        sandbox_toggle_layout.setContentsMargins(6, 0, 6, 0)
        sandbox_toggle_layout.addWidget(self.sandbox_enable_prompt_tokens)

        self.template_selector = TemplateSelector(
            config=self.config,
            sandbox=True,
            main_window=main_window,
            parent=self,
            toggle_prompt_tokens=self.sandbox_enable_prompt_tokens,
        )
        self.template_selector.setMinimumHeight(400)
        self.update_template_selector_syntax()

        self.add_layout(jinja_header_layout)
        self.add_layout(
            self.combine_forms(
                create_form_layout(
                    self.block_start_str_lbl, self.block_start_str_entry
                ),
                create_form_layout(
                    self.combine_lbl_color_selection(
                        self.block_end_str_lbl, self.block_syntax_color
                    ),
                    self.block_end_str_entry,
                ),
            ),
            add_stretch=True,
        )

        self.add_layout(
            self.combine_forms(
                create_form_layout(
                    self.variable_start_str_lbl, self.variable_start_str_entry
                ),
                create_form_layout(
                    self.combine_lbl_color_selection(
                        self.variable_end_str_lbl, self.variable_syntax_color
                    ),
                    self.variable_end_str_entry,
                ),
            )
        )

        self.add_layout(
            self.combine_forms(
                create_form_layout(
                    self.comment_start_str_lbl, self.comment_start_str_entry
                ),
                create_form_layout(
                    self.combine_lbl_color_selection(
                        self.comment_end_str_lbl, self.comment_syntax_color
                    ),
                    self.comment_end_str_entry,
                ),
            )
        )

        self.add_layout(
            self.combine_forms(
                create_form_layout(
                    self.combine_lbl_color_selection(
                        self.line_statement_prefix_lbl, self.line_statement_syntax_color
                    ),
                    self.line_statement_prefix_entry,
                ),
                create_form_layout(
                    self.combine_lbl_color_selection(
                        self.line_comment_prefix_lbl, self.line_comment_syntax_color
                    ),
                    self.line_comment_prefix_entry,
                ),
            )
        )

        self.add_layout(toggle_layout)
        self.add_layout(
            create_form_layout(self.newline_sequence_lbl, self.newline_sequence)
        )

        self.add_widget(build_h_line((6, 1, 6, 1)))
        self.add_layout(sandbox_toggle_layout)
        self.add_widget(build_h_line((6, 1, 6, 1)))
        self.add_widget(self.template_selector)

        self.add_layout(self.reset_layout)

        self._load_saved_settings()

    @Slot(object)
    def _update_block_entry_text_color(self, color: QColor) -> None:
        for widget in self.block_entries:
            self._update_text_color(widget, color)
        self.update_template_selector_syntax()

    @Slot(object)
    def _update_variable_entry_text_color(self, color: QColor) -> None:
        for widget in self.variable_entries:
            self._update_text_color(widget, color)
        self.update_template_selector_syntax()

    @Slot(object)
    def _update_comment_entry_text_color(self, color: QColor) -> None:
        for widget in self.comment_entries:
            self._update_text_color(widget, color)
        self.update_template_selector_syntax()

    @Slot(object)
    def _update_line_statement_entry_text_color(self, color: QColor) -> None:
        self._update_text_color(self.line_statement_prefix_entry, color)
        self.update_template_selector_syntax()

    @Slot(object)
    def _update_line_comment_entry_text_color(self, color: QColor) -> None:
        self._update_text_color(self.line_comment_prefix_entry, color)
        self.update_template_selector_syntax()

    @Slot()
    def _load_saved_settings(self) -> None:
        payload = self.config.cfg_payload
        self.block_start_str_entry.setText(payload.block_start_string)
        self.block_end_str_entry.setText(payload.block_end_string)
        block_color = QColor(self.config.cfg_payload.block_syntax_color)
        self._update_block_entry_text_color(block_color)
        self.block_syntax_color.update_color(block_color)

        self.variable_start_str_entry.setText(payload.variable_start_string)
        self.variable_end_str_entry.setText(payload.variable_end_string)
        variable_color = QColor(self.config.cfg_payload.variable_syntax_color)
        self._update_variable_entry_text_color(variable_color)
        self.variable_syntax_color.update_color(variable_color)

        self.comment_start_str_entry.setText(payload.comment_start_string)
        self.comment_end_str_entry.setText(payload.comment_end_string)
        comment_color = QColor(self.config.cfg_payload.comment_syntax_color)
        self._update_comment_entry_text_color(comment_color)
        self.comment_syntax_color.update_color(comment_color)

        self.line_statement_prefix_entry.setText(payload.line_statement_prefix)
        line_statement_color = QColor(
            self.config.cfg_payload.line_statement_syntax_color
        )
        self._update_line_statement_entry_text_color(line_statement_color)
        self.line_statement_syntax_color.update_color(line_statement_color)

        self.line_comment_prefix_entry.setText(payload.line_comment_prefix)
        line_comment_color = QColor(self.config.cfg_payload.line_comment_syntax_color)
        self._update_line_comment_entry_text_color(line_comment_color)
        self.line_comment_syntax_color.update_color(line_comment_color)

        self.trim_blocks_toggle.setChecked(payload.trim_blocks)
        self.lstrip_blocks_toggle.setChecked(payload.lstrip_blocks)
        get_newline_sequence_idx = self.newline_sequence.findText(
            payload.newline_sequence
        )
        if get_newline_sequence_idx > -1:
            self.newline_sequence.setCurrentIndex(get_newline_sequence_idx)
        self.keep_trailing_newline_toggle.setChecked(payload.keep_trailing_newline)
        self.sandbox_enable_prompt_tokens.setChecked(
            payload.enable_sandbox_prompt_tokens
        )

        self.template_selector.load_templates()

    @Slot()
    def _save_settings(self) -> None:
        self._save_template_edited()

        if not self._validate_tracker_templates():
            return

        if not self._save_inputs_valid():
            return

        self.config.cfg_payload.block_start_string = (
            self.block_start_str_entry.text().strip()
        )
        self.config.cfg_payload.block_end_string = (
            self.block_end_str_entry.text().strip()
        )
        self.config.cfg_payload.block_syntax_color = (
            self.block_syntax_color.get_hex_color()
        )

        self.config.cfg_payload.variable_start_string = (
            self.variable_start_str_entry.text().strip()
        )
        self.config.cfg_payload.variable_end_string = (
            self.variable_end_str_entry.text().strip()
        )
        self.config.cfg_payload.variable_syntax_color = (
            self.variable_syntax_color.get_hex_color()
        )

        self.config.cfg_payload.comment_start_string = (
            self.comment_start_str_entry.text().strip()
        )
        self.config.cfg_payload.comment_end_string = (
            self.comment_end_str_entry.text().strip()
        )
        self.config.cfg_payload.comment_syntax_color = (
            self.comment_syntax_color.get_hex_color()
        )

        self.config.cfg_payload.line_statement_prefix = (
            self.line_statement_prefix_entry.text().strip()
        )
        self.config.cfg_payload.line_statement_syntax_color = (
            self.line_statement_syntax_color.get_hex_color()
        )

        self.config.cfg_payload.line_comment_prefix = (
            self.line_comment_prefix_entry.text().strip()
        )
        self.config.cfg_payload.line_comment_syntax_color = (
            self.line_comment_syntax_color.get_hex_color()
        )

        self.config.cfg_payload.trim_blocks = self.trim_blocks_toggle.isChecked()
        self.config.cfg_payload.lstrip_blocks = self.lstrip_blocks_toggle.isChecked()
        self.config.cfg_payload.newline_sequence = self.newline_sequence.currentText()
        self.config.cfg_payload.keep_trailing_newline = (
            self.keep_trailing_newline_toggle.isChecked()
        )
        self.config.cfg_payload.enable_sandbox_prompt_tokens = (
            self.sandbox_enable_prompt_tokens.isChecked()
        )
        self.update_jinja_engine_settings()
        self.updated_settings_applied.emit()

    def _save_template_edited(self) -> None:
        if self.template_selector.template_edited():
            if (
                QMessageBox.question(
                    self,
                    "Save Template",
                    "Current template has been edited, would you like to save changes?",
                )
                is QMessageBox.StandardButton.Yes
            ):
                self.template_selector.save_template()

    def _validate_tracker_templates(self) -> bool:
        for tracker in self.template_selector.popup_button.get_checked_items():
            cur_tracker = TrackerSelection(tracker)
            if cur_tracker is TrackerSelection.PASS_THE_POPCORN:
                ptp_template = self.template_selector.backend.read_template(
                    self.config.cfg_payload.ptp_tracker.nfo_template
                )
                if ptp_template:
                    ptp_match_rule = r"^\n*?\s*?\{\{\s?media_info\s?\}\}\n*?\s*\{\{\s?screen_shots\s?\}\}"
                    if not re.search(ptp_match_rule, ptp_template, flags=re.MULTILINE):
                        if (
                            QMessageBox.question(
                                self,
                                "Warning",
                                "PassThePopcorn requires MediaInfo first followed by at least three screenshots. "
                                "The start of your template should be:\n{{ media_info }}\n{{ screen_shots }}\n...\n\n"
                                "Would you like to fix this now?",
                            )
                            is QMessageBox.StandardButton.Yes
                        ):
                            return False
            elif cur_tracker in (
                TrackerSelection.REELFLIX,
                TrackerSelection.AITHER,
                TrackerSelection.LST,
                TrackerSelection.DARK_PEERS,
                TrackerSelection.SHARE_ISLAND,
                TrackerSelection.UPLOAD_CX,
                TrackerSelection.ONLY_ENCODES,
            ):
                unit3d_template = self.template_selector.backend.read_template(
                    self.config.tracker_map[cur_tracker].nfo_template
                )
                if unit3d_template:
                    rf_match_rule = r"\{\{\s?screen_shots\s?\}\}"
                    if not re.search(
                        rf_match_rule, unit3d_template, flags=re.MULTILINE
                    ):
                        if (
                            QMessageBox.question(
                                self,
                                "Warning",
                                f"{cur_tracker} requires at least three screenshots in BBCode format. You "
                                "should assign a template with {{ screen_shots }} and ensure you utilize "
                                "the screenshot feature.\n\nWould you like to fix this now?",
                            )
                            is QMessageBox.StandardButton.Yes
                        ):
                            return False
        return True

    def _save_inputs_valid(self) -> bool:
        inputs_to_validate = (
            self.block_end_str_entry,
            self.block_end_str_entry,
            self.variable_start_str_entry,
            self.variable_end_str_entry,
            self.comment_start_str_entry,
            self.comment_end_str_entry,
        )
        for widget in inputs_to_validate:
            widget_text = widget.text().strip()
            if not widget_text or (widget_text == widget.placeholderText()):
                widget.setPlaceholderText("Input required")
                QMessageBox.warning(
                    self, "Warning", "You must fill all required inputs"
                )
                return False
        return True

    def apply_defaults(self) -> None:
        self.block_start_str_entry.setText(
            self.config.cfg_payload_defaults.block_start_string
        )
        self.block_end_str_entry.setText(
            self.config.cfg_payload_defaults.block_end_string
        )
        block_color = QColor(self.config.cfg_payload_defaults.block_syntax_color)
        self._update_block_entry_text_color(block_color)
        self.block_syntax_color.update_color(block_color)

        self.variable_start_str_entry.setText(
            self.config.cfg_payload_defaults.variable_start_string
        )
        self.variable_end_str_entry.setText(
            self.config.cfg_payload_defaults.variable_end_string
        )
        variable_color = QColor(self.config.cfg_payload_defaults.variable_syntax_color)
        self._update_variable_entry_text_color(variable_color)
        self.variable_syntax_color.update_color(variable_color)

        self.comment_start_str_entry.setText(
            self.config.cfg_payload_defaults.comment_start_string
        )
        self.comment_end_str_entry.setText(
            self.config.cfg_payload_defaults.comment_end_string
        )
        comment_color = QColor(self.config.cfg_payload_defaults.comment_syntax_color)
        self._update_comment_entry_text_color(comment_color)
        self.comment_syntax_color.update_color(comment_color)

        self.line_statement_prefix_entry.clear()
        line_statement_color = QColor(
            self.config.cfg_payload_defaults.line_statement_syntax_color
        )
        self._update_line_statement_entry_text_color(line_statement_color)
        self.line_statement_syntax_color.update_color(line_statement_color)

        self.line_comment_prefix_entry.clear()
        line_comment_color = QColor(
            self.config.cfg_payload_defaults.line_comment_syntax_color
        )
        self._update_line_comment_entry_text_color(line_comment_color)
        self.line_comment_syntax_color.update_color(line_comment_color)

        self.trim_blocks_toggle.setChecked(self.config.cfg_payload_defaults.trim_blocks)
        self.lstrip_blocks_toggle.setChecked(
            self.config.cfg_payload_defaults.lstrip_blocks
        )
        new_line_idx = self.newline_sequence.findText(
            self.config.cfg_payload_defaults.newline_sequence
        )
        if new_line_idx > -1:
            self.newline_sequence.setCurrentIndex(new_line_idx)
        else:
            self.newline_sequence.setCurrentIndex(1)
        self.keep_trailing_newline_toggle.setChecked(
            self.config.cfg_payload_defaults.keep_trailing_newline
        )
        self.sandbox_enable_prompt_tokens.setChecked(
            self.config.cfg_payload_defaults.enable_sandbox_prompt_tokens
        )
        self.update_jinja_engine_settings()

    @Slot(object)
    def update_jinja_engine_settings(self, _event=None) -> None:
        update_map = {
            "block_start_string": self.block_start_str_entry.text().strip(),
            "block_end_string": self.block_end_str_entry.text().strip(),
            "variable_start_string": self.variable_start_str_entry.text().strip(),
            "variable_end_string": self.variable_end_str_entry.text().strip(),
            "comment_start_string": self.comment_start_str_entry.text().strip(),
            "comment_end_string": self.comment_end_str_entry.text().strip(),
            "line_statement_prefix": self.line_statement_prefix_entry.text().strip(),
            "line_comment_prefix": self.line_comment_prefix_entry.text().strip(),
            "trim_blocks": self.trim_blocks_toggle.isChecked(),
            "lstrip_blocks": self.lstrip_blocks_toggle.isChecked(),
            "keep_trailing_newline": self.keep_trailing_newline_toggle.isChecked(),
        }

        # update jinja engine environment settings
        for attr, value in update_map.items():
            if value is not None:
                setattr(
                    self.config.jinja_engine.environment,
                    attr,
                    value if value != "" else None,
                )

        # update highlights
        self.update_template_selector_syntax()

    def update_template_selector_syntax(self) -> None:
        self.template_selector.text_edit.clear_keyword_highlights()
        self.template_selector.text_edit.highlight_keywords(
            self.jinja_syntax_highlights()
        )

    def jinja_syntax_highlights(self) -> list[HighlightKeywords]:
        syntax_highlights = []

        block_start_txt = self.block_start_str_entry.text().strip()
        block_end_txt = self.block_end_str_entry.text().strip()
        if block_start_txt and block_end_txt:
            block_color = self.block_syntax_color.get_hex_color()
            if block_color:
                syntax_highlights.append(
                    HighlightKeywords(
                        re.compile(
                            re.escape(block_start_txt)
                            + r".+?"
                            + re.escape(block_end_txt)
                        ),
                        block_color,
                        False,
                    )
                )

        variable_start_txt = self.variable_start_str_entry.text().strip()
        variable_end_txt = self.variable_end_str_entry.text().strip()
        if variable_start_txt and variable_end_txt:
            variable_color = self.variable_syntax_color.get_hex_color()
            if variable_color:
                syntax_highlights.append(
                    HighlightKeywords(
                        re.compile(
                            re.escape(variable_start_txt)
                            + r".+?"
                            + re.escape(variable_end_txt)
                        ),
                        variable_color,
                        False,
                    )
                )

        comment_start_txt = self.comment_start_str_entry.text().strip()
        comment_end_txt = self.comment_end_str_entry.text().strip()
        if comment_start_txt and comment_end_txt:
            comment_color = self.comment_syntax_color.get_hex_color()
            if comment_color:
                syntax_highlights.append(
                    HighlightKeywords(
                        re.compile(
                            re.escape(comment_start_txt)
                            + r".+?"
                            + re.escape(comment_end_txt)
                        ),
                        comment_color,
                        False,
                    )
                )

        line_statement_txt = self.line_statement_prefix_entry.text().strip()
        if line_statement_txt:
            line_statement_color = self.line_statement_syntax_color.get_hex_color()
            if line_statement_color:
                syntax_highlights.append(
                    HighlightKeywords(
                        re.compile(
                            r"^" + re.escape(line_statement_txt) + r".+?(?:\n|$)"
                        ),
                        line_statement_color,
                        False,
                    )
                )

        line_comment_prefix_txt = self.line_comment_prefix_entry.text().strip()
        if line_comment_prefix_txt:
            line_comment_color = self.line_comment_syntax_color.get_hex_color()
            if line_comment_color:
                syntax_highlights.append(
                    HighlightKeywords(
                        re.compile(
                            r"^" + re.escape(line_comment_prefix_txt) + r".+?(?:\n|$)"
                        ),
                        line_comment_color,
                        False,
                    )
                )

        return syntax_highlights

    @staticmethod
    def combine_lbl_color_selection(
        label: QLabel, color_picker: ColorSelectionShape
    ) -> QWidget:
        combined_widget = QWidget()
        layout = QHBoxLayout(combined_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addWidget(color_picker)
        return combined_widget

    @staticmethod
    def combine_forms(
        layout1: QLayout,
        layout2: QLayout,
        layout3: QLayout | None = None,
        margins: tuple[int, int, int, int] = (0, 0, 0, 0),
    ) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(*margins)
        layout.addLayout(layout1)
        layout.addLayout(layout2)
        if layout3:
            layout.addLayout(layout3)
        return layout

    @staticmethod
    def _update_text_color(widget: QLineEdit, color: QColor) -> None:
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Text, color)
        widget.setPalette(palette)

    @Slot()
    def _on_settings_closed(self) -> None:
        if self.template_selector.cached_sandbox_prompt_tokens:
            self.template_selector.cached_sandbox_prompt_tokens.clear()
        self._on_tab_changed()

    @Slot(int)
    def _on_tab_changed(self, _: int | None = None) -> None:
        # uncheck previewed template on change if needed
        if self.template_selector.preview_btn.isChecked():
            self.template_selector.preview_btn.setChecked(False)
            self.template_selector.preview_template()
        if self.template_selector.token_table_window:
            self.template_selector.token_table_window.close()
