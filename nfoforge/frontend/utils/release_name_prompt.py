from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QWidget

from nfoforge.core.rename.name_checks import (
    blocking_issues,
    release_name_issues,
    warning_issues,
)

if TYPE_CHECKING:
    from nfoforge.config.config import ConfigManager
    from nfoforge.context.processing_context import ProcessingContext


def confirm_release_names(
    parent: QWidget,
    config: ConfigManager,
    context: ProcessingContext,
    names: Iterable[str],
) -> bool:
    """Apply the plugins' name rules; whether the rename may go ahead.

    A rule that blocks is shown and the page stays put, so the name can be
    changed. Warnings are asked about together, once.
    """
    issues = release_name_issues(config, context, names)
    blocked = blocking_issues(issues)
    if blocked:
        QMessageBox.warning(parent, "Release Name Not Allowed", "\n\n".join(blocked))
        return False
    warned = warning_issues(issues)
    if not warned:
        return True
    return (
        QMessageBox.warning(
            parent,
            "Release Name Warning",
            "\n\n".join(warned) + "\n\nContinue with this name?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        == QMessageBox.StandardButton.Ok
    )
