from enum import Enum, auto as auto_enum


class UploadProcessMode(Enum):
    DUPE_CHECK = auto_enum()
    UPLOAD = auto_enum()
    PREPARE = auto_enum()


class RunPhase(Enum):
    """How far through the pipeline `process_trackers()` should go.

    Preparing stops one step short of publishing, which is what lets a job be
    saved with its titles, NFOs, uploaded images and torrent already done --
    and in turn what lets a queue upload it without stopping to ask anything.
    """

    FULL = auto_enum()
    """Everything, ending in upload and torrent-client injection."""

    PREPARE = auto_enum()
    """Everything except upload and injection."""
