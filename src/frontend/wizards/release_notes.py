from typing import TYPE_CHECKING

from PySide6.QtWidgets import QCheckBox, QFrame, QScrollArea, QVBoxLayout, QWidget

from src.config.config import Config
from src.context.processing_context import ProcessingContext
from src.frontend.custom_widgets.dict_widget import DictWidget
from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class ReleaseNotes(BaseWizardPage):
    def __init__(
        self, config: Config, context: ProcessingContext, parent: "MainWindow"
    ) -> None:
        super().__init__(config, context, parent)

        self.setObjectName("releaseNotesPage")
        self.setTitle("""\
            <h4>Release Notes</h4><span style="font-size: 9pt; font-weight: normal;">
            <p>
                The currently selected output below will fill the token 
                <span style="font-weight: bold;">{{ release_notes }}</span> automatically if
                utilized in any of your <span style="font-weight: bold;">templates</span>.
            </p>""")
        self.setCommitPage(True)

        self.release_notes_toggle = QCheckBox("Enable Release Notes", self)
        self.release_notes_toggle.setToolTip(
            "If checked, the current selected output will be "
            "applied to the release notes token.\nIf un-checked, "
            "the release token will not be filled."
        )
        self.dict_widget = DictWidget(parent=self)
        self.dict_widget.main_layout.setContentsMargins(0, 0, 0, 0)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.addWidget(self.release_notes_toggle)
        content_layout.addWidget(self.dict_widget, stretch=1)

        self.main_scroll_area = QScrollArea(self)
        self.main_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.main_scroll_area.setWidgetResizable(True)
        self.main_scroll_area.setWidget(content_widget)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.main_scroll_area)
        self.setLayout(main_layout)

    def initializePage(self) -> None:
        self.release_notes_toggle.setChecked(
            self.config.cfg_payload.enable_release_notes
        )
        self.dict_widget.fill_data(self.config.cfg_payload.release_notes)

        # apply last used index
        if self.config.cfg_payload.last_used_release_note:
            combo_idx = self.dict_widget.combo.findText(
                self.config.cfg_payload.last_used_release_note
            )
            if combo_idx != -1:
                self.dict_widget.combo.setCurrentIndex(combo_idx)

    def validatePage(self) -> bool:
        super().validatePage()
        self._apply_release_notes()
        self._update_cfg()
        return True

    def _apply_release_notes(self) -> None:
        if self.release_notes_toggle.isChecked():
            get_notes = self.dict_widget.text_box.toPlainText()
            if get_notes and get_notes.strip():
                self.context.shared_data.release_notes = get_notes

    def _update_cfg(self) -> None:
        self.config.cfg_payload.enable_release_notes = (
            self.release_notes_toggle.isChecked()
        )
        self.config.cfg_payload.last_used_release_note = (
            self.dict_widget.combo.currentText()
        )
        self.config.cfg_payload.release_notes = self.dict_widget.get_data()
        self.config.save_config()
