# Metadata Provider Plugins

NfoForge uses TMDB as its primary metadata source and does not scrape IMDb.
An optional metadata-provider plugin can supply selected fields from an API or
catalog the user is authorized to access. NfoForge first builds canonical
metadata from TMDB and then overlays every populated provider field. Missing
provider fields retain their TMDB values.

A provider failure is non-blocking. NfoForge displays a warning and continues
with TMDB metadata. The plugin should therefore return `None` when it has
nothing useful to add and raise a descriptive exception only when the request
actually failed.

Return changes through `MetadataProviderResult` instead of mutating
`context.media_search` directly. The provider runs before the canonical merge,
and direct mutations may be replaced when NfoForge finalizes the payload.

## Contract

Expose a `PluginPayload` from the plugin package's `__init__.py`. The provider
is called in a worker thread and must accept the following keyword-only
arguments plus `**kwargs` for forward compatibility:

```python
from collections.abc import Mapping
from typing import Any

from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.plugins.metadata_provider import (
    MetadataMediaKind,
    MetadataProviderResult,
)
from src.plugins.plugin_payload import PluginPayload


def metadata_provider(
    *,
    config: ConfigManager,
    context: ProcessingContext,
    imdb_id: str,
    tmdb_data: Mapping[str, Any],
    media_type: MediaType,
    timeout: int,
    **kwargs: object,
) -> MetadataProviderResult | None:
    # Replace this with an authenticated API request using `imdb_id` and
    # honoring `timeout`.
    api_result = fetch_from_your_api(imdb_id, timeout=timeout)
    if not api_result:
        return None

    return MetadataProviderResult(
        original_title=api_result.get("original_title"),
        localized_title=api_result.get("localized_title"),
        year=api_result.get("year"),
        plot=api_result.get("plot"),
        poster_url=api_result.get("poster_url"),
        genres=tuple(api_result.get("genres", ())),
        media_kind=MetadataMediaKind.MOVIE,
    )


plugin_payload = PluginPayload(
    name="My Metadata Provider",
    metadata_provider=metadata_provider,
)
```

Every result field is optional. `genres` must be a tuple of strings, and
`media_kind` must be a `MetadataMediaKind` member. The supported kinds are
`MOVIE`, `TV_MOVIE`, `SHORT`, `MINI_SERIES`, `STAND_UP_COMEDY`, and
`LIVE_PERFORMANCE`.

The merged values are exposed through `MediaSearchPayload.title`,
`original_title`, `year`, `plot`, `poster_url`, `genre_names`, and
`media_kind`. Raw `tmdb_data` and `provider_metadata` remain available for
diagnostics and advanced integrations. IDs, `media_type`, TMDB genre enums,
and TVDB episode data remain application-controlled because they determine
routing and series mapping.

After installing the plugin, enable plugins and select it under
**Settings -> General -> Metadata Provider**. Selecting the built-in TMDB
entry disables external enrichment.

## Included Deterministic Example

The repository includes
`plugins/metadata_plugin_example/plugin_metadata_example`, which performs no
network requests and looks up results from an in-memory dictionary. Enable
**Metadata Provider Example** to exercise the provider path safely. The sample
records include `tt1254207` (Big Buck Bunny), `tt0111161` (The Shawshank
Redemption), and `tt0944947` (Game of Thrones); unknown IDs return `None` and
therefore use TMDB fallback metadata.

## Original Title Tokens

`{original_title}` resolves from the provider's original title first and then
falls back to TMDB's original title. The
`{original_title_fallback_title}` and
`{original_title_fallback_title_clean}` variants additionally fall back to the
selected TMDB title when no original title is available.
