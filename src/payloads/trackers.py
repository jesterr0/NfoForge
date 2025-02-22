from dataclasses import dataclass
from src.enums.trackers.beyondhd import BHDPromo, BHDLiveRelease
from src.enums.trackers.morethantv import MTVSourceOrigin
from src.enums.token_replacer import ColonReplace
from src.enums.url_type import URLType


@dataclass(slots=True)
class TrackerInfo:
    # tracker settings
    upload_enabled: bool = True
    announce_url: str | None = None
    enabled: bool = False
    source: str | None = None
    comments: str | None = None
    nfo_template: str | None = None

    # hard coded values
    max_piece_size: int = 0

    # screenshot settings
    url_type: URLType = URLType.BBCODE
    column_s: int = 1
    column_space: int = 1
    row_space: int = 1

    # title token override
    mvr_title_override_enabled: bool = False
    mvr_title_colon_replace: ColonReplace = ColonReplace.REPLACE_WITH_DASH
    mvr_title_token_override: str = ""
    mvr_title_replace_map: list[tuple[str, str]] | None = None


@dataclass(slots=True)
class MoreThanTVInfo(TrackerInfo):
    anonymous: int = 0
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    totp: str | None = None
    group_description: str | None = None
    additional_tags: str | None = None
    source_origin: MTVSourceOrigin = MTVSourceOrigin.UNDEFINED
    image_width: int = 350


@dataclass(slots=True)
class TorrentLeechInfo(TrackerInfo):
    username: str | None = None
    password: str | None = None
    torrent_passkey: str | None = None
    alt_2_fa_token: str | None = None

    # override url type
    url_type = URLType.HTML


@dataclass(slots=True)
class BeyondHDInfo(TrackerInfo):
    anonymous: int = 0
    api_key: str | None = None
    rss_key: str | None = None
    promo: BHDPromo = BHDPromo.NO_PROMO
    live_release: BHDLiveRelease = BHDLiveRelease.LIVE
    internal: int = 0
    image_width: int = 350


@dataclass(slots=True)
class PassThePopcornInfo(TrackerInfo):
    api_user: str | None = None
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    totp: str | None = None


@dataclass(slots=True)
class ReelFlixInfo(TrackerInfo):
    api_key: str | None = None
    anonymous: int = 0
    internal: int = 0
    personal_release: int = 0
    stream_optimized: int = 0
    opt_in_to_mod_queue: int = 0
    image_width: int = 350

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
    image_width: int = 350

    # below is only available to staff and internal users
    featured: int = 0
    free: int = 0
    double_up: int = 0
    sticky: int = 0


@dataclass(slots=True)
class HunoInfo(TrackerInfo):
    api_key: str | None = None
    anonymous: int = 0
    internal: int = 0
    stream_optimized: int = 0
    image_width: int = 350
