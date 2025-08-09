from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.utils import set_top_parent_geometry


class OverviewDialog(QDialog):
    def __init__(
        self, tracker_nfos: dict[TrackerSelection, dict[str | None, str]], parent=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("overviewDialog")
        self.setWindowFlag(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setWindowTitle("Overview & Edit")
        set_top_parent_geometry(self)

        self._original = tracker_nfos
        self._edits = {}

        info_lbl = QLabel(
            f'<h3 style="margin: 0; margin-bottom: 6px;">{self.windowTitle()}</h3>'
            '<i><span>Some <span style="font-weight: bold;">tracker titles</span> require special '
            "formatting during upload. You can edit the title below, but any "
            '<span style="font-weight: bold;">required</span> formatting will be applied '
            "automatically.</span></i>",
            wordWrap=True,
            parent=self,
        )

        scroll = QScrollArea(self)
        scroll.setFrameShape(QFrame.Shape.Box)
        scroll.setFrameShadow(QFrame.Shadow.Sunken)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(0)

        self.title_edits = {}
        self.nfo_edits = {}

        for tracker, data in tracker_nfos.items():
            title = data.get("title")
            nfo = data.get("nfo")

            if not title and not nfo:
                continue

            label = QLabel(f'<span style="font-weight: bold;">{tracker}</span>', self)
            group_box = QGroupBox(self)
            group_layout = QVBoxLayout(group_box)
            group_layout.setSpacing(0)

            title = data.get("title")
            nfo = data.get("nfo")

            if title:
                title_label = QLabel("Tracker Title:", group_box)
                group_layout.addWidget(title_label)
                title_edit = QLineEdit(group_box)
                title_edit.setText(title)
                title_edit.setPlaceholderText("Release title")
                group_layout.addWidget(title_edit)
                self.title_edits[tracker] = title_edit

                if nfo:
                    group_layout.addSpacing(6)

            if nfo:
                nfo_label = QLabel("NFO:", group_box)
                nfo_edit = CodeEditor(
                    pop_out_expansion=True,
                    pop_out_name=f"NFO ({tracker})",
                    parent=group_box,
                )
                nfo_edit.setPlainText(data.get("nfo", ""))
                nfo_edit.setMinimumHeight(450)
                self.nfo_edits[tracker] = nfo_edit

                group_layout.addWidget(nfo_label)
                group_layout.addWidget(nfo_edit)

            inner_layout.addWidget(label)
            inner_layout.addWidget(group_box)
            inner_layout.addSpacing(6)

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

    def get_results(self) -> dict[TrackerSelection, dict[str | None, str]]:
        if self.result() == QDialog.DialogCode.Accepted:
            return {
                tracker: {
                    "title": self.title_edits[tracker].text(),
                    "nfo": self.nfo_edits[tracker].toPlainText(),
                }
                for tracker in self.title_edits
            }
        return self._original


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    app.setStyle("fusion")

    tracker_nfos = {
        TrackerSelection.MORE_THAN_TV: {"title": "SomeTitleA", "nfo": "Some Nfo A"},
        TrackerSelection.TORRENT_LEECH: {"title": "SomeTitleB", "nfo": "Some Nfo B"},
        TrackerSelection.PASS_THE_POPCORN: {"nfo": "Some Nfo B"},
        TrackerSelection.REELFLIX: {},
    }

    dialog = OverviewDialog(tracker_nfos)  # pyright: ignore[reportArgumentType]
    result = dialog.exec()
    if result == QDialog.DialogCode.Accepted:
        edited_nfos = dialog.get_results()
        print("Edited NFOs:", edited_nfos)
    else:
        print("Original NFOs:", tracker_nfos)
