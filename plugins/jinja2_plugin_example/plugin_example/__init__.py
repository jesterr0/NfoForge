from .example import ci_replace_filter, ci_replace_function

from src.plugins.plugin_payload import PluginPayload

plugin_payload = PluginPayload(
    name="Jinja2Example",
    jinja2_filters={"ci_replace_filter": ci_replace_filter},
    jinja2_functions={"ci_replace_function": ci_replace_function},
)
