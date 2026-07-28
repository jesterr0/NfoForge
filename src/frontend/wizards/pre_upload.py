from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import override

from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.frontend.wizards.client_options import ClientOptionsSection
from src.frontend.wizards.nfo_template import NfoTemplateSection
from src.frontend.wizards.release_notes import ReleaseNotesSection
from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class PreUploadPage(BaseWizardPage):
    """Review compact finalization settings before processing begins."""

    def __init__(
        self,
        config: ConfigManager,
        context: ProcessingContext,
        parent: "MainWindow",
    ) -> None:
        super().__init__(config, context, parent)
        self.setObjectName("preUploadPage")
        self.setTitle("Pre-upload")
        self.setSubTitle(
            "Review template assignments, release notes, and torrent-client options."
        )
        self.setCommitPage(True)

        explanation = QLabel(
            "These settings apply to the current release. Persistent template "
            "and release-note changes are saved when you continue.",
            self,
            wordWrap=True,
        )

        self.error_label = QLabel(self, wordWrap=True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setStyleSheet("color: #ff0033; font-weight: bold;")
        self.error_label.hide()

        self.nfo_templates = NfoTemplateSection(
            config,
            context,
            parent,
            parent=self,
        )
        self.release_notes = ReleaseNotesSection(config, context, parent=self)
        self.client_options = ClientOptionsSection(config, context, parent=self)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.nfo_templates)
        content_layout.addWidget(self.release_notes)
        content_layout.addWidget(self.client_options)
        content_layout.addStretch()

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(content)

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addWidget(self.error_label)
        layout.addWidget(self.scroll_area, stretch=1)

    @override
    def initializePage(self) -> None:
        self._clear_error()
        self.nfo_templates.load()
        self.release_notes.load()

        qbit_enabled = self.config.settings.torrent_clients.qbittorrent.enabled
        self.client_options.setVisible(qbit_enabled)
        if qbit_enabled:
            self.client_options.load()

    @override
    def validatePage(self) -> bool:
        super().validatePage()

        template_error = self.nfo_templates.validation_error()
        if template_error:
            self._show_error(template_error, self.nfo_templates)
            return False

        if not self.client_options.isHidden():
            client_error = self.client_options.validation_error()
            if client_error:
                self._show_error(client_error, self.client_options)
                return False

        self.release_notes.apply()
        self.config.save()
        self.nfo_templates.close_auxiliary_windows()
        self._clear_error()
        return True

    def _show_error(self, message: str, section: QWidget) -> None:
        self.error_label.setText(message)
        self.error_label.show()
        self.scroll_area.ensureWidgetVisible(section)

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.hide()
