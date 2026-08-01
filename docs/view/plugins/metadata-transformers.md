# Metadata Transformer Plugins

NfoForge builds its canonical media-search payload from TMDB and its normal
TVDB/AniList enrichment before invoking an optional metadata transformer. The
transformer receives an isolated copy, may change any payload field, and must
return that payload for its changes to be accepted. Returning `None` keeps the
TMDB result unchanged.

A failure or invalid return is non-blocking: NfoForge warns the user, discards
the isolated copy, and continues with canonical metadata.

## Contract

```python
from src.plugins.api import (
    MetadataMediaKind,
    MetadataTransformRequest,
    PluginDefinition,
)
from src.payloads.media_search import MediaSearchPayload


def transform_metadata(
    request: MetadataTransformRequest,
) -> MediaSearchPayload | None:
    imdb_id = request.payload.imdb_id
    api_result = fetch_from_your_api(imdb_id, timeout=request.timeout)
    if not api_result:
        return None

    request.payload.title = api_result.get("localized_title")
    request.payload.original_title = api_result.get("original_title")
    request.payload.year = api_result.get("year")
    request.payload.plot = api_result.get("plot")
    request.payload.poster_url = api_result.get("poster_url")
    request.payload.genre_names = tuple(api_result.get("genres", ()))
    request.payload.media_kind = MetadataMediaKind.MOVIE
    request.payload.plugin_data["example.my-metadata"] = api_result
    return request.payload


plugin = PluginDefinition(
    display_name="My Metadata Transformer",
    version="1.0.0",
    metadata_transformer=transform_metadata,
)
```

The request also exposes `config` and `context` for integrations that need
read-only application state. Only the isolated `request.payload` should be
mutated. `plugin_data` is available for namespaced diagnostic or downstream
data that does not belong in a canonical field.

After installing the plugin, enable external plugins and select it under
**Settings -> Plugins -> Metadata Transformer**. The built-in TMDB selection
disables external transformation.

The deterministic example at
`plugins/metadata_plugin_example/plugin_metadata` uses an in-memory dictionary
and includes records for `tt1254207`, `tt0111161`, and `tt0944947`.

## Original title tokens

`{original_title}` uses the transformed original title and then TMDB's original
title. `{original_title_fallback_title}` and
`{original_title_fallback_title_clean}` additionally fall back to the selected
title.
