from dataclasses import dataclass, field
from typing import Any

from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.plugins.metadata_provider import MetadataMediaKind, MetadataProviderResult


@dataclass(slots=True)
class MediaSearchPayload:
    media_type: MediaType | None = None
    imdb_id: str | None = None
    provider_metadata: MetadataProviderResult | None = None
    tmdb_id: str | None = None
    tmdb_data: dict[str, Any] | None = None
    tvdb_id: str | None = None
    tvdb_data: dict[str, Any] | None = None
    anilist_id: str | None = None
    anilist_data: dict[str, Any] | None = None
    mal_id: str | None = None
    title: str | None = None
    year: int | None = None
    original_title: str | None = None
    genres: list[TMDBGenreIDsMovies | TMDBGenreIDsSeries] = field(default_factory=list)
    plot: str | None = None
    poster_url: str | None = None
    genre_names: tuple[str, ...] = ()
    media_kind: MetadataMediaKind | None = None

    def merge_metadata(
        self, provider_metadata: MetadataProviderResult | None = None
    ) -> None:
        """Build canonical metadata from TMDb, then apply provider overrides.

        Routing-sensitive values such as IDs, media type, TMDb genre enums,
        and TVDB episode data are intentionally not provider-controlled.
        """

        tmdb_data = self.tmdb_data or {}

        self.title = self._first_string(
            tmdb_data.get("title"), tmdb_data.get("name"), self.title
        )
        self.original_title = self._first_string(
            tmdb_data.get("original_title"),
            tmdb_data.get("original_name"),
            self.original_title,
        )
        self.year = self._tmdb_year(tmdb_data) or self.year
        self.plot = self._first_string(tmdb_data.get("overview"))
        self.poster_url = self._tmdb_poster_url(tmdb_data)
        self.genre_names = self._tmdb_genre_names(tmdb_data)
        self.media_kind = None
        self.provider_metadata = provider_metadata

        if provider_metadata is None:
            return
        if provider_metadata.localized_title:
            self.title = provider_metadata.localized_title
        if provider_metadata.original_title:
            self.original_title = provider_metadata.original_title
        if provider_metadata.year is not None:
            self.year = provider_metadata.year
        if provider_metadata.plot:
            self.plot = provider_metadata.plot
        if provider_metadata.poster_url:
            self.poster_url = provider_metadata.poster_url
        if provider_metadata.genres:
            self.genre_names = provider_metadata.genres
        if provider_metadata.media_kind is not None:
            self.media_kind = provider_metadata.media_kind

    @staticmethod
    def _first_string(*values: object) -> str | None:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _tmdb_year(tmdb_data: dict[str, Any]) -> int | None:
        date = tmdb_data.get("release_date") or tmdb_data.get("first_air_date")
        if isinstance(date, str):
            year = date.split("-", maxsplit=1)[0]
            return int(year) if year.isdigit() else None
        return None

    @staticmethod
    def _tmdb_poster_url(tmdb_data: dict[str, Any]) -> str | None:
        poster_path = tmdb_data.get("poster_path")
        if not isinstance(poster_path, str) or not poster_path.strip():
            return None
        poster_path = poster_path.strip()
        if poster_path.startswith(("http://", "https://")):
            return poster_path
        return f"https://image.tmdb.org/t/p/original/{poster_path.lstrip('/')}"

    def _tmdb_genre_names(self, tmdb_data: dict[str, Any]) -> tuple[str, ...]:
        raw_genres = tmdb_data.get("genres")
        if isinstance(raw_genres, list):
            names = tuple(
                name.strip()
                for genre in raw_genres
                if isinstance(genre, dict)
                and isinstance((name := genre.get("name")), str)
                and name.strip()
            )
            if names:
                return names
        return tuple(
            genre.name.replace("_", " ").title()
            for genre in self.genres
            if genre.name != "UNDEFINED"
        )

    def reset(self) -> None:
        self.media_type = None
        self.imdb_id = None
        self.provider_metadata = None
        self.tmdb_id = None
        self.tmdb_data = None
        self.tvdb_id = None
        self.tvdb_data = None
        self.anilist_id = None
        self.anilist_data = None
        self.mal_id = None
        self.title = None
        self.year = None
        self.original_title = None
        self.genres.clear()
        self.plot = None
        self.poster_url = None
        self.genre_names = ()
        self.media_kind = None
