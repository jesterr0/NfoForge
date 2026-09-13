"""The one question a user is ever asked about the layout migration."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.config.layout_migration import LegacyInstall
from src.frontend.windows.legacy_import import choose_legacy_install

_WHAT_HAPPENS = (
    "Your settings, profiles, templates, tracker cookies, plugins and tools are "
    "copied across. The folder they come from is left exactly as it is, so "
    "nothing is lost either way, and you can import from it later in Settings."
)


class MigrationPromptDialog(QDialog):
    """Where to bring existing settings and data from, if anywhere.

    Asked once per machine, on the launch that migrates, and never again. That
    makes it worth more care than its size suggests: whatever it answers is what
    happens to the data, and there is no second chance to read it properly.

    One dialog with two states rather than two dialogs. The choices are the same
    either way -- use this folder, use a different one, or start fresh -- and only
    the opening sentence differs, so splitting them would duplicate the part that
    matters to keep identical.
    """

    def __init__(
        self, found: LegacyInstall | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._found = found
        self.chosen: LegacyInstall | None = None

        self.setWindowTitle("Bring your settings across")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.message_text(), wordWrap=True, parent=self))

        button_box = QDialogButtonBox(parent=self)
        self.migrate_button = QPushButton("Migrate", parent=self)
        self.choose_button = QPushButton("Choose a folder...", parent=self)
        self.fresh_button = QPushButton("Start fresh", parent=self)

        self.migrate_button.setEnabled(found is not None)

        # Migrating owns the keyboard default when there is something to migrate.
        # It is what nearly everyone wants, and it is not the destructive option:
        # the folder it reads is left untouched, so a reflexive Enter copies data
        # in rather than discarding any. With nothing found there is nothing to
        # default to but starting fresh.
        self.choose_button.setAutoDefault(False)
        if found is not None:
            self.fresh_button.setAutoDefault(False)
            self.migrate_button.setDefault(True)
        else:
            self.fresh_button.setDefault(True)

        button_box.addButton(
            self.migrate_button, QDialogButtonBox.ButtonRole.AcceptRole
        )
        button_box.addButton(self.choose_button, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.addButton(self.fresh_button, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(button_box)

        self.migrate_button.clicked.connect(self._on_migrate)
        self.choose_button.clicked.connect(self._on_choose)
        self.fresh_button.clicked.connect(self.reject)

    def message_text(self) -> str:
        """What the user reads, naming the folder when there is one.

        The path is the whole point of the found state: someone with more than
        one copy extracted needs to see which is about to be imported, and it is
        the only way to tell the application found the right thing.
        """
        if self._found is not None:
            return (
                f"A previous NfoForge installation was found at:\n\n"
                f"{self._found.root}\n\n"
                f"{_WHAT_HAPPENS}"
            )
        return (
            "NfoForge now keeps your settings and data in their own folder, "
            "outside the application, so replacing a release no longer disturbs "
            "them.\n\nNo previous installation was found automatically. You can "
            "point at the folder you used before, or start fresh.\n\n"
            f"{_WHAT_HAPPENS}"
        )

    def _on_migrate(self) -> None:
        self.chosen = self._found
        self.accept()

    def _on_choose(self) -> None:
        """Let the user name the folder, and accept only a real installation.

        Picking the wrong folder is easily done, so nothing found there leaves the
        dialog open. Closing on a bad choice would turn a mistake into a decision
        to start fresh.

        The picking and its complaint are shared with the Settings import rather
        than written twice, since getting the same wrong folder wrong in two
        different ways would be worse than either.
        """
        found = choose_legacy_install(self)
        if found is None:
            return

        self.chosen = found
        self.accept()
