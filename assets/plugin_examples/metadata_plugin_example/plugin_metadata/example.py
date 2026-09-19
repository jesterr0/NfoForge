from typing import Any

from src.payloads.media_search import MediaSearchPayload
from src.plugins.api import (
    MetadataMediaKind,
    MetadataTransformRequest,
)

# This deterministic mapping stands in for an authenticated API response. A
# real plugin can fetch the same shape using request.timeout and its own client.
EXAMPLE_METADATA: dict[str, dict[str, Any]] = {
    "tt1254207": {
        "title": "Big Buck Bunny",
        "original_title": "Big Buck Bunny",
        "year": 2008,
        "plot": "A curious rabbit spends a sunny day dealing with three bullies.",
        "genre_names": ("Animation", "Comedy"),
        "media_kind": MetadataMediaKind.MOVIE,
    },
    "tt0111161": {
        "title": "The Shawshank Redemption",
        "original_title": "The Shawshank Redemption",
        "year": 1994,
        "plot": "Two imprisoned men find hope and friendship over the years.",
        "genre_names": ("Drama",),
        "media_kind": MetadataMediaKind.MOVIE,
    },
    "tt0944947": {
        "title": "Game of Thrones",
        "original_title": "Game of Thrones",
        "year": 2011,
        "plot": "Several noble families fight for control of the Iron Throne.",
        "genre_names": ("Drama", "Fantasy"),
        "media_kind": MetadataMediaKind.MINI_SERIES,
    },
}


def transform_metadata(
    request: MetadataTransformRequest,
) -> MediaSearchPayload | None:
    """Apply dictionary data to the isolated canonical media-search payload."""

    imdb_id = (request.payload.imdb_id or "").strip().lower()
    metadata = EXAMPLE_METADATA.get(imdb_id)
    if metadata is None:
        return None

    for field_name, value in metadata.items():
        setattr(request.payload, field_name, value)
    request.payload.plugin_data["example.metadata"] = {"matched_imdb_id": imdb_id}
    return request.payload
