from enum import auto as auto_enum
from typing_extensions import override
from src.enums import CaseInsensitiveEnum


class Profile(CaseInsensitiveEnum):
    BASIC = auto_enum()
    ADVANCED = auto_enum()
    PLUGIN = auto_enum()

    @override
    def __str__(self):
        str_map = {
            Profile.BASIC: "Basic",
            Profile.ADVANCED: "Advanced",
            Profile.PLUGIN: "Plugin",
        }
        return str_map[self]
