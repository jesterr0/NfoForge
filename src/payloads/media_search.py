from copy import deepcopy
from dataclasses import dataclass, field, fields
from typing import Any

from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.plugins.api import MetadataMediaKind


@dataclass(slots=True)
class MediaSearchPayload:
    media_type: MediaType | None = None
    imdb_id: str | None = None
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
    plugin_data: dict[str, Any] = field(default_factory=dict)

    def populate_from_tmdb(self) -> None:
        """Populate canonical metadata before an optional plugin transformation."""

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

    def validate(self) -> None:
        """Validate fields plugins can alter before accepting transformed data."""

        string_fields = (
            "imdb_id",
            "tmdb_id",
            "tvdb_id",
            "anilist_id",
            "mal_id",
            "title",
            "original_title",
            "plot",
            "poster_url",
        )
        for field_name in string_fields:
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"MediaSearchPayload.{field_name} must be str or None")
        if self.year is not None and (
            not isinstance(self.year, int) or isinstance(self.year, bool)
        ):
            raise TypeError("MediaSearchPayload.year must be int or None")
        if self.media_type is not None and not isinstance(self.media_type, MediaType):
            raise TypeError("MediaSearchPayload.media_type must be MediaType or None")
        if self.media_kind is not None and not isinstance(
            self.media_kind, MetadataMediaKind
        ):
            raise TypeError(
                "MediaSearchPayload.media_kind must be MetadataMediaKind or None"
            )
        if not isinstance(self.genre_names, tuple) or not all(
            isinstance(name, str) for name in self.genre_names
        ):
            raise TypeError("MediaSearchPayload.genre_names must be tuple[str, ...]")
        if not isinstance(self.plugin_data, dict):
            raise TypeError("MediaSearchPayload.plugin_data must be a dictionary")

    def apply_lookup_results(self, media_data: dict[str, Any] | None) -> None:
        """Apply non-UI metadata lookup results to this payload."""

        if not media_data:
            return
        tmdb_result = media_data.get("tmdb_complete_data")
        if isinstance(tmdb_result, dict) and tmdb_result.get("success") is True:
            raw_tmdb = tmdb_result.get("result")
            if isinstance(raw_tmdb, dict):
                self.tmdb_data = raw_tmdb

        resolved_ids = media_data.get("resolved_ids")
        if isinstance(resolved_ids, dict) and resolved_ids.get("success") is True:
            raw_ids = resolved_ids.get("result")
            if isinstance(raw_ids, dict):
                if raw_ids.get("imdb_id"):
                    self.imdb_id = str(raw_ids["imdb_id"])
                if raw_ids.get("tvdb_id"):
                    self.tvdb_id = str(raw_ids["tvdb_id"])

        tvdb_result = media_data.get("tvdb_data")
        if isinstance(tvdb_result, dict) and tvdb_result.get("success") is True:
            raw_tvdb = tvdb_result.get("result")
            if isinstance(raw_tvdb, dict):
                self.tvdb_data = raw_tvdb
                if raw_tvdb.get("id"):
                    self.tvdb_id = str(raw_tvdb["id"])

        anilist_result = media_data.get("ani_list_data")
        if isinstance(anilist_result, dict) and anilist_result.get("success") is True:
            raw_anilist = anilist_result.get("result")
            if isinstance(raw_anilist, dict) and raw_anilist:
                self.anilist_data = raw_anilist
                if raw_anilist.get("id"):
                    self.anilist_id = str(raw_anilist["id"])
                if raw_anilist.get("idMal"):
                    self.mal_id = str(raw_anilist["idMal"])

    def copy_from(self, other: "MediaSearchPayload") -> None:
        """Replace this payload in place so existing Jinja references remain valid."""

        other.validate()
        for payload_field in fields(self):
            setattr(
                self, payload_field.name, deepcopy(getattr(other, payload_field.name))
            )

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
        self.plugin_data.clear()
