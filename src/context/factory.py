from collections.abc import Mapping
from typing import TYPE_CHECKING

from src.context.processing_context import ProcessingContext
from src.nf_jinja2 import Jinja2TemplateEngine
from src.payloads.config import ConfigPayload

if TYPE_CHECKING:
    from src.plugins.plugin_payload import PluginPayload


_NEWLINE_SEQUENCES = {
    "\\n": "\n",
    "\\r": "\r",
    "\\r\\n": "\r\n",
}


def create_processing_context(
    config_payload: ConfigPayload,
    plugins: Mapping[str, "PluginPayload"],
) -> ProcessingContext:
    """Create an isolated processing context with a configured Jinja engine."""
    engine = Jinja2TemplateEngine(
        trim_blocks=config_payload.trim_blocks,
        lstrip_blocks=config_payload.lstrip_blocks,
        newline_sequence=_NEWLINE_SEQUENCES.get(
            config_payload.newline_sequence,
            config_payload.newline_sequence,
        ),
        keep_trailing_newline=config_payload.keep_trailing_newline,
    )

    for plugin in plugins.values():
        if plugin.jinja2_filters:
            for name, func in plugin.jinja2_filters.items():
                engine.add_filter(name, func)
        if plugin.jinja2_functions:
            for name, func in plugin.jinja2_functions.items():
                engine.add_global(name, func, False)

    return ProcessingContext(jinja_engine=engine)
