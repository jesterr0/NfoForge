from src.plugins.api import PluginDefinition

from .example import transform_metadata

plugin = PluginDefinition(
    display_name="Metadata Transformer Example",
    version="1.0.0",
    description="Deterministic dictionary-backed metadata transformer.",
    metadata_transformer=transform_metadata,
)
