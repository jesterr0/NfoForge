from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum


class Cropping(CaseInsensitiveEnum):
    DISABLED = auto_enum()
    AUTO = auto_enum()
    MANUAL = auto_enum()

    def __str__(self) -> str:
        if self == Cropping.DISABLED:
            return "Disabled"
        elif self == Cropping.AUTO:
            return "Automatic"
        elif self == Cropping.MANUAL:
            return "Manual"
