from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

from src.context.processing_context import ProcessingContext
from src.frontend.custom_widgets.basic_code_editor import CodeEditor


class EncodeLogsSection(QGroupBox):
    """Run-scoped encode-log editor used by the pre-upload review page."""

    def __init__(
        self,
        context: ProcessingContext,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Encode Logs", parent)
        self.context = context

        self.setToolTip(
            "Plugins can populate this field during the wizard. Its contents fill "
            "the {{ encode_logs }} token."
        )

        self.text_box = CodeEditor(
            line_numbers=False,
            wrap_text=False,
            mono_font=True,
            pop_out_expansion=True,
            parent=self,
        )
        self.text_box.setMinimumHeight(130)
        self.text_box.setPlaceholderText(
            "Encode logs can be inserted or edited here. Additionally, you can fill this with a plugin."
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self.text_box)

    def load(self) -> None:
        self.text_box.setPlainText(self.context.shared_data.encode_logs or "")

    def apply(self) -> None:
        encode_logs = self.text_box.toPlainText()
        self.context.shared_data.encode_logs = (
            encode_logs if encode_logs.strip() else None
        )
