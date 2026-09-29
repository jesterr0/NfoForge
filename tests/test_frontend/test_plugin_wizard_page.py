"""The desktop app turns a plugin's wizard page reference into its class."""

import pytest

from nfoforge.exceptions import PluginError
from nfoforge.frontend.wizards.media_input import MediaInput
from nfoforge.plugins.manager import resolve_wizard_page


def test_a_reference_resolves_to_the_page_class() -> None:
    page = resolve_wizard_page("nfoforge.frontend.wizards.media_input:MediaInput")

    assert page is MediaInput


def test_a_class_is_taken_as_it_is() -> None:
    assert resolve_wizard_page(MediaInput) is MediaInput


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("no_such_plugin.pages:InputPage", "cannot be loaded"),
        ("nfoforge.frontend.wizards.media_input:NoSuchPage", "cannot be loaded"),
        ("nfoforge.plugins.api:PluginDefinition", "BaseWizardPage subclass"),
    ],
)
def test_a_reference_that_is_not_a_page_is_refused(
    reference: str, message: str
) -> None:
    with pytest.raises(PluginError, match=message):
        resolve_wizard_page(reference)
