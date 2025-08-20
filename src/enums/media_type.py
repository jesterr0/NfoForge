from src.enums import CaseInsensitiveStrEnum


class MediaType(CaseInsensitiveStrEnum):
    MOVIES = "Movies"
    SERIES = "Series"

    @classmethod
    def search_type(cls, val: str, strict: bool = False) -> "MediaType | None":
        val = str(val).lower()
        if val in {"movie", "movies"}:
            return cls.MOVIES
        elif val in {"tv", "series", "show", "anime"}:
            return cls.SERIES
        if strict:
            raise ValueError("Failed to detect MediaType")
