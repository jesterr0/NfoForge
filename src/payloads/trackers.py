from dataclasses import dataclass
from src.enums.trackers.morethantv import MTVSourceOrigin
from src.enums.trackers.beyondhd import BHDPromo, BHDLiveRelease


@dataclass(slots=True)
class TrackerInfo:
    upload_enabled: bool = True
    announce_url: str | None = None
    enabled: bool = False
    source: str | None = None
    comments: str | None = None
    nfo_template: str | None = None
    max_piece_size: int = 0


@dataclass(slots=True)
class MoreThanTvInfo(TrackerInfo):
    anonymous: int = 0
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    totp: str | None = None
    group_description: str | None = None
    additional_tags: str | None = None
    source_origin: MTVSourceOrigin = MTVSourceOrigin.UNDEFINED


@dataclass(slots=True)
class TorrentLeechInfo(TrackerInfo):
    username: str | None = None
    password: str | None = None
    torrent_passkey: str | None = None
    alt_2_fa_token: str | None = None


@dataclass(slots=True)
class BeyondHDInfo(TrackerInfo):
    anonymous: int = 0
    api_key: str | None = None
    rss_key: str | None = None
    promo: BHDPromo = BHDPromo.NO_PROMO
    live_release: BHDLiveRelease = BHDLiveRelease.LIVE
    internal: int = 0


@dataclass(slots=True)
class PassThePopcornInfo(TrackerInfo):
    api_user: str | None = None
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    totp: str | None = None
    ptpimg_api_key: str | None = None
    reupload_images_to_ptp_img: bool = False


@dataclass(slots=True)
class ReelFlixInfo(TrackerInfo):
    api_key: str | None = None
    anonymous: int = 0
    internal: int = 0
    personal_release: int = 0
    stream_optimized: int = 0
    opt_in_to_mod_queue: int = 0

    # below is only available to staff and internal users
    featured: int = 0
    free: int = 0
    double_up: int = 0
    sticky: int = 0


@dataclass(slots=True)
class AitherInfo(TrackerInfo):
    api_key: str | None = None
    anonymous: int = 0
    internal: int = 0
    personal_release: int = 0
    stream_optimized: int = 0
    opt_in_to_mod_queue: int = 0

    # below is only available to staff and internal users
    featured: int = 0
    free: int = 0
    double_up: int = 0
    sticky: int = 0
