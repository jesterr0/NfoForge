from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum


class ImagePlugin(CaseInsensitiveEnum):
    FPNG = auto_enum()
    IMWRI = auto_enum()

    def __str__(self) -> str:
        if self == ImagePlugin.FPNG:
            return "fpng"
        elif self == ImagePlugin.IMWRI:
            return "imwri"
