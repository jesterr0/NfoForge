from collections.abc import Callable
from dataclasses import dataclass
from typing import Type

from src.plugins.plugin_wizard_base import BaseWizardPage


@dataclass(slots=True)
class PluginPayload:
    """
    Simple object to hold plugin packages.

    Field `name` is required, everything else should filled based on the plugin requirements.
    """

    name: str
    wizard: Type[BaseWizardPage] | None = None
    token_replacer: Callable[..., str | None] | bool | None = None
    pre_upload: Callable[..., bool] | bool | None = None
    jinja2_filters: dict[str, Callable[..., str]] | None = None
    jinja2_functions: dict[str, Callable[..., str]] | None = None
    flat_filters: dict[str, Callable[..., str]] | None = None
