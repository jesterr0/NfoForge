"""Ask the user before rewriting their own NFO template files."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.backend.utils.template_token_migration import (
    TemplateTokenReport,
    build_diff,
    rewrite_template_text,
)


class TemplateMigrationDialog(QDialog):
    """Consent gate for the renamed-token template migration.

    These are files the user wrote, so the migration is opt-in per launch. The
    suppression checkbox exists so someone who deliberately keeps old names --
    templates shared with an older install, for example -- is not nagged.
    """

    def __init__(
        self,
        reports: list[TemplateTokenReport],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._reports = reports
        self.migrate_requested = False
        self.suppress_future_prompts = False

        self.setWindowTitle("Templates use renamed tokens")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"{len(reports)} of your templates reference tokens that were "
                "renamed in this version. Until they are updated, those fields "
                "render as blank in generated NFOs.",
                wordWrap=True,
                parent=self,
            )
        )

        self.summary_view = QTextEdit(parent=self)
        self.summary_view.setReadOnly(True)
        self.summary_view.setPlainText(self.summary_text())
        layout.addWidget(self.summary_view)

        layout.addWidget(
            QLabel(
                "A timestamped backup of each file is kept alongside it.",
                parent=self,
            )
        )

        self.suppress_checkbox = QCheckBox("Don't ask me again", parent=self)
        layout.addWidget(self.suppress_checkbox)

        button_box = QDialogButtonBox(parent=self)
        self.update_button = QPushButton("Update", parent=self)
        self.not_now_button = QPushButton("Not now", parent=self)
        self.diff_button = QPushButton("Show diff", parent=self)
        button_box.addButton(self.update_button, QDialogButtonBox.ButtonRole.AcceptRole)
        button_box.addButton(
            self.not_now_button, QDialogButtonBox.ButtonRole.RejectRole
        )
        button_box.addButton(self.diff_button, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(button_box)

        self.update_button.clicked.connect(self._on_update)
        self.not_now_button.clicked.connect(self._on_not_now)
        self.diff_button.clicked.connect(self._on_show_diff)

    def summary_text(self) -> str:
        """Human-readable list of what would change, per file."""
        lines: list[str] = []
        for report in self._reports:
            lines.append(report.path.name)
            for old_name, new_name in sorted(report.renamed.items()):
                lines.append(f"    {old_name}  ->  {new_name}")
            for removed_name in sorted(report.removed):
                lines.append(
                    f"    {removed_name}  ->  no replacement, edit this one by hand"
                )
            lines.append("")
        return "\n".join(lines).rstrip()

    def _on_update(self) -> None:
        self.migrate_requested = True
        self.suppress_future_prompts = self.suppress_checkbox.isChecked()
        self.accept()

    def _on_not_now(self) -> None:
        self.migrate_requested = False
        self.suppress_future_prompts = self.suppress_checkbox.isChecked()
        self.reject()

    def _on_show_diff(self) -> None:
        """Swap the summary for a unified diff of every affected file."""
        diffs: list[str] = []
        for report in self._reports:
            try:
                with report.path.open(encoding="utf-8", newline="") as template_file:
                    original = template_file.read()
            except (OSError, UnicodeDecodeError):
                continue
            diff = build_diff(report.path, original, rewrite_template_text(original))
            if diff:
                diffs.append(diff)
        self.summary_view.setPlainText(
            "\n".join(diffs) if diffs else "No textual changes to show."
        )
        self.diff_button.setEnabled(False)
