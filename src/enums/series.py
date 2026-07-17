from src.enums import CaseInsensitiveStrEnum


class EpisodeFormat(CaseInsensitiveStrEnum):
    STANDARD = "Standard"
    DAILY_DATE = "Daily / Date"
    ANIME_ABSOLUTE = "Anime / Absolute"
    # Planned placeholder: DVD ordering currently reuses the Standard token
    # set (see docs/view/getting-started/series-support.md). Kept for a future
    # dedicated DVD filename/title format; not yet wired into the token sets.
    DVD = "DVD"
