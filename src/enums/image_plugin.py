from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum
from typing_extensions import override


class ImagePlugin(CaseInsensitiveEnum):
    FPNG = auto_enum()
    IMWRI = auto_enum()

    @override
    def __str__(self) -> str:
        str_map = {ImagePlugin.FPNG: "fpng", ImagePlugin.IMWRI: "imwri"}
        return str_map[self]
