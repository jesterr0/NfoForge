from typing_extensions import override
from src.enums import CaseInsensitiveEnum


class ImageHost(CaseInsensitiveEnum):
    CHEVERETO_V3 = "Chevereto v3"
    CHEVERETO_V4 = "Chevereto v4"
    IMAGE_BOX = "ImageBox"
    IMAGE_BB = "ImageBB"
    PTPIMG = "PTPIMG"

    # used outside of the UI
    DISABLED = "Disabled"

    @override
    def __str__(self) -> str:
        return self.value


class ImageSource(CaseInsensitiveEnum):
    IMAGES = "IMGs"
    URLS = "URLs"

    @override
    def __str__(self) -> str:
        return self.value
