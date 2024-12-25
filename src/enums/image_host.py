from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum


class ImageHost(CaseInsensitiveEnum):
    DISABLED = auto_enum()
    CHEVERETO_V3 = auto_enum()
    CHEVERETO_V4 = auto_enum()
    IMAGE_BOX = auto_enum()
    IMAGE_BB = auto_enum()

    def __str__(self) -> str:
        img_host_map = {
            ImageHost.DISABLED: "Disabled",
            ImageHost.CHEVERETO_V3: "Chevereto v3",
            ImageHost.CHEVERETO_V4: "Chevereto v4",
            ImageHost.IMAGE_BOX: "ImageBox",
            ImageHost.IMAGE_BB: "ImageBB",
        }
        return img_host_map[self]
