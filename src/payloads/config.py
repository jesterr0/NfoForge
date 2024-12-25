from dataclasses import dataclass
from pathlib import Path

from src.logger.nfo_forge_logger import LogLevel
from src.enums.theme import NfoForgeTheme
from src.enums.profile import Profile
from src.enums.media_mode import MediaMode
from src.enums.image_host import ImageHost
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.image_plugin import ImagePlugin
from src.enums.indexer import Indexer
from src.enums.cropping import Cropping
from src.enums.subtitles import SubtitleAlignment
from src.enums.token_replacer import ColonReplace
from src.enums.url_type import URLType
from src.payloads.trackers import TrackerInfo
from src.payloads.clients import TorrentClient
from src.payloads.watch_folder import WatchFolder
from src.payloads.image_hosts import (
    CheveretoV3Payload,
    CheveretoV4Payload,
    ImageBBPayload,
)

# TODO: add nfo enable_disable flag or something?


@dataclass(slots=True)
class ProgramConfigPayload:
    current_config: str | None = None
    main_window_position: str | None = None


@dataclass(slots=True)
class ConfigPayload:
    # general
    ui_suffix: str
    nfo_forge_theme: NfoForgeTheme
    profile: Profile
    media_mode: MediaMode
    source_media_ext_filter: list[str]
    encode_media_ext_filter: list[str]
    media_input_dir: bool
    releasers_name: str
    image_host: ImageHost
    timeout: int
    log_level: LogLevel
    log_total: int

    # dependencies
    ffmpeg: Path | None
    frame_forge: Path | None

    # api keys
    tmdb_api_key: str

    # trackers
    tracker_order: list[int]
    piece_sizes: dict
    mtv_tracker: TrackerInfo
    tl_tracker: TrackerInfo
    bhd_tracker: TrackerInfo

    # torrent client settings
    qbittorrent: TorrentClient
    deluge: TorrentClient
    rtorrent: TorrentClient
    transmission: TorrentClient

    # watch folder
    watch_folder: WatchFolder

    # movie renamer settings
    mvr_enabled: bool
    mvr_imdb_parse: bool
    mvr_replace_illegal_chars: bool
    mvr_parse_with_media_info: bool
    mvr_colon_replacement: ColonReplace
    mvr_token: str
    mvr_clean_title_rules: list[tuple[str, str]]
    mvr_release_group: str

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
    trim_start: int
    trim_end: int
    required_selected_screens: int
    comparison_subtitles: bool
    comparison_subtitle_source_name: str
    comparison_subtitle_encode_name: str
    compress_images: bool
    indexer: Indexer
    image_plugin: ImagePlugin

    # image hosts
    chevereto_v3: CheveretoV3Payload
    chevereto_v4: CheveretoV4Payload
    image_bb: ImageBBPayload

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
