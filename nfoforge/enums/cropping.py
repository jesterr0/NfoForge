from enum import auto as auto_enum
from typing import override

from nfoforge.enums import CaseInsensitiveEnum


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
