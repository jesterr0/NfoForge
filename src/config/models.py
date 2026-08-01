from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, TypedDict, overload

from src.backend.tokens import TokenSelection
from src.enums.cropping import Cropping
from src.enums.image_host import ImageHost, ImageSource
from src.enums.image_plugin import ImagePlugin
from src.enums.indexer import Indexer
from src.enums.logging_settings import LogLevel
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.subtitles import SubtitleAlignment
from src.enums.theme import NfoForgeTheme
from src.enums.token_replacer import ColonReplace
from src.enums.torrent_client import TorrentClientSelection
from src.enums.tracker_selection import TrackerSelection
from src.enums.url_type import URLType
from src.payloads.clients import (
    DelugeConfig,
    NetworkTorrentClientConfig,
    QBittorrentConfig,
    RTorrentConfig,
    TransmissionConfig,
)
from src.payloads.image_hosts import (
    CheveretoV3Payload,
    CheveretoV4Payload,
    ImageBBPayload,
    ImageBoxPayload,
    ImagePayloadBase,
)
from src.payloads.trackers import (
    AitherInfo,
    BeyondHDInfo,
    DarkPeersInfo,
    HunoInfo,
    LSTInfo,
    MoreThanTVInfo,
    OnlyEncodesInfo,
    PassThePopcornInfo,
    ReelFlixInfo,
    ShareIslandInfo,
    TorrentLeechInfo,
    TrackerInfo,
    UploadCXInfo,
)
from src.payloads.watch_folder import WatchFolder

ReplacementRule = tuple[str, str]
UserToken = tuple[str, TokenSelection]
ResolutionKey: TypeAlias = Literal["720p", "1080p", "2160p"]
HdrType: TypeAlias = Literal[
    "SDR",
    "PQ",
    "HLG",
    "HDR10",
    "HDR10+",
    "DV",
    "DV HDR10",
    "DV HDR10+",
]


class DynamicRangeSettingsData(TypedDict):
    resolutions: dict[ResolutionKey, bool]
    hdr_types: dict[HdrType, bool]
    custom_strings: dict[HdrType, str]


@dataclass(slots=True)
class ProgramConfig:
    current_config: str | None = None
    main_window_position: str | None = None


@dataclass(slots=True)
class GeneralSettings:
    ui_suffix: str
    ui_scale_factor: float
    theme: NfoForgeTheme
    enable_plugins: bool
    releasers_name: str
    tmdb_language: str
    timeout: int
    enable_prompt_overview: bool
    enable_mkbrr: bool
    log_level: LogLevel
    log_total: int
    working_dir: Path


@dataclass(slots=True)
class DependencySettings:
    ffmpeg: Path | None
    ffprobe: Path | None
    frame_forge: Path | None
    mkbrr: Path | None


@dataclass(slots=True)
class ApiKeySettings:
    tmdb: str


@dataclass(slots=True)
class TrackerSettings:
    order: list[TrackerSelection]
    last_used_image_host: dict[TrackerSelection, ImageHost | ImageSource]
    more_than_tv: MoreThanTVInfo
    torrent_leech: TorrentLeechInfo
    beyond_hd: BeyondHDInfo
    pass_the_popcorn: PassThePopcornInfo
    reelflix: ReelFlixInfo
    aither: AitherInfo
    huno: HunoInfo
    lst: LSTInfo
    dark_peers: DarkPeersInfo
    share_island: ShareIslandInfo
    upload_cx: UploadCXInfo
    only_encodes: OnlyEncodesInfo

    def by_selection(self) -> dict[TrackerSelection, TrackerInfo]:
        return {
            TrackerSelection.MORE_THAN_TV: self.more_than_tv,
            TrackerSelection.TORRENT_LEECH: self.torrent_leech,
            TrackerSelection.BEYOND_HD: self.beyond_hd,
            TrackerSelection.PASS_THE_POPCORN: self.pass_the_popcorn,
            TrackerSelection.REELFLIX: self.reelflix,
            TrackerSelection.AITHER: self.aither,
            TrackerSelection.HUNO: self.huno,
            TrackerSelection.LST: self.lst,
            TrackerSelection.DARK_PEERS: self.dark_peers,
            TrackerSelection.SHARE_ISLAND: self.share_island,
            TrackerSelection.UPLOAD_CX: self.upload_cx,
            TrackerSelection.ONLY_ENCODES: self.only_encodes,
        }


@dataclass(slots=True)
class TorrentClientSettings:
    qbittorrent: QBittorrentConfig
    deluge: DelugeConfig
    rtorrent: RTorrentConfig
    transmission: TransmissionConfig
    watch_folder: WatchFolder

    def by_selection(
        self,
    ) -> dict[TorrentClientSelection, NetworkTorrentClientConfig | WatchFolder]:
        return {
            TorrentClientSelection.QBITTORRENT: self.qbittorrent,
            TorrentClientSelection.DELUGE: self.deluge,
            TorrentClientSelection.RTORRENT: self.rtorrent,
            TorrentClientSelection.TRANSMISSION: self.transmission,
            TorrentClientSelection.WATCH_FOLDER: self.watch_folder,
        }


@dataclass(slots=True)
class MovieSettings:
    enabled: bool
    replace_illegal_chars: bool
    filename_colon_replace: ColonReplace
    title_colon_replace: ColonReplace
    parse_filename_attributes: bool
    filename_token: str
    title_token: str
    release_group: str


@dataclass(slots=True)
class SeriesSettings:
    enabled: bool
    replace_illegal_chars: bool
    filename_colon_replace: ColonReplace
    title_colon_replace: ColonReplace
    parse_filename_attributes: bool
    standard_episode_token: str
    daily_episode_token: str
    anime_episode_token: str
    season_folder_token: str
    multi_episode_style: MultiEpisodeStyle
    standard_title_token: str
    daily_title_token: str
    anime_title_token: str
    release_group: str


@dataclass(slots=True)
class DynamicRangeSettings:
    resolutions: dict[ResolutionKey, bool]
    hdr_types: dict[HdrType, bool]
    custom_strings: dict[HdrType, str]

    def to_dict(
        self,
    ) -> DynamicRangeSettingsData:
        return {
            "resolutions": dict[ResolutionKey, bool](self.resolutions),
            "hdr_types": dict[HdrType, bool](self.hdr_types),
            "custom_strings": dict[HdrType, str](self.custom_strings),
        }

    @overload
    def __getitem__(self, key: Literal["resolutions"]) -> dict[ResolutionKey, bool]: ...

    @overload
    def __getitem__(self, key: Literal["hdr_types"]) -> dict[HdrType, bool]: ...

    @overload
    def __getitem__(self, key: Literal["custom_strings"]) -> dict[HdrType, str]: ...

    @overload
    def __getitem__(
        self, key: str
    ) -> dict[ResolutionKey, bool] | dict[HdrType, bool] | dict[HdrType, str]: ...

    def __getitem__(
        self, key: str
    ) -> dict[ResolutionKey, bool] | dict[HdrType, bool] | dict[HdrType, str]:
        if key == "resolutions":
            return self.resolutions
        if key == "hdr_types":
            return self.hdr_types
        if key == "custom_strings":
            return self.custom_strings
        raise KeyError(key)

    @overload
    def get(
        self, key: Literal["resolutions"], default: None = None
    ) -> dict[ResolutionKey, bool] | None: ...

    @overload
    def get(
        self, key: Literal["resolutions"], default: dict[ResolutionKey, bool]
    ) -> dict[ResolutionKey, bool]: ...

    @overload
    def get(
        self, key: Literal["hdr_types"], default: None = None
    ) -> dict[HdrType, bool] | None: ...

    @overload
    def get(
        self, key: Literal["hdr_types"], default: dict[HdrType, bool]
    ) -> dict[HdrType, bool]: ...

    @overload
    def get(
        self, key: Literal["custom_strings"], default: None = None
    ) -> dict[HdrType, str] | None: ...

    @overload
    def get(
        self, key: Literal["custom_strings"], default: dict[HdrType, str]
    ) -> dict[HdrType, str]: ...

    @overload
    def get(
        self,
        key: str,
        default: dict[ResolutionKey, bool]
        | dict[HdrType, bool]
        | dict[HdrType, str]
        | None = None,
    ) -> (
        dict[ResolutionKey, bool] | dict[HdrType, bool] | dict[HdrType, str] | None
    ): ...

    def get(
        self,
        key: str,
        default: dict[ResolutionKey, bool]
        | dict[HdrType, bool]
        | dict[HdrType, str]
        | None = None,
    ) -> dict[ResolutionKey, bool] | dict[HdrType, bool] | dict[HdrType, str] | None:
        try:
            return self[key]
        except KeyError:
            return default


@dataclass(slots=True)
class GlobalManagementSettings:
    title_clean_rules: list[ReplacementRule]
    title_clean_rules_modified: bool
    video_dynamic_range: DynamicRangeSettings


@dataclass(slots=True)
class UserTokenSettings:
    tokens: dict[str, UserToken]


@dataclass(slots=True)
class ScreenshotSettings:
    crop_mode: Cropping
    enabled: bool
    count: int
    mode: ScreenShotMode
    subtitle_height_720: int
    subtitle_height_1080: int
    subtitle_height_2160: int
    subtitle_alignment: SubtitleAlignment
    subtitle_color: str
    subtitle_outline_color: str
    trim_start: int
    trim_end: int
    min_required_selected: int
    max_required_selected: int
    comparison_subtitles: bool
    comparison_source_name: str
    comparison_encode_name: str
    optimize_generated_images: bool
    optimize_downloaded_images: bool
    optimize_downloaded_images_percentage: float
    indexer: Indexer
    image_plugin: ImagePlugin


@dataclass(slots=True)
class ImageHostSettings:
    chevereto_v3: CheveretoV3Payload
    chevereto_v4: CheveretoV4Payload
    image_bb: ImageBBPayload
    image_box: ImageBoxPayload

    def by_selection(self) -> dict[ImageHost, ImagePayloadBase]:
        return {
            ImageHost.CHEVERETO_V3: self.chevereto_v3,
            ImageHost.CHEVERETO_V4: self.chevereto_v4,
            ImageHost.IMAGE_BB: self.image_bb,
            ImageHost.IMAGE_BOX: self.image_box,
        }


@dataclass(slots=True)
class UrlSettings:
    alt: str
    columns: int
    vertical: int
    horizontal: int
    mode: int
    type: URLType
    image_width: int
    manual: int


@dataclass(slots=True)
class PluginSettings:
    wizard_page: str | None
    token_replacer: str | None
    pre_upload: str | None
    metadata_provider: str | None


@dataclass(slots=True)
class TemplateSettings:
    block_syntax_color: str
    variable_syntax_color: str
    comment_syntax_color: str
    warning_syntax_color: str
    trim_blocks: bool
    lstrip_blocks: bool
    newline_sequence: str
    keep_trailing_newline: bool
    enable_sandbox_prompt_tokens: bool


@dataclass(slots=True)
class ReleaseNoteSettings:
    enabled: bool
    last_used: str
    notes: dict[str, str]


@dataclass(slots=True)
class WidgetSettings:
    prompt_token_editor_warn_on_missing: bool


@dataclass(slots=True)
class AppConfig:
    general: GeneralSettings
    dependencies: DependencySettings
    api_keys: ApiKeySettings
    trackers: TrackerSettings
    torrent_clients: TorrentClientSettings
    movie: MovieSettings
    series: SeriesSettings
    global_management: GlobalManagementSettings
    user_tokens: UserTokenSettings
    screenshots: ScreenshotSettings
    image_hosts: ImageHostSettings
    urls: UrlSettings
    plugins: PluginSettings
    templates: TemplateSettings
    release_notes: ReleaseNoteSettings
    widgets: WidgetSettings
