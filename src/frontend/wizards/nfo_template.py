import re
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QMessageBox

from src.config.config import Config
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.frontend.global_signals import GSigs
from src.frontend.custom_widgets.template_selector import TemplateSelector
from src.frontend.custom_widgets.basic_code_editor import HighlightKeywords

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class NfoTemplate(BaseWizardPage):
    def __init__(self, config: Config, parent: "MainWindow"):
        super().__init__(config, parent)
        self.setTitle("NFO Template")
        self.setObjectName("nfoTemplate")
        self.setCommitPage(True)

        self.config = config

        self.main_window = parent

        self.template_selector = TemplateSelector(
            self.config, False, self.main_window, self
        )
        self.template_selector.popup_button.clicked.connect(self._reset_highlight)
        self.template_selector.hide_parent.connect(GSigs().main_window_hide)

        layout = QVBoxLayout(self)
        layout.addWidget(self.template_selector)

    def initializePage(self):
        self.template_selector.load_templates()
        self.template_selector.text_edit.clear_keyword_highlights()
        self.template_selector.text_edit.highlight_keywords(
            self.get_syntax_highlights()
        )

        try:
            self.template_selector.read_template()
        except ValueError as v_error:
            QMessageBox.critical(
                self,
                "Error",
                f"You didn't select a template for your tracker:\n{v_error}",
            )
        except IndexError as i_error:
            QMessageBox.critical(self, "Error", f"Failed to load template:\n{i_error}")

    def get_syntax_highlights(self) -> list[HighlightKeywords]:
        payload = self.config.cfg_payload
        syntax_highlights = []
        if payload.block_start_string and payload.block_end_string:
            syntax_highlights.append(
                HighlightKeywords(
                    re.compile(
                        re.escape(payload.block_start_string)
                        + r".+?"
                        + re.escape(payload.block_end_string)
                    ),
                    payload.block_syntax_color,
                    False,
                )
            )
        if payload.variable_start_string and payload.variable_end_string:
            syntax_highlights.append(
                HighlightKeywords(
                    re.compile(
                        re.escape(payload.variable_start_string)
                        + r".+?"
                        + re.escape(payload.variable_end_string)
                    ),
                    payload.variable_syntax_color,
                    False,
                )
            )
        if payload.comment_start_string and payload.comment_end_string:
            syntax_highlights.append(
                HighlightKeywords(
                    re.compile(
                        re.escape(payload.comment_start_string)
                        + r".+?"
                        + re.escape(payload.comment_end_string)
                    ),
                    payload.comment_syntax_color,
                    False,
                )
            )
        if payload.line_comment_prefix:
            syntax_highlights.append(
                HighlightKeywords(
                    re.compile(
                        r"^" + re.escape(payload.line_statement_prefix) + r".+?(?:\n|$)"
                    ),
                    payload.line_statement_syntax_color,
                    False,
                )
            )
        if payload.line_comment_prefix:
            syntax_highlights.append(
                HighlightKeywords(
                    re.compile(
                        r"^" + re.escape(payload.line_comment_prefix) + r".+?(?:\n|$)"
                    ),
                    payload.line_comment_syntax_color,
                    False,
                )
            )
        return syntax_highlights

    def validatePage(self) -> bool:
        if not self._validate_tracker_selection():
            return False

        self.config.save_config()
        self.template_selector.destroy_token_window.emit()
        return True

    def _validate_tracker_selection(self) -> bool:
        if not self.config.shared_data.selected_trackers:
            raise AttributeError(
                "You have currently not selected any trackers, please start over and select your desired trackers"
            )

        for tracker in self.config.shared_data.selected_trackers:
            if not self.config.tracker_map[tracker].nfo_template:
                selected_trackers = {
                    str(x) for x in self.config.shared_data.selected_trackers
                }
                QMessageBox.information(
                    self,
                    "Information",
                    "You must assign a template for each selected tracker.\n\n"
                    f"Selected trackers: {', '.join(selected_trackers)}\n\n"
                    "Note:\nYou can do this by selecting a template and by "
                    "clicking the 'Trackers' button and checking your desired "
                    "tracker(s) for the currently selected template.",
                )
                self.template_selector.popup_button.setStyleSheet(
                    "border: 2px solid #ff0033; border-radius: 4px;"
                )
                return False

        return True

    def _reset_highlight(self) -> None:
        self.template_selector.popup_button.setStyleSheet("")

    def reset_page(self):
        self.template_selector.destroy_token_window.emit()
