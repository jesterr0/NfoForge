from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.frontend.custom_widgets.dict_widget import DictWidget


class ReleaseNotesSection(QGroupBox):
    """Compact release-note editor used by the pre-upload review page."""

    def __init__(
        self,
        config: ConfigManager,
        context: ProcessingContext,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Release Notes", parent)
        self.config = config
        self.context = context

        self.setCheckable(True)
        self.setToolTip(
            "When enabled, the selected note fills the {{ release_notes }} token."
        )

        self.dict_widget = DictWidget(parent=self)
        self.dict_widget.main_layout.setContentsMargins(0, 0, 0, 0)
        self.dict_widget.text_box.setMinimumHeight(120)
        self.toggled.connect(self.dict_widget.setVisible)

        layout = QVBoxLayout(self)
        layout.addWidget(self.dict_widget)

    def load(self) -> None:
        settings = self.config.settings.release_notes
        self.setChecked(settings.enabled)
        self.dict_widget.fill_data(settings.notes)

        if settings.last_used:
            combo_idx = self.dict_widget.combo.findText(settings.last_used)
            if combo_idx != -1:
                self.dict_widget.combo.setCurrentIndex(combo_idx)

    def apply(self) -> None:
        settings = self.config.settings.release_notes
        settings.enabled = self.isChecked()
        settings.last_used = self.dict_widget.combo.currentText()
        settings.notes = self.dict_widget.get_data()

        selected_notes = self.dict_widget.text_box.toPlainText()
        self.context.shared_data.release_notes = (
            selected_notes if self.isChecked() and selected_notes.strip() else None
        )
