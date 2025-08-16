from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.enums.cropping import Cropping
from src.enums.image_host import ImageHost, ImageSource
from src.enums.image_plugin import ImagePlugin
from src.enums.indexer import Indexer
from src.enums.media_mode import MediaMode
from src.enums.profile import Profile
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.subtitles import SubtitleAlignment
from src.enums.theme import NfoForgeTheme
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection
from src.enums.url_type import URLType
from src.logger.nfo_forge_logger import LogLevel
from src.payloads.clients import TorrentClient
from src.payloads.image_hosts import (
    CheveretoV3Payload,
    CheveretoV4Payload,
    ImageBBPayload,
    ImageBoxPayload,
    PTPIMGPayload,
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
    UploadCXInfo,
)
from src.payloads.watch_folder import WatchFolder


@dataclass(slots=True)
class ProgramConfigPayload:
    current_config: str | None = None
    main_window_position: str | None = None


@dataclass(slots=True)
class ConfigPayload:
    # general
    ui_suffix: str
    ui_scale_factor: float
    nfo_forge_theme: NfoForgeTheme
    profile: Profile
    media_mode: MediaMode
    source_media_ext_filter: list[str]
    encode_media_ext_filter: list[str]
    releasers_name: str
    tmdb_language: str
    timeout: int
    enable_prompt_overview: bool
    enable_mkbrr: bool
    log_level: LogLevel
    log_total: int
    working_dir: Path

    # dependencies
    ffmpeg: Path | None
    ffprobe: Path | None
    frame_forge: Path | None
    mkbrr: Path | None

    # api keys
    tmdb_api_key: str

    # trackers
    tracker_order: list[TrackerSelection]
    last_used_img_host: dict[TrackerSelection, ImageHost | ImageSource]
    mtv_tracker: MoreThanTVInfo
    tl_tracker: TorrentLeechInfo
    bhd_tracker: BeyondHDInfo
    ptp_tracker: PassThePopcornInfo
    rf_tracker: ReelFlixInfo
    aither_tracker: AitherInfo
    huno_tracker: HunoInfo
    lst_tracker: LSTInfo
    darkpeers_tracker: DarkPeersInfo
    shareisland_tracker: ShareIslandInfo
    ulcx_tracker: UploadCXInfo
    oe_tracker: OnlyEncodesInfo

    # torrent client settings
    qbittorrent: TorrentClient
    deluge: TorrentClient
    rtorrent: TorrentClient
    transmission: TorrentClient

    # watch folder
    watch_folder: WatchFolder

    # movie renamer settings
    mvr_enabled: bool
    mvr_replace_illegal_chars: bool
    mvr_colon_replace_filename: ColonReplace
    mvr_colon_replace_title: ColonReplace
    mvr_parse_filename_attributes: bool
    mvr_token: str
    mvr_title_token: str
    mvr_clean_title_rules: list[tuple[str, str]]
    mvr_clean_title_rules_modified: bool
    mvr_release_group: str
    mvr_mi_video_dynamic_range: dict[str, Any]

    # user tokens
    user_tokens: dict[str, tuple[str, str]]

    # screenshot settings
    crop_mode: Cropping
    screenshots_enabled: bool
    screen_shot_count: int
    ss_mode: ScreenShotMode
    sub_size_height_720: int
    sub_size_height_1080: int
    sub_size_height_2160: int
    subtitle_alignment: SubtitleAlignment
    subtitle_color: str
    subtitle_outline_color: str
    trim_start: int
    trim_end: int
    min_required_selected_screens: int
    max_required_selected_screens: int
    comparison_subtitles: bool
    comparison_subtitle_source_name: str
    comparison_subtitle_encode_name: str
    optimize_generated_images: bool
    optimize_dl_url_images: bool
    optimize_dl_url_images_percentage: float
    indexer: Indexer
    image_plugin: ImagePlugin

    # image hosts
    chevereto_v3: CheveretoV3Payload
    chevereto_v4: CheveretoV4Payload
    image_bb: ImageBBPayload
    image_box: ImageBoxPayload
    ptpimg: PTPIMGPayload

    # urls
    urls_alt: str
    urls_columns: int
    urls_vertical: int
    urls_horizontal: int
    urls_mode: int
    urls_type: URLType
    urls_image_width: int
    urls_manual: int

    # plugins
    wizard_page: str | None
    token_replacer: str | None
    pre_upload: str | None

    # template settings
    block_start_string: str
    block_end_string: str
    block_syntax_color: str
    variable_start_string: str
    variable_end_string: str
    variable_syntax_color: str
    comment_start_string: str
    comment_end_string: str
    comment_syntax_color: str
    line_statement_prefix: str
    line_statement_syntax_color: str
    line_comment_prefix: str
    line_comment_syntax_color: str
    trim_blocks: bool
    lstrip_blocks: bool
    newline_sequence: str
    keep_trailing_newline: bool
    enable_sandbox_prompt_tokens: bool

    # release notes
    enable_release_notes: bool
    last_used_release_note: str
    release_notes: dict[str, str]
