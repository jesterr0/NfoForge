from enum import auto as auto_enum
from enum import Enum


class UploadProcessMode(Enum):
    DUPE_CHECK = auto_enum()
    UPLOAD = auto_enum()
