from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MetadataMediaKind(Enum):
    """Normalized media kinds an external metadata provider may report."""

    MOVIE = "movie"
    TV_MOVIE = "tv_movie"
    SHORT = "short"
    MINI_SERIES = "mini_series"
    STAND_UP_COMEDY = "stand_up_comedy"
    LIVE_PERFORMANCE = "live_performance"


@dataclass(frozen=True, slots=True)
class MetadataProviderResult:
    """Optional metadata supplied by an external catalog provider.

    Every field is optional. NfoForge overlays populated values on top of its
    TMDb metadata, so a provider only needs to return data it can supply
    reliably.
    """

    original_title: str | None = None
    localized_title: str | None = None
    year: int | None = None
    plot: str | None = None
    poster_url: str | None = None
    genres: tuple[str, ...] = ()
    media_kind: MetadataMediaKind | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "original_title",
            "localized_title",
            "plot",
            "poster_url",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"'{field_name}' must be a string or None")
            if isinstance(value, str):
                object.__setattr__(self, field_name, value.strip() or None)

        if self.year is not None and (
            not isinstance(self.year, int) or isinstance(self.year, bool)
        ):
            raise TypeError("'year' must be an integer or None")

        if not isinstance(self.genres, tuple) or not all(
            isinstance(genre, str) for genre in self.genres
        ):
            raise TypeError("'genres' must be a tuple of strings")
        object.__setattr__(
            self,
            "genres",
            tuple(genre.strip() for genre in self.genres if genre.strip()),
        )

        if self.media_kind is not None and not isinstance(
            self.media_kind, MetadataMediaKind
        ):
            raise TypeError("'media_kind' must be a MetadataMediaKind or None")
