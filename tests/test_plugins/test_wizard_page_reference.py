"""A plugin can name its wizard page by string, so it loads without Qt.

Registration checks the string's shape only. Importing the page would import
Qt, which is what the string exists to avoid.
"""

import pytest

from nfoforge.exceptions import PluginError
from nfoforge.plugins.api import PluginDefinition
from nfoforge.plugins.manager import PluginManager


def _definition(wizard_page: object) -> PluginDefinition:
    return PluginDefinition(
        display_name="Example",
        version="1.0.0",
        wizard_page=wizard_page,  # type: ignore[arg-type]
    )


def test_a_page_named_by_string_registers_without_being_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nfoforge.plugins.manager.resolve_wizard_page",
        lambda _page: pytest.fail("registration imported the wizard page"),
    )
    manager = PluginManager()

    manager.register("example", _definition("example_plugin.pages:InputPage"), "test")

    assert manager.get("example") is not None


@pytest.mark.parametrize(
    "reference",
    ["example_plugin.pages", "example_plugin.pages:", ":InputPage", "not a path:X"],
)
def test_a_malformed_reference_is_refused(reference: str) -> None:
    with pytest.raises(PluginError, match="package.module:ClassName"):
        PluginManager().register("example", _definition(reference), "test")
