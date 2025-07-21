from enum import auto as auto_enum

from typing_extensions import override

from src.enums import CaseInsensitiveEnum


class Dependencies(CaseInsensitiveEnum):
    FFMPEG = auto_enum()
    FRAME_FORGE = auto_enum()
    MKBRR = auto_enum()

    @override
    def __str__(self) -> str:
        dep_map = {
            Dependencies.FFMPEG: "FFMPEG",
            Dependencies.FRAME_FORGE: "FrameForge",
            Dependencies.MKBRR: "mkbrr",
        }
        return dep_map[self]

    def dep_map(self) -> dict[str, str]:
        dep_map = {
            Dependencies.FFMPEG: {
                "cfg_var": "ffmpeg",
                "app_folder": "ffmpeg",
                "executable": "ffmpeg",
            },
            Dependencies.FRAME_FORGE: {
                "cfg_var": "frame_forge",
                "app_folder": "frame_forge",
                "executable": "frameforge",
            },
            Dependencies.MKBRR: {
                "cfg_var": "mkbrr",
                "app_folder": "mkbrr",
                "executable": "mkbrr",
            },
        }
        return dep_map[self]
