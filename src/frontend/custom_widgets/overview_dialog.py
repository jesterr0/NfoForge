from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.utils import build_h_line
from src.frontend.utils import set_top_parent_geometry


class OverviewDialog(QDialog):
    def __init__(self, tracker_nfos: dict[TrackerSelection, str], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("overviewDialog")
        self.setWindowFlag(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setWindowTitle("Overview & Edit")
        set_top_parent_geometry(self)

        self._original = tracker_nfos
        self._edits = {}

        info_lbl = QLabel(f"<h3>{self.windowTitle()}</h3>", self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        self.text_edits = {}
        total = len(tracker_nfos.keys())
        for idx, (tracker, nfo) in enumerate(tracker_nfos.items(), start=1):
            label = QLabel(f'<span style="font-weight: bold;">{tracker}</span>', self)
            edit = CodeEditor(
                pop_out_expansion=True, pop_out_name=f"NFO ({tracker})", parent=self
            )
            edit.setPlainText(nfo)
            edit.setMinimumHeight(450)
            self.text_edits[tracker] = edit
            inner_layout.addWidget(label)
            inner_layout.addWidget(edit)
            if idx < total:
                inner_layout.addWidget(build_h_line((1, 1, 1, 1)))

        scroll.setWidget(inner)

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setMaximumWidth(150)
        cancel_btn.clicked.connect(self.reject)

        ok_btn = QPushButton("OK", self)
        ok_btn.setMaximumWidth(150)
        ok_btn.clicked.connect(self.accept)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(info_lbl)
        self.main_layout.addWidget(scroll)
        self.main_layout.addLayout(btn_layout)

    def get_results(self) -> dict[TrackerSelection, str]:
        if self.result() == QDialog.DialogCode.Accepted:
            return {
                TrackerSelection(tracker): edit.toPlainText()
                for tracker, edit in self.text_edits.items()
            }
        return self._original


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    app.setStyle("fusion")
    # Example input: dict[str, str]
    tracker_nfos = {
        TrackerSelection.MORE_THAN_TV: "NFO text for TrackerA...",
        TrackerSelection.TORRENT_LEECH: "NFO text for TrackerB...",
    }
    dialog = OverviewDialog(tracker_nfos)  # pyright: ignore[reportArgumentType]
    result = dialog.exec()
    if result == QDialog.DialogCode.Accepted:
        edited_nfos = dialog.get_results()
        print("Edited NFOs:", edited_nfos)
    else:
        print("Original NFOs:", tracker_nfos)
