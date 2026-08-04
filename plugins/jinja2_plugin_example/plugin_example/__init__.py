from src.plugins.api import PluginDefinition

from .example import ci_replace_filter, ci_replace_function

plugin = PluginDefinition(
    display_name="Jinja2 Example",
    version="1.0.0",
    jinja2_filters={"ci_replace_filter": ci_replace_filter},
    jinja2_functions={"ci_replace_function": ci_replace_function},
)
