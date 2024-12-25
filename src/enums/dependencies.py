from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum


class Dependencies(CaseInsensitiveEnum):
    FFMPEG = auto_enum()
    FRAME_FORGE = auto_enum()

    def __str__(self) -> str:
        dep_map = {
            Dependencies.FFMPEG: "FFMPEG",
            Dependencies.FRAME_FORGE: "FrameForge",
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
        }
        return dep_map[self]
