"""What the user is told once the migration has run."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.backend.utils.file_utilities import open_explorer
from src.config.layout_apply import (
    CONFLICTS_DIR_NAME,
    SUMMARY_LOG_NAME,
    MigrationRun,
    render_summary,
)


class MigrationSummaryDialog(QDialog):
    """The only account of the migration the user gets, and the last of it.

    Nothing in here recurs on a later launch, so anything that needs a decision
    has to be in it, and it has to say that nothing will be rechecked. Otherwise
    a leftover folder waits forever for a prompt that is never coming.

    A copy is kept on disk, which this names so the user can find it again. The
    text itself is composed in `layout_apply`, so the window and that copy are
    the same account rather than two that can drift apart.
    """

    def __init__(self, run: MigrationRun, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._run = run
        saved = run.plan.state_root / "logs" / SUMMARY_LOG_NAME
        # Only named if it is really there. Keeping the copy is best effort, and
        # pointing at a file that could not be written would send the user
        # looking for something that does not exist.
        self._saved_to = saved if saved.is_file() else None

        self.setWindowTitle("Migration complete")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Your settings and data have been moved to their own folder, "
                "outside the application. Replacing a release will not disturb "
                "them again.",
                wordWrap=True,
                parent=self,
            )
        )

        self.detail_view = QTextEdit(parent=self)
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlainText(self.summary_text())
        layout.addWidget(self.detail_view)

        button_box = QDialogButtonBox(parent=self)
        self.open_button = QPushButton("Open data folder", parent=self)
        self.conflicts_button = QPushButton("Open conflicts folder", parent=self)
        self.close_button = QPushButton("Close", parent=self)

        self.conflicts_button.setEnabled(bool(run.outcome.diverted))
        self.open_button.setAutoDefault(False)
        self.conflicts_button.setAutoDefault(False)
        self.close_button.setDefault(True)

        button_box.addButton(self.open_button, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.addButton(
            self.conflicts_button, QDialogButtonBox.ButtonRole.ActionRole
        )
        button_box.addButton(self.close_button, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(button_box)

        self.open_button.clicked.connect(
            lambda: open_explorer(self._run.plan.state_root)
        )
        self.conflicts_button.clicked.connect(
            lambda: open_explorer(self._run.plan.state_root / CONFLICTS_DIR_NAME)
        )
        self.close_button.clicked.connect(self.accept)

    def summary_text(self) -> str:
        """The same text that was saved, rendered by the same function."""
        return render_summary(self._run, saved_to=self._saved_to)
