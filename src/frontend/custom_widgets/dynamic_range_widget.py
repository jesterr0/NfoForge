from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DynamicRangeWidget(QWidget):
    state_changed = Signal(object)

    def __init__(self, debounce_interval: int = 150, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dynamicRangeWidget")
        self._last_state: dict | None = None
        self._debounce_timer = QTimer(self, singleShot=True, interval=debounce_interval)
        self._debounce_timer.timeout.connect(self._emit_state_if_changed)

        # resolution
        res_group = QGroupBox("Active in resolution:")
        res_layout = QHBoxLayout()
        self.res_checkboxes = {}
        for res in ["720p", "1080p", "2160p"]:
            cb = QCheckBox(res, self)
            self.res_checkboxes[res] = cb
            res_layout.addWidget(cb)
            cb.stateChanged.connect(self._on_state_change)
        res_group.setLayout(res_layout)

        # HDR types
        hdr_group = QGroupBox("HDR Types Returned:")
        hdr_layout_v = QVBoxLayout()
        self.hdr_checkboxes = {}
        hdr_types = [
            "SDR",
            "PQ",
            "HLG",
            "HDR10",
            "HDR10+",
            "DV",
            "DV HDR10",
            "DV HDR10+",
        ]
        # split into two rows
        for i in range(0, len(hdr_types), 4):
            row_layout = QHBoxLayout()
            for hdr in hdr_types[i : i + 4]:
                cb = QCheckBox(hdr, self)
                self.hdr_checkboxes[hdr] = cb
                row_layout.addWidget(cb)
                cb.stateChanged.connect(self._on_state_change)
            hdr_layout_v.addLayout(row_layout)
        hdr_group.setLayout(hdr_layout_v)

        # custom Dynamic Range Strings
        custom_group = QGroupBox("Custom Dynamic Range Strings:")
        custom_layout = QFormLayout()
        self.custom_edits = {}
        for hdr in hdr_types:
            edit = QLineEdit(self)
            self.custom_edits[hdr] = edit
            custom_layout.addRow(hdr, edit)
            edit.editingFinished.connect(self._on_state_change)
        custom_group.setLayout(custom_layout)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(res_group)
        self.main_layout.addWidget(hdr_group)
        self.main_layout.addWidget(custom_group)
        self.main_layout.addStretch()

    def to_dict(self) -> dict:
        """Example output:
        ```python
        {'resolutions': {'720p': False, '1080p': False, '2160p': False},
        'hdr_types': {'SDR': False, 'PQ': False, 'HLG': False, 'HDR10': False,
        'HDR10+': False, 'DV': False, 'DV HDR10': False, 'DV HDR10+': False},
        'custom_strings': {'SDR': '', 'PQ': '', 'HLG': '', 'HDR10': '', 'HDR10+': '',
        'DV': '', 'DV HDR10': '', 'DV HDR10+': ''}}
        ```"""
        return {
            "resolutions": {k: cb.isChecked() for k, cb in self.res_checkboxes.items()},
            "hdr_types": {k: cb.isChecked() for k, cb in self.hdr_checkboxes.items()},
            "custom_strings": {
                k: edit.text().strip() for k, edit in self.custom_edits.items()
            },
        }

    def from_dict(self, settings: dict) -> None:
        """Expected input:
        ```python
        {'resolutions': {'720p': False, '1080p': False, '2160p': False},
        'hdr_types': {'SDR': False, 'PQ': False, 'HLG': False, 'HDR10': False,
        'HDR10+': False, 'DV': False, 'DV HDR10': False, 'DV HDR10+': False},
        'custom_strings': {'SDR': '', 'PQ': '', 'HLG': '', 'HDR10': '', 'HDR10+': '',
        'DV': '', 'DV HDR10': '', 'DV HDR10+': ''}}
        ```"""
        self.blockSignals(True)
        for k, v in settings.get("resolutions", {}).items():
            if k in self.res_checkboxes:
                self.res_checkboxes[k].setChecked(v)
        for k, v in settings.get("hdr_types", {}).items():
            if k in self.hdr_checkboxes:
                self.hdr_checkboxes[k].setChecked(v)
        for k, v in settings.get("custom_strings", {}).items():
            if k in self.custom_edits:
                self.custom_edits[k].setText(v)
        self._last_state = self.to_dict()
        self.blockSignals(False)

    @Slot()
    def _on_state_change(self, *_) -> None:
        self._debounce_timer.start()

    def _emit_state_if_changed(self):
        new_state = self.to_dict()
        if new_state != self._last_state:
            self._last_state = new_state
            self.state_changed.emit(new_state)


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QPushButton

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = QWidget()
    layout = QVBoxLayout(window)
    dr_widget = DynamicRangeWidget()
    layout.addWidget(dr_widget)
    btn = QPushButton("Print Settings")
    layout.addWidget(btn)

    def print_settings():
        print(dr_widget.to_dict())

    btn.clicked.connect(print_settings)

    window.setWindowTitle("Dynamic Range Widget Demo")
    window.resize(500, 600)
    window.show()
    sys.exit(app.exec())
