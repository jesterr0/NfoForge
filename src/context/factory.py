from src.config.models import AppConfig
from src.context.processing_context import ProcessingContext
from src.nf_jinja2 import Jinja2TemplateEngine
from src.plugins.manager import PluginManager


def create_processing_context(
    config: AppConfig,
    plugin_manager: PluginManager,
) -> ProcessingContext:
    """Create an isolated processing context with a configured Jinja engine."""
    engine = Jinja2TemplateEngine(
        trim_blocks=config.templates.trim_blocks,
        lstrip_blocks=config.templates.lstrip_blocks,
        newline_sequence=config.templates.newline_sequence,
        keep_trailing_newline=config.templates.keep_trailing_newline,
    )

    for name, func in plugin_manager.jinja2_filters(
        enabled=config.general.enable_plugins
    ).items():
        engine.add_filter(name, func)
    for name, func in plugin_manager.jinja2_functions(
        enabled=config.general.enable_plugins
    ).items():
        engine.add_global(name, func, False)

    return ProcessingContext(jinja_engine=engine)
