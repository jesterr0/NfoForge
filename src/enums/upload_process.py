from enum import Enum, auto as auto_enum


class UploadProcessMode(Enum):
    DUPE_CHECK = auto_enum()
    UPLOAD = auto_enum()
