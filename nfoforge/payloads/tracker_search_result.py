from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class TrackerSearchResult:
    name: str | None = None
    url: str | None = None
    download_link: str | None = None
    release_type: str | None = None
    release_size: int | None = None
    created_at: datetime | None = None
    seeders: int | None = None
    leechers: int | None = None
    grabs: int | None = None
    files: int | None = None
    imdb_id: str | None = None
    tmdb_id: str | None = None
    uploader: str | None = None
    info_hash: str | None = None
