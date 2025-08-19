from collections.abc import Sequence

from PySide6.QtGui import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.utils import build_h_line, set_top_parent_geometry


class MultiPromptDialog(QDialog):
    def __init__(self, title: str, prompts: Sequence[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setObjectName("multiPromptDialog")
        set_top_parent_geometry(self)

        self.inputs: dict[str, CodeEditor] = {}

        scroll = QScrollArea(self)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(0)

        total = len(prompts)
        for idx, prompt in enumerate(prompts, start=1):
            label = QLabel(prompt, self)
            edit = CodeEditor(pop_out_expansion=True, pop_out_name=f"Editor - {prompt}")
            edit.setFrameShape(QFrame.Shape.Box)
            edit.setFrameShadow(QFrame.Shadow.Sunken)
            edit.setFixedHeight(110)
            self.inputs[prompt] = edit

            scroll_layout.addWidget(label)
            scroll_layout.addSpacing(3)
            scroll_layout.addWidget(edit)
            scroll_layout.addSpacing(3)

            if idx < total:
                scroll_layout.addWidget(build_h_line((1, 1, 1, 1)))
                scroll_layout.addSpacing(6)

        scroll_layout.addStretch()

        scroll_content.setLayout(scroll_layout)
        scroll.setWidget(scroll_content)

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setFixedWidth(120)
        cancel_btn.clicked.connect(self.reject)

        ok_btn = QPushButton("Okay", self)
        ok_btn.setFixedWidth(120)
        ok_btn.clicked.connect(self.accept)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(scroll)
        self.main_layout.addLayout(btn_layout)

    def get_results(self) -> tuple[bool, dict[str, str] | None]:
        accepted = self.exec() == QDialog.DialogCode.Accepted
        results = (
            {k: v.toPlainText() for k, v in self.inputs.items()} if accepted else None
        )
        return accepted, results
