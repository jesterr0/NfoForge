from PySide6.QtGui import Qt
from PySide6.QtWidgets import QDialog
from typing_extensions import override


class PluginPromptDialog(QDialog):
    """
    Base class for plugin prompt dialogs, ready to use with the helper function
    `ask_thread_safe_custom_prompt`.

    Usage:
        - Subclass this dialog to create your own custom prompt UI.
        - You must connect your dialog's "OK"/"Close" button to `self.accept`
          and your "Cancel" button to `self.reject`. This ensures the dialog
          closes correctly and your overridden logic is executed.
        - Override the `accept()` method in your subclass to gather user input
          and assign it to `self.results` before calling `super().accept()`.
          Example:

              def accept(self):
                  self.results = {...}  # Gather your results here
                  super().accept()

    Notes:
        - The dialog will be executed modally using `exec()`.
        - The `self.results` attribute should contain the dialog's output
          after acceptance, or remain None if cancelled.
    """

    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setObjectName("multiPromptDialog")
        self.apply_top_parent_geometry()

        self.results = None

    def apply_top_parent_geometry(self) -> None:
        """Applies the top most parents geometry, override this and pass if you want to avoid this."""
        # import at runtime to prevent circular import issues
        from src.frontend.utils import set_top_parent_geometry

        set_top_parent_geometry(self)

    @override
    def accept(self):
        """
        Subclasses should override this method to fill `self.results`
        with the dialog's output before calling `super().accept()`.
        """
        super().accept()
