from src.enums import CaseInsensitiveStrEnum


class QualitySelection(CaseInsensitiveStrEnum):
    """Release source, in the spelling that goes into a title or filename.

    These values are rendered directly by the `{source}` token and are the
    literal item text of the wizard's Quality combo box, so they have to read
    the way a release name reads. ``WEB_DL`` was "WEBDL" for exactly that
    reason -- it flowed straight into every generated title, and Aither, LST,
    ReelFliX and BeyondHD all require "WEB-DL".
    """

    SDTV = "SDTV"
    HDTV = "HDTV"
    DVD = "DVD"
    WEB_RIP = "WEBRip"
    WEB_DL = "WEB-DL"
    BLURAY = "BluRay"
    UHD_BLURAY = "UHD BluRay"
