"""Hide the stray back arrow Qt 6.12 draws on every `QWizard`.

Qt creates the Aero-style back arrow (a bare 32x32 `QAbstractButton`) for
every wizard and leaves it visible in the top-left corner whatever the wizard
style, on every platform. NfoForge's wizards use `ModernStyle` and have no back
navigation, so the arrow is never wanted. It is found as the one button that is
not one of the wizard's own, and kept hidden.
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractButton, QWizard

_B = QWizard.WizardButton
_WIZARD_BUTTONS = (
    _B.BackButton,
    _B.NextButton,
    _B.CommitButton,
    _B.FinishButton,
    _B.CancelButton,
    _B.HelpButton,
    _B.CustomButton1,
    _B.CustomButton2,
    _B.CustomButton3,
)


class _KeepHidden(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(watched, QAbstractButton):
            watched.hide()
        return False


def hide_stray_back_arrow(wizard: QWizard) -> None:
    """Hide (and keep hidden) every button the wizard did not declare."""
    own = {wizard.button(button) for button in _WIZARD_BUTTONS}
    keep_hidden = _KeepHidden(wizard)
    # direct children only: a page's own buttons are not stray
    for button in wizard.findChildren(
        QAbstractButton, options=Qt.FindChildOption.FindDirectChildrenOnly
    ):
        if button in own:
            continue
        button.hide()
        button.installEventFilter(keep_hidden)
