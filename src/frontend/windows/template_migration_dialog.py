"""Ask the user before rewriting their own NFO template files."""

import traceback

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
from src.logger.nfo_forge_logger import LOG


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
                "renamed or removed in this version. Until they are updated, "
                "those fields render as blank in generated NFOs.",
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
                "Templates with renamed tokens are rewritten, with a "
                "timestamped backup kept alongside the original. Templates "
                "that only reference removed tokens have no automatic "
                "replacement and are left untouched for you to edit by hand.",
                wordWrap=True,
                parent=self,
            )
        )

        self.suppress_checkbox = QCheckBox("Don't ask me again", parent=self)
        layout.addWidget(self.suppress_checkbox)

        button_box = QDialogButtonBox(parent=self)
        self.update_button = QPushButton("Update", parent=self)
        self.not_now_button = QPushButton("Not now", parent=self)
        self.diff_button = QPushButton("Show diff", parent=self)

        # "Not now" -- not "Update" -- is the keyboard-Enter default. The
        # dialog opens with focus in the read-only summary box, which does
        # not itself consume Return, so Qt's dialog-level auto-default
        # promotion would otherwise hand a reflexive Enter (the natural
        # reaction to an unexpected dialog while still reading it) to
        # whichever button was added first -- the destructive one. The
        # non-destructive action must own the keyboard default.
        self.update_button.setAutoDefault(False)
        self.diff_button.setAutoDefault(False)
        self.not_now_button.setDefault(True)

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
        self.accept()

    def _on_not_now(self) -> None:
        self.migrate_requested = False
        self.reject()

    def done(self, result: int) -> None:
        """Capture "Don't ask me again" no matter how the dialog closes.

        `_on_update`/`_on_not_now` only run for the Update/Not now buttons.
        Esc and the window's close button both call `QDialog.reject()`
        directly, bypassing those handlers, so the checkbox is read once
        here -- the one path every way of closing the dialog goes through --
        instead of duplicating the read in each handler.
        """
        self.suppress_future_prompts = self.suppress_checkbox.isChecked()
        super().done(result)

    def _on_show_diff(self) -> None:
        """Swap the summary for a unified diff of every affected file.

        This slot runs inside the nested event loop `QDialog.exec()` starts,
        so an exception here would not reach a `try`/`except` wrapped around
        `exec()` in the caller -- it never crosses back into that Python
        frame the normal way. Caught and logged locally instead, falling
        back to the plain summary, so a bad diff can degrade the dialog
        without taking startup down with it.
        """
        try:
            diffs: list[str] = []
            for report in self._reports:
                try:
                    with report.path.open(
                        encoding="utf-8", newline=""
                    ) as template_file:
                        original = template_file.read()
                except (OSError, UnicodeDecodeError) as error:
                    LOG.warning(
                        LOG.LOG_SOURCE.FE,
                        f"Skipping unreadable template {report.path}: {error}",
                    )
                    continue
                diff = build_diff(
                    report.path, original, rewrite_template_text(original)
                )
                if diff:
                    diffs.append(diff)
            self.summary_view.setPlainText(
                "\n".join(diffs) if diffs else "No textual changes to show."
            )
            self.diff_button.setEnabled(False)
        except Exception:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                f"Failed to build template migration diff: {traceback.format_exc()}",
            )
            self.summary_view.setPlainText(self.summary_text())
