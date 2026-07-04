from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.plugins.plugin_payload import PluginPayload


@dataclass(slots=True)
class PluginRegistry:
    plugins: dict[str, "PluginPayload"] = field(default_factory=dict)
    flat_filters: dict[str, Callable[..., str]] = field(default_factory=dict)
