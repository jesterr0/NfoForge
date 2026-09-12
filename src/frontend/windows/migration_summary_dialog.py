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

from src.backend.utils.file_utilities import file_bytes_to_str, open_explorer
from src.config.layout_apply import CONFLICTS_DIR_NAME, MigrationOutcome
from src.config.layout_migration import FindingKind, MigrationPlan, render_plan


class MigrationSummaryDialog(QDialog):
    """The only account of the migration the user gets, and the last of it.

    Nothing in here recurs on a later launch, so anything that needs a decision
    has to be in it, and it has to say that nothing will be rechecked. Otherwise
    a leftover folder waits forever for a prompt that is never coming.
    """

    def __init__(
        self,
        plan: MigrationPlan,
        outcome: MigrationOutcome,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plan = plan
        self._outcome = outcome

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

        self.conflicts_button.setEnabled(bool(outcome.diverted))
        self.open_button.setAutoDefault(False)
        self.conflicts_button.setAutoDefault(False)
        self.close_button.setDefault(True)

        button_box.addButton(self.open_button, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.addButton(
            self.conflicts_button, QDialogButtonBox.ButtonRole.ActionRole
        )
        button_box.addButton(self.close_button, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(button_box)

        self.open_button.clicked.connect(lambda: open_explorer(self._plan.state_root))
        self.conflicts_button.clicked.connect(
            lambda: open_explorer(self._plan.state_root / CONFLICTS_DIR_NAME)
        )
        self.close_button.clicked.connect(self.accept)

    def summary_text(self) -> str:
        """Everything that happened, and everything still wanting attention.

        The moved, copied and reported entries come from the same renderer the
        plan uses, so what the user is told afterwards is the same description of
        the same actions -- not a second account that can disagree with the first.
        """
        sections = [f"Your settings and data are now in:\n  {self._plan.state_root}"]

        rendered = render_plan(self._plan)
        if rendered:
            sections.append(rendered)

        if self._outcome.rewritten:
            lines = ["Settings updated to their new locations:"]
            lines.extend(f"  {entry}" for entry in sorted(self._outcome.rewritten))
            sections.append("\n".join(lines))

        if self._outcome.diverted:
            lines = [
                "Something was already in the way, so these were put aside for "
                "you to look at rather than replacing what was there:"
            ]
            for diversion in self._outcome.diverted:
                lines.append(f"  {diversion.planned}")
                lines.append(f"    kept instead at {diversion.actual}")
            sections.append("\n".join(lines))

        sections.append(self._legacy_note())
        sections.append(
            "None of these locations will be checked again. Anything above that "
            "you want to deal with later is yours to come back to, and a previous "
            "installation can still be imported from Settings at any time."
        )
        return "\n\n".join(sections)

    def _legacy_note(self) -> str:
        """What to say about the folder the data came from.

        It is intact and deleting it is the user's call: they are the only one who
        can judge whether it holds anything else. A setting still pointing inside
        it gets its own warning, because that is the one consequence they cannot
        see coming -- it keeps working right up until they act on this advice, and
        then fails for reasons that look unrelated.
        """
        if self._plan.legacy_root is None:
            return (
                "Nothing was imported from a previous installation, so nothing "
                "outside this folder was read."
            )

        lines = [
            f"Your previous installation is still at:\n  {self._plan.legacy_root}",
            "Nothing was removed from it. Review it before deleting anything.",
        ]
        inside = [
            finding
            for finding in self._plan.findings
            if finding.kind is FindingKind.PATH_INSIDE_LEGACY_INSTALL
        ]
        if inside:
            lines.append(
                "Emptying that folder will break these settings, which still "
                "point inside it:"
            )
            for finding in inside:
                suffix = f" ({file_bytes_to_str(finding.size)})" if finding.size else ""
                lines.append(f"  {finding.detail}: {finding.path}{suffix}")
        return "\n".join(lines)
