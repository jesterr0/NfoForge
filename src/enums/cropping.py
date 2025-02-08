from enum import auto as auto_enum
from typing_extensions import override
from src.enums import CaseInsensitiveEnum


class Cropping(CaseInsensitiveEnum):
    DISABLED = auto_enum()
    AUTO = auto_enum()
    MANUAL = auto_enum()

    @override
    def __str__(self) -> str:
        str_map = {
            Cropping.DISABLED: "Disabled",
            Cropping.AUTO: "Automatic",
            Cropping.MANUAL: "Manual",
        }
        return str_map[self]
