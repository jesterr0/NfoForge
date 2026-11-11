"""Full-disc releases: Blu-ray (`BDMV`) and DVD (`VIDEO_TS`) folders."""

from nfoforge.core.disc.bdinfo import (
    BDInfoError,
    BdinfoRsScanner,
    BDInfoScanner,
)
from nfoforge.core.disc.bdinfo_report import (
    BDAudioStream,
    BDInfoReport,
    BDInfoReportError,
    BDSubtitleStream,
    BDVideoStream,
    parse_bdinfo_report,
)
from nfoforge.core.disc.detect import (
    detect_disc,
    directory_size,
    find_discs,
    holds_disc,
    mark_main_playlists,
)
from nfoforge.core.disc.model import (
    Disc,
    DiscError,
    DiscPlaylist,
    DiscType,
    PlaylistItem,
    disc_warnings,
    normalize_playlist_id,
)
from nfoforge.core.disc.mount import (
    MOUNTS,
    ImageMounter,
    Mount,
    MountError,
    MountRegistry,
    is_disc_image,
)
from nfoforge.core.disc.naming import (
    DISC_REGIONS,
    DISC_SOURCES,
    detect_region,
    disc_quality,
    dvd_standard,
)
from nfoforge.core.disc.release import DiscRelease, disc_release
from nfoforge.core.disc.report import (
    MISSING_BDINFO,
    cached_bdinfo_report,
    describe_disc,
)
from nfoforge.core.disc.select import (
    choose_playlist,
    describe_playlist,
    describe_playlists,
    format_duration,
    needs_playlist_choice,
    preferred_playlist,
)
from nfoforge.core.disc.serialize import disc_from_dict, disc_to_dict
from nfoforge.core.disc.shots import FrameTarget, disc_frame_targets
from nfoforge.core.disc.size import DiscSize, disc_size_class

__all__ = [
    "DISC_REGIONS",
    "DISC_SOURCES",
    "MISSING_BDINFO",
    "MOUNTS",
    "BDAudioStream",
    "BDInfoError",
    "BDInfoReport",
    "BDInfoReportError",
    "BDInfoScanner",
    "BDSubtitleStream",
    "BDVideoStream",
    "BdinfoRsScanner",
    "Disc",
    "DiscError",
    "DiscPlaylist",
    "DiscRelease",
    "DiscSize",
    "DiscType",
    "FrameTarget",
    "ImageMounter",
    "Mount",
    "MountError",
    "MountRegistry",
    "PlaylistItem",
    "cached_bdinfo_report",
    "choose_playlist",
    "describe_disc",
    "describe_playlist",
    "describe_playlists",
    "detect_disc",
    "detect_region",
    "disc_frame_targets",
    "disc_from_dict",
    "disc_quality",
    "disc_release",
    "directory_size",
    "disc_size_class",
    "disc_to_dict",
    "disc_warnings",
    "dvd_standard",
    "find_discs",
    "format_duration",
    "holds_disc",
    "is_disc_image",
    "mark_main_playlists",
    "needs_playlist_choice",
    "normalize_playlist_id",
    "parse_bdinfo_report",
    "preferred_playlist",
]
