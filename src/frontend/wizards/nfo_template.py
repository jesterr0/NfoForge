import re
from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.frontend.custom_widgets.basic_code_editor import HighlightKeywords
from src.frontend.custom_widgets.template_selector import TemplateSelector
from src.frontend.global_signals import GSigs

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class NfoTemplateSection(QGroupBox):
    """Template-assignment summary with the full editor available on demand."""

    def __init__(
        self,
        config: ConfigManager,
        context: ProcessingContext,
        main_window: "MainWindow",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("NFO Templates", parent)
        self.config = config
        self.context = context
        self.main_window = main_window
        self.editor_dialog: QDialog | None = None
        self.template_selector: TemplateSelector | None = None

        self.status_label = QLabel(self, wordWrap=True)
        self.configure_button = QPushButton("Configure Templates...", self)
        self.configure_button.clicked.connect(self._open_editor)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.configure_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addLayout(button_layout)

    def load(self) -> None:
        self._update_status()

    def validation_error(self) -> str | None:
        selected_trackers = self.context.shared_data.selected_trackers
        if not selected_trackers:
            return (
                "No trackers are selected. Return to Trackers and select at least one."
            )

        missing = [
            str(tracker)
            for tracker in selected_trackers
            if not self.config.settings.trackers.by_selection()[tracker].nfo_template
        ]
        if missing:
            self.configure_button.setStyleSheet(
                "border: 2px solid #ff0033; border-radius: 4px;"
            )
            return (
                "Assign an NFO template to every selected tracker. Missing: "
                f"{', '.join(missing)}"
            )

        self._clear_error()
        return None

    def close_auxiliary_windows(self) -> None:
        if self.template_selector is not None:
            self.template_selector.destroy_token_window.emit()

    @Slot()
    def _open_editor(self) -> None:
        template_selector = self._ensure_editor()
        template_selector.load_templates()
        template_selector.set_syntax_highlights(
            self._syntax_highlights(),
            self.config.settings.templates.warning_syntax_color,
        )
        try:
            template_selector.read_template()
        except (IndexError, ValueError) as error:
            QMessageBox.critical(
                self,
                "Template Error",
                f"Failed to load the selected template:\n{error}",
            )
        if self.editor_dialog is not None:
            self.editor_dialog.exec()
        self._update_status()

    def _ensure_editor(self) -> TemplateSelector:
        if self.template_selector is not None:
            return self.template_selector

        self.editor_dialog = QDialog(self)
        self.editor_dialog.setWindowTitle("Configure NFO Templates")
        self.editor_dialog.setModal(True)
        self.editor_dialog.resize(950, 650)

        self.template_selector = TemplateSelector(
            config=self.config,
            context=self.context,
            sandbox=False,
            main_window=self.main_window,
            parent=self.editor_dialog,
        )
        self.template_selector.popup_button.clicked.connect(self._clear_error)
        self.template_selector.hide_parent.connect(GSigs().main_window_hide)

        dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            parent=self.editor_dialog,
        )
        dialog_buttons.rejected.connect(self.editor_dialog.reject)

        dialog_layout = QVBoxLayout(self.editor_dialog)
        dialog_layout.addWidget(self.template_selector)
        dialog_layout.addWidget(dialog_buttons)
        return self.template_selector

    def _update_status(self) -> None:
        selected_trackers = self.context.shared_data.selected_trackers
        if not selected_trackers:
            self.status_label.setText(
                "Template assignments will be checked after trackers are selected."
            )
            return

        assignments = []
        tracker_settings = self.config.settings.trackers.by_selection()
        for tracker in selected_trackers:
            template = tracker_settings[tracker].nfo_template
            assignments.append(f"{tracker}: {template or 'Not assigned'}")
        self.status_label.setText("\n".join(assignments))

    @Slot()
    def _clear_error(self) -> None:
        self.configure_button.setStyleSheet("")

    def _syntax_highlights(self) -> list[HighlightKeywords]:
        settings = self.config.settings.templates
        return [
            HighlightKeywords(
                re.compile(r"\{%.*?%\}"),
                settings.block_syntax_color,
                False,
            ),
            HighlightKeywords(
                re.compile(r"\{\{.*?\}\}"),
                settings.variable_syntax_color,
                False,
            ),
            HighlightKeywords(
                re.compile(r"\{#.*?#\}"),
                settings.comment_syntax_color,
                False,
            ),
        ]
