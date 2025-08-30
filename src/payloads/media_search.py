from dataclasses import dataclass, field

from imdbinfo.models import MovieDetail

from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries


@dataclass(slots=True)
class MediaSearchPayload:
    media_type: MediaType | None = None
    imdb_id: str | None = None
    imdb_data: MovieDetail | None = None
    tmdb_id: str | None = None
    tmdb_data: dict | None = None
    tvdb_id: str | None = None
    tvdb_data: dict | None = None
    anilist_id: str | None = None
    anilist_data: dict | None = None
    mal_id: str | None = None
    title: str | None = None
    year: int | None = None
    original_title: str | None = None
    genres: list[TMDBGenreIDsMovies | TMDBGenreIDsSeries] = field(default_factory=list)

    def reset(self) -> None:
        self.media_type = None
        self.imdb_id = None
        self.imdb_data = None
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
