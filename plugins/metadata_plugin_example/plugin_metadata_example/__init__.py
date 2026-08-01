from src.plugins.plugin_payload import PluginPayload

from .example import metadata_provider

plugin_payload = PluginPayload(
    name="Metadata Provider Example",
    metadata_provider=metadata_provider,
)
