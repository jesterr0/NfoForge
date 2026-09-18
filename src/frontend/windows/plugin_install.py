"""Installing a plugin from Settings, having said plainly what that means.

The work is in `src.plugins.install`, which is Qt-free. What is here is the
part that cannot be: choosing a folder or an archive, showing what was found,
and asking. The asking is the point. A plugin is Python that runs inside
NfoForge's process with everything NfoForge can reach, so an install button
that simply installed would be a worse experience than copying a folder by
hand -- the copy at least makes it obvious that something is being put
somewhere.

Nothing is imported or executed here. What the dialog shows comes from the
manifest alone, which is why it can name the plugin's id and module but not its
display name: reading that would mean importing the module, which is the thing
the user has not agreed to yet.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.config.paths import AppPaths
from src.frontend.utils import build_h_line, create_form_layout
from src.plugins.install import (
    PluginCandidate,
    PluginInstallError,
    extracted_archive,
    inspect_folder,
    install,
    resolve_conflict,
)

ARCHIVE_FILTER = "Plugin archive (*.zip)"


class PluginTrustDialog(QDialog):
    """What is about to be installed, and what installing it permits.

    Deliberately not a plain yes/no box. The warning is the same one the
    documentation gives, and it is repeated here because this is the one moment
    a user is choosing to run someone else's code and the documentation is not
    in front of them.
    """

    def __init__(
        self,
        candidate: PluginCandidate,
        source: Path,
        replaces: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.candidate = candidate
        self.replaces = replaces

        self.setWindowTitle("Update plugin" if replaces else "Install plugin")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "NfoForge found one plugin here. Check that it is the one you "
                "meant before installing it."
                if replaces is None
                else "A plugin with this id is already installed. Installing "
                "this one replaces it; the copy you have is moved aside, not "
                "deleted.",
                wordWrap=True,
                parent=self,
            )
        )
        layout.addLayout(
            create_form_layout(
                QLabel("Plugin id", parent=self),
                QLabel(candidate.plugin_id, parent=self),
            )
        )
        layout.addLayout(
            create_form_layout(
                QLabel("Module", parent=self),
                QLabel(candidate.module, parent=self),
            )
        )
        layout.addLayout(
            create_form_layout(
                QLabel("From", parent=self),
                QLabel(str(source), parent=self, wordWrap=True),
            )
        )
        if replaces is not None:
            layout.addLayout(
                create_form_layout(
                    QLabel("Replaces", parent=self),
                    QLabel(str(replaces), parent=self, wordWrap=True),
                )
            )
            # No old-versus-new version here: a plugin's version lives in the
            # `PluginDefinition` its module exports, and reading that would mean
            # importing the module -- which is exactly what this dialog is
            # asking permission for. The path is what can be shown honestly.
            layout.addWidget(
                QLabel(
                    "NfoForge cannot read either plugin's version without "
                    "running its code, so check the source you got this from.",
                    wordWrap=True,
                    parent=self,
                )
            )
        else:
            layout.addLayout(
                create_form_layout(
                    QLabel("Installs as", parent=self),
                    QLabel(candidate.directory_name, parent=self),
                )
            )
        layout.addWidget(build_h_line((6, 1, 6, 1)))
        layout.addWidget(
            QLabel(
                "A plugin is trusted Python code loaded into NfoForge itself. "
                "It can read and change anything NfoForge can, including your "
                "tracker credentials. Install only plugins whose source and "
                "author you trust.",
                wordWrap=True,
                parent=self,
            )
        )

        button_box = QDialogButtonBox(parent=self)
        self.install_button = QPushButton(
            "Update" if replaces else "Install", parent=self
        )
        self.cancel_button = QPushButton("Cancel", parent=self)
        # The safe answer is the default one. Nothing is lost by declining --
        # the folder or archive is still wherever it was.
        self.install_button.setAutoDefault(False)
        self.cancel_button.setDefault(True)
        button_box.addButton(
            self.install_button, QDialogButtonBox.ButtonRole.AcceptRole
        )
        button_box.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.install_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(button_box)


def install_from_folder(parent: QWidget, paths: AppPaths) -> Path | None:
    """Ask for a folder and install the plugin in it, or say why not."""
    chosen = QFileDialog.getExistingDirectory(parent, "Select the plugin's folder")
    if not chosen:
        return None
    return _run(parent, paths, Path(chosen), _folder_candidate(Path(chosen)))


def install_from_archive(parent: QWidget, paths: AppPaths) -> Path | None:
    """Ask for a `.zip` and install the plugin in it, or say why not."""
    chosen, _ = QFileDialog.getOpenFileName(
        parent, "Select a plugin archive", "", ARCHIVE_FILTER
    )
    if not chosen:
        return None
    return _run(parent, paths, Path(chosen), extracted_archive(Path(chosen)))


@contextmanager
def _folder_candidate(folder: Path) -> Iterator[PluginCandidate]:
    """A folder as a context manager, so both sources arrive the same way.

    An archive has to be unpacked somewhere temporary, and that tree must
    survive being shown to the user and then copied from, which makes it a
    context manager. A folder needs nothing of the sort, but giving it the same
    shape keeps `_run` from having to know which of the two it was handed.
    Inspection happens on entry either way, so a folder that is not a plugin
    raises in the same place an unreadable archive does.
    """
    yield inspect_folder(folder)


def _run(
    parent: QWidget,
    paths: AppPaths,
    source: Path,
    inspection: AbstractContextManager[PluginCandidate],
) -> Path | None:
    """Inspect, ask, install -- with the source kept alive throughout."""
    try:
        with inspection as candidate:
            # Resolved before asking, so a clash the user cannot act on is
            # reported instead of their being asked to trust something that
            # could not be loaded even if they said yes.
            replaces = resolve_conflict(candidate, paths)
            dialog = PluginTrustDialog(candidate, source, replaces, parent=parent)
            try:
                accepted = dialog.exec() == QDialog.DialogCode.Accepted
            finally:
                dialog.deleteLater()
            if not accepted:
                return None
            outcome = install(candidate, paths)
    except PluginInstallError as error:
        QMessageBox.critical(parent, "Install plugin", str(error))
        return None

    title = "Update plugin" if outcome.replaced else "Install plugin"
    verb = "updated at" if outcome.replaced else "installed to"
    kept = (
        f"\n\nThe copy it replaced was kept at:\n\n{outcome.replaced}"
        if outcome.replaced
        else ""
    )
    QMessageBox.information(
        parent,
        title,
        f"'{candidate.plugin_id}' was {verb}:\n\n{outcome.destination}{kept}\n\n"
        "NfoForge has to be restarted before it is loaded, and external "
        "plugins have to be enabled in Settings -> Plugins.",
    )
    return outcome.destination
