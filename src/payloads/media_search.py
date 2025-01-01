from dataclasses import dataclass, field
from imdb.Movie import Movie
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries


@dataclass(slots=True)
class MediaSearchPayload:
    imdb_id: str | None = None
    imdb_data: Movie | None = None
    tmdb_id: str | None = None
    tmdb_data: dict | None = None
    title: str | None = None
    year: int | None = None
    original_title: str | None = None
    genres: list[TMDBGenreIDsMovies | TMDBGenreIDsSeries] = field(default_factory=list)

    def reset(self) -> None:
        self.imdb_id = None
        self.imdb_data = None
        self.tmdb_id = None
        self.tmdb_data = None
        self.title = None
        self.year = None
        self.original_title = None
        self.genres = []
