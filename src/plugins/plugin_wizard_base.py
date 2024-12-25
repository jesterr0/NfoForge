from typing import TYPE_CHECKING

from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class WizardPluginBase(BaseWizardPage):
    """Base class for all wizard plugins"""

    def __init__(self, config, parent: "MainWindow"):
        """Initialize the plugin with a config and a parent widget."""
        super().__init__(config, parent)

    # TODO: add requirements later as needed

    # def get_title(self) -> str:
    #     """Return the title of the wizard page."""
    #     raise NotImplementedError("Plugin must implement 'get_title' method")

    # def setup_ui(self):
    #     """Setup UI components for the plugin."""
    #     raise NotImplementedError("Plugin must implement 'setup_ui' method")

    # def validate_page(self) -> bool:
    #     """Validate the wizard page."""
    #     raise NotImplementedError("Plugin must implement 'validate_page' method")
