from src.enums import CaseInsensitiveStrEnum


class MediaType(CaseInsensitiveStrEnum):
    MOVIE = "Movie"
    SERIES = "Series"

    @classmethod
    def search_type(cls, val: str) -> "MediaType | None":
        val = str(val).lower()
        if val in ("movie", "movies"):
            return cls.MOVIE
        elif val in ("tv", "series", "show", "anime"):
            return cls.SERIES
        
    @classmethod
    def strict_search_type(cls, val: str) -> "MediaType":
        media_type = cls.search_type(val)
        if not media_type:
            raise ValueError("Failed to detect MediaType")
        return media_type
