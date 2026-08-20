from src.enums import CaseInsensitiveStrEnum


class MediaSearchMode(CaseInsensitiveStrEnum):
    BOTH = "Movies & TV"
    MOVIES = "Movies only"
    TV = "TV only"
