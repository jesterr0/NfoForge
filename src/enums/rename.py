from src.enums import CaseInsensitiveStrEnum


class QualitySelection(CaseInsensitiveStrEnum):
    SDTV = "SDTV"
    HDTV = "HDTV"
    DVD = "DVD"
    WEB_RIP = "WEBRip"
    WEB_DL = "WEBDL"
    BLURAY = "BluRay"
