from collections.abc import Mapping
from typing import Any

from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.plugins.metadata_provider import MetadataMediaKind, MetadataProviderResult

# This is deliberately local and deterministic. Replace this dictionary with
# an authenticated API client in a real metadata-provider plugin.
EXAMPLE_METADATA: dict[str, MetadataProviderResult] = {
    "tt1254207": MetadataProviderResult(
        original_title="Big Buck Bunny",
        localized_title="Big Buck Bunny",
        year=2008,
        plot="A curious rabbit spends a sunny day dealing with three bullies.",
        genres=("Animation", "Comedy"),
        media_kind=MetadataMediaKind.MOVIE,
    ),
    "tt0111161": MetadataProviderResult(
        original_title="The Shawshank Redemption The chef",
        localized_title="The Shawshank Redemption The chef 2",
        year=1994,
        plot="Two imprisoned men find hope and friendship over the years.",
        genres=("Drama",),
        media_kind=MetadataMediaKind.MOVIE,
    ),
    "tt0944947": MetadataProviderResult(
        original_title="Game of Thrones",
        localized_title="Game of Thrones",
        year=2011,
        plot="Several noble families fight for control of the Iron Throne.",
        genres=("Drama", "Fantasy"),
        media_kind=MetadataMediaKind.MINI_SERIES,
    ),
}


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
    """Return deterministic metadata for known IDs and TMDb fallback otherwise.

    The extra arguments demonstrate the complete provider contract. A real
    plugin can use ``config`` for credentials/settings, ``context`` for the
    current processing state, ``tmdb_data`` as a fallback/request hint, and
    ``timeout`` for its HTTP client. This example intentionally performs no
    network requests. Return only the fields that should override TMDb; NfoForge
    merges the result into its canonical media-search payload.
    """

    # you'd use the args above to determine what you need to lookup on your own API
    # to update NFOForge's internal payload for the rest of the program

    return EXAMPLE_METADATA.get(imdb_id.strip().lower())
