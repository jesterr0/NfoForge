from pathlib import Path
import tomlkit
from tomlkit import TOMLDocument
from typing import TYPE_CHECKING

from src.config.dependencies import FindDependencies
from src.backend.utils.working_dir import RUNTIME_DIR
from src.enums.theme import NfoForgeTheme
from src.enums.cropping import Cropping
from src.enums.indexer import Indexer
from src.enums.media_mode import MediaMode
from src.enums.profile import Profile
from src.enums.image_host import ImageHost
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.image_plugin import ImagePlugin
from src.enums.subtitles import SubtitleAlignment
from src.enums.trackers.morethantv import MTVSourceOrigin
from src.enums.trackers.beyondhd import BHDPromo, BHDLiveRelease
from src.enums.tracker_selection import TrackerSelection
from src.enums.token_replacer import ColonReplace
from src.enums.torrent_client import TorrentClientSelection
from src.enums.url_type import URLType
from src.enums.logging_settings import LogLevel
from src.payloads.config import ConfigPayload, ProgramConfigPayload
from src.payloads.shared_data import SharedPayload
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.trackers import (
    TrackerInfo,
    MoreThanTVInfo,
    TorrentLeechInfo,
    BeyondHDInfo,
    PassThePopcornInfo,
    ReelFlixInfo,
    AitherInfo,
)
from src.payloads.clients import TorrentClient
from src.payloads.watch_folder import WatchFolder
from src.payloads.image_hosts import (
    ImagePayloadBase,
    CheveretoV3Payload,
    CheveretoV4Payload,
    ImageBBPayload,
    ImageBoxPayload,
    PTPIMGPayload,
)
from src.exceptions import ConfigError
from src.nf_jinja2 import Jinja2TemplateEngine

if TYPE_CHECKING:
    from src.plugins.plugin_payload import PluginPayload


# TODO: add cryptography


class Config:
    """
    Parse config file and create a payload object to be used throughout
    the program as needed as well as store other payloads that might need shared
    """

    DEV_MODE: bool = False

    ACCEPTED_EXTENSIONS = (".mkv", ".mp4")

    QBIT_SPECIFIC = ("category",)

    DELUGE_SPECIFIC = ("label", "path")

    RTORRENT_SPECIFIC = ("label", "path")

    TRANSMISSION_SPECIFIC = ("label", "path")

    CONFIG_DEFAULT = RUNTIME_DIR / "config" / "defaults" / "default_config.toml"
    PROGRAM_CONF_DEFAULT = (
        RUNTIME_DIR / "config" / "defaults" / "default_program_conf.toml"
    )

    CONF_PATH = RUNTIME_DIR / "config" / "program" / "conf.toml"

    USER_CONFIG_DIR = RUNTIME_DIR / "config" / "user"

    TRACKER_COOKIE_PATH = RUNTIME_DIR / "cookies"

    def __init__(self, config_file: str | None):
        # load various directories as needed
        self.TRACKER_COOKIE_PATH.mkdir(exist_ok=True, parents=True)

        # keep track of plugins
        self.loaded_plugins: dict[str, "PluginPayload"] = {}

        # load program config
        self.program_conf = ProgramConfigPayload()
        self._program_conf_toml_data = None
        self.load_program_conf(config_file)

        # variables that are assigned during init
        self.cfg_payload: ConfigPayload = None
        self._toml_data = None
        self.load_config(config_file)

        # keep track of last data used to prevent un-needed writes when saving the config(s)
        self._program_conf_data_last = None
        self._config_data_last = None

        # used for misc shared data, this will be the only payload
        # that we won't use slots on. So it can be used for ANYTHING else.
        self.shared_data = SharedPayload()

        # additional payloads
        self.media_search_payload = MediaSearchPayload()
        self.media_input_payload = MediaInputPayload()

        # maps
        self.tracker_map = self._tracker_map()
        self.client_map = self._client_map()
        self.image_host_map = self._image_host_map()

        # dependencies
        self._init_dependencies()

        # call save just in case some data is not up to date
        self.save_config()

        # jinja engine
        self.jinja_engine = Jinja2TemplateEngine(**self._jinja_env_settings())

    def reset_config(self) -> None:
        """Reset the configuration payloads to their default values."""
        self.shared_data.reset()

        self.media_search_payload.reset()
        self.media_input_payload.reset()

        self.jinja_engine.reset_added_globals()

    def load_program_conf(self, config_file: str | None) -> None:
        """
        Loads program config, this will be small and only control very
        unique settings that doesn't belong in the main config.
        """
        self.CONF_PATH.parent.mkdir(exist_ok=True, parents=True)
        if self.CONF_PATH.exists():
            with open(self.CONF_PATH, "r") as toml_file:
                self._program_conf_toml_data = self.check_toml_updates(
                    tomlkit.parse(toml_file.read()),
                    tomlkit.parse(self.PROGRAM_CONF_DEFAULT.read_text()),
                )
                if config_file:
                    self._program_conf_toml_data["current_config"] = config_file
                self._program_conf_data_last = self._program_conf_toml_data
                self.update_conf_payload()
            self.save_program_conf()
        else:
            with open(self.CONF_PATH, "w") as toml_file:
                toml_file.write(self.PROGRAM_CONF_DEFAULT.read_text())
            self.load_program_conf(config_file)

    def update_conf_payload(self) -> None:
        data = self._program_conf_toml_data
        self.program_conf.current_config = data.get("current_config", "config")
        self.program_conf.main_window_position = data.get("main_window_position")

    def save_program_conf(self) -> None:
        """Converts config payload object to TOML and writes to a file"""
        try:
            # update the toml object
            self._program_conf_toml_data["current_config"] = (
                self.program_conf.current_config
                if self.program_conf.current_config
                else ""
            )
            self._program_conf_toml_data["main_window_position"] = (
                self.program_conf.main_window_position
                if self.program_conf.main_window_position
                else ""
            )

            # if last data does not equal current data, we'll write the changes to file while also updating
            # the last data variable with the latest data
            if self._program_conf_data_last or (
                self._program_conf_data_last != self._program_conf_toml_data
            ):
                with open(self.CONF_PATH, "w") as toml_file:
                    self._program_conf_data_last = self._program_conf_toml_data
                    toml_file.write(tomlkit.dumps(self._program_conf_toml_data))

        except Exception as e:
            raise ConfigError(f"Error saving program conf file: {str(e)}")

        """
            if (
                self._config_data_last
                or (self._config_data_last != self._toml_data)
                and not save_path
            ):
                if not save_path and self.program_conf.current_config:
                    save_path = self.USER_CONFIG_DIR / str(
                        self.program_conf.current_config + ".toml"
                    )

                if not save_path:
                    raise ConfigError("Failed to determine save path")

                with open(save_path, "w") as toml_file:
                    self._config_data_last = self._toml_data
                    toml_file.write(tomlkit.dumps(self._toml_data))        
        """

    def load_config(self, config_file: str | None = None):
        """Loads config file, if missing automatically creates one from the example template."""
        if config_file:
            config_path = config_path = self.USER_CONFIG_DIR / str(
                config_file + ".toml"
            )
        else:
            if not self.program_conf.current_config:
                raise ConfigError("Failure to load current config")
            config_path = self.USER_CONFIG_DIR / str(
                self.program_conf.current_config + ".toml"
            )

        if config_path.exists():
            with open(config_path, "r") as toml_file:
                self._toml_data = self.check_toml_updates(
                    tomlkit.parse(toml_file.read()),
                    tomlkit.parse(self.CONFIG_DEFAULT.read_text()),
                )
                self._config_data_last = self._toml_data
                self.update_config_payload(self._toml_data)
            self.save_config(config_path)
        else:
            config_path.parent.mkdir(exist_ok=True, parents=True)
            with open(config_path, "w") as toml_file:
                toml_file.write(self.CONFIG_DEFAULT.read_text())
            self.load_config()

    def check_toml_updates(
        self, base_toml: tomlkit.items.Table, new_toml: tomlkit.items.Table
    ) -> tomlkit.items.Table:
        """Recursively updates base_toml with key-value pairs from new_toml"""
        for key, value in new_toml.items():
            if key not in base_toml:
                base_toml[key] = value
            elif isinstance(value, tomlkit.items.Table):
                if not isinstance(base_toml.get(key), tomlkit.items.Table):
                    base_toml[key] = value
                else:
                    self.check_toml_updates(base_toml[key], value)
            else:
                # If the key exists and is not a table, leave the base_toml's value unchanged.
                continue
        return base_toml

    def save_config(self, save_path: Path | None = None) -> None:
        """Converts config payload object to TOML and writes to a file"""
        try:
            # update program conf
            self.save_program_conf()

            # Update the toml object
            # general
            general_data = self._toml_data["general"]
            general_data["ui_suffix"] = self.cfg_payload.ui_suffix
            general_data["nfo_forge_theme"] = NfoForgeTheme(
                self.cfg_payload.nfo_forge_theme
            ).value
            general_data["profile"] = Profile(self.cfg_payload.profile).value
            general_data["media_mode"] = MediaMode(self.cfg_payload.media_mode).value
            general_data["source_media_ext_filter"] = (
                self.cfg_payload.source_media_ext_filter
            )
            general_data["encode_media_ext_filter"] = (
                self.cfg_payload.encode_media_ext_filter
            )
            general_data["media_input_dir"] = self.cfg_payload.media_input_dir
            general_data["releasers_name"] = self.cfg_payload.releasers_name
            general_data["timeout"] = self.cfg_payload.timeout
            general_data["log_level"] = LogLevel(self.cfg_payload.log_level).value
            general_data["log_total"] = self.cfg_payload.log_total

            # dependencies
            dependencies_data = self._toml_data["dependencies"]
            dependencies_data["ffmpeg"] = self.resolve_dependency(
                self.cfg_payload.ffmpeg
            )
            dependencies_data["frame_forge"] = self.resolve_dependency(
                self.cfg_payload.frame_forge
            )

            # api keys
            api_keys_data = self._toml_data["api_keys"]
            api_keys_data["tmdb_api_key"] = self.cfg_payload.tmdb_api_key
            api_keys_data["tvdb_api_key"] = self.cfg_payload.tvdb_api_key

            # trackers
            tracker_data = self._toml_data["tracker"]

            # tracker settings
            tracker_settings = tracker_data["settings"]
            tracker_settings["tracker_order"] = [
                str(x) for x in self.cfg_payload.tracker_order
            ]

            # more_than_tv tracker
            if "more_than_tv" not in tracker_data:
                tracker_data["more_than_tv"] = tomlkit.table()
            mtv_data = tracker_data["more_than_tv"]
            mtv_data["upload_enabled"] = self.cfg_payload.mtv_tracker.upload_enabled
            mtv_data["announce_url"] = self.cfg_payload.mtv_tracker.announce_url
            mtv_data["enabled"] = self.cfg_payload.mtv_tracker.enabled
            mtv_data["source"] = self.cfg_payload.mtv_tracker.source
            mtv_data["comments"] = self.cfg_payload.mtv_tracker.comments
            mtv_data["nfo_template"] = self.cfg_payload.mtv_tracker.nfo_template
            mtv_data["max_piece_size"] = self.cfg_payload.mtv_tracker.max_piece_size
            mtv_data["url_type"] = URLType(self.cfg_payload.mtv_tracker.url_type).value
            mtv_data["column_s"] = self.cfg_payload.mtv_tracker.column_s
            mtv_data["column_space"] = self.cfg_payload.mtv_tracker.column_space
            mtv_data["row_space"] = self.cfg_payload.mtv_tracker.row_space
            mtv_data["anonymous"] = self.cfg_payload.mtv_tracker.anonymous
            mtv_data["api_key"] = self.cfg_payload.mtv_tracker.api_key
            mtv_data["username"] = self.cfg_payload.mtv_tracker.username
            mtv_data["password"] = self.cfg_payload.mtv_tracker.password
            mtv_data["totp"] = self.cfg_payload.mtv_tracker.totp
            mtv_data["group_description"] = (
                self.cfg_payload.mtv_tracker.group_description
            )
            mtv_data["additional_tags"] = self.cfg_payload.mtv_tracker.additional_tags
            mtv_data["source_origin"] = MTVSourceOrigin(
                self.cfg_payload.mtv_tracker.source_origin
            ).value
            mtv_data["image_width"] = self.cfg_payload.mtv_tracker.image_width

            # torrent_leech tracker
            if "torrent_leech" not in tracker_data:
                tracker_data["torrent_leech"] = tomlkit.table()
            tl_data = tracker_data["torrent_leech"]
            tl_data["upload_enabled"] = self.cfg_payload.tl_tracker.upload_enabled
            tl_data["announce_url"] = self.cfg_payload.tl_tracker.announce_url
            tl_data["enabled"] = self.cfg_payload.tl_tracker.enabled
            tl_data["source"] = self.cfg_payload.tl_tracker.source
            tl_data["comments"] = self.cfg_payload.tl_tracker.comments
            tl_data["nfo_template"] = self.cfg_payload.tl_tracker.nfo_template
            tl_data["max_piece_size"] = self.cfg_payload.tl_tracker.max_piece_size
            tl_data["url_type"] = URLType(self.cfg_payload.tl_tracker.url_type).value
            tl_data["column_s"] = self.cfg_payload.tl_tracker.column_s
            tl_data["column_space"] = self.cfg_payload.tl_tracker.column_space
            tl_data["row_space"] = self.cfg_payload.tl_tracker.row_space
            tl_data["username"] = self.cfg_payload.tl_tracker.username
            tl_data["password"] = self.cfg_payload.tl_tracker.password
            tl_data["torrent_passkey"] = self.cfg_payload.tl_tracker.torrent_passkey
            tl_data["alt_2_fa_token"] = self.cfg_payload.tl_tracker.alt_2_fa_token

            # BeyondHD tracker
            if "beyond_hd" not in tracker_data:
                tracker_data["beyond_hd"] = tomlkit.table()
            bhd_data = tracker_data["beyond_hd"]
            bhd_data["upload_enabled"] = self.cfg_payload.bhd_tracker.upload_enabled
            bhd_data["announce_url"] = self.cfg_payload.bhd_tracker.announce_url
            bhd_data["enabled"] = self.cfg_payload.bhd_tracker.enabled
            bhd_data["source"] = self.cfg_payload.bhd_tracker.source
            bhd_data["comments"] = self.cfg_payload.bhd_tracker.comments
            bhd_data["nfo_template"] = self.cfg_payload.bhd_tracker.nfo_template
            bhd_data["max_piece_size"] = self.cfg_payload.bhd_tracker.max_piece_size
            bhd_data["url_type"] = URLType(self.cfg_payload.bhd_tracker.url_type).value
            bhd_data["column_s"] = self.cfg_payload.bhd_tracker.column_s
            bhd_data["column_space"] = self.cfg_payload.bhd_tracker.column_space
            bhd_data["row_space"] = self.cfg_payload.bhd_tracker.row_space
            bhd_data["anonymous"] = self.cfg_payload.bhd_tracker.anonymous
            bhd_data["api_key"] = self.cfg_payload.bhd_tracker.api_key
            bhd_data["rss_key"] = self.cfg_payload.bhd_tracker.rss_key
            bhd_data["promo"] = BHDPromo(self.cfg_payload.bhd_tracker.promo).value
            bhd_data["live_release"] = BHDLiveRelease(
                self.cfg_payload.bhd_tracker.live_release
            ).value
            bhd_data["internal"] = self.cfg_payload.bhd_tracker.internal
            bhd_data["image_width"] = self.cfg_payload.bhd_tracker.image_width

            # PassThePopcorn tracker
            if "pass_the_popcorn" not in tracker_data:
                tracker_data["pass_the_popcorn"] = tomlkit.table()
            ptp_data = tracker_data["pass_the_popcorn"]
            ptp_data["upload_enabled"] = self.cfg_payload.ptp_tracker.upload_enabled
            ptp_data["announce_url"] = self.cfg_payload.ptp_tracker.announce_url
            ptp_data["enabled"] = self.cfg_payload.ptp_tracker.enabled
            ptp_data["source"] = self.cfg_payload.ptp_tracker.source
            ptp_data["comments"] = self.cfg_payload.ptp_tracker.comments
            ptp_data["nfo_template"] = self.cfg_payload.ptp_tracker.nfo_template
            ptp_data["max_piece_size"] = self.cfg_payload.ptp_tracker.max_piece_size
            ptp_data["url_type"] = URLType(self.cfg_payload.ptp_tracker.url_type).value
            ptp_data["column_s"] = self.cfg_payload.ptp_tracker.column_s
            ptp_data["column_space"] = self.cfg_payload.ptp_tracker.column_space
            ptp_data["row_space"] = self.cfg_payload.ptp_tracker.row_space
            ptp_data["api_user"] = self.cfg_payload.ptp_tracker.api_user
            ptp_data["api_key"] = self.cfg_payload.ptp_tracker.api_key
            ptp_data["username"] = self.cfg_payload.ptp_tracker.username
            ptp_data["password"] = self.cfg_payload.ptp_tracker.password
            ptp_data["totp"] = self.cfg_payload.ptp_tracker.totp

            # ReelFliX tracker
            if "reelflix" not in tracker_data:
                tracker_data["reelflix"] = tomlkit.table()
            rf_data = tracker_data["reelflix"]
            rf_data["upload_enabled"] = self.cfg_payload.rf_tracker.upload_enabled
            rf_data["announce_url"] = self.cfg_payload.rf_tracker.announce_url
            rf_data["enabled"] = self.cfg_payload.rf_tracker.enabled
            rf_data["source"] = self.cfg_payload.rf_tracker.source
            rf_data["comments"] = self.cfg_payload.rf_tracker.comments
            rf_data["nfo_template"] = self.cfg_payload.rf_tracker.nfo_template
            rf_data["max_piece_size"] = self.cfg_payload.rf_tracker.max_piece_size
            rf_data["url_type"] = URLType(self.cfg_payload.rf_tracker.url_type).value
            rf_data["column_s"] = self.cfg_payload.rf_tracker.column_s
            rf_data["column_space"] = self.cfg_payload.rf_tracker.column_space
            rf_data["row_space"] = self.cfg_payload.rf_tracker.row_space
            rf_data["api_key"] = self.cfg_payload.rf_tracker.api_key
            rf_data["anonymous"] = self.cfg_payload.rf_tracker.anonymous
            rf_data["internal"] = self.cfg_payload.rf_tracker.internal
            rf_data["personal_release"] = self.cfg_payload.rf_tracker.personal_release
            rf_data["stream_optimized"] = self.cfg_payload.rf_tracker.stream_optimized
            rf_data["opt_in_to_mod_queue"] = (
                self.cfg_payload.rf_tracker.opt_in_to_mod_queue
            )
            rf_data["featured"] = self.cfg_payload.rf_tracker.featured
            rf_data["free"] = self.cfg_payload.rf_tracker.free
            rf_data["double_up"] = self.cfg_payload.rf_tracker.double_up
            rf_data["sticky"] = self.cfg_payload.rf_tracker.sticky
            rf_data["image_width"] = self.cfg_payload.rf_tracker.image_width

            # Aither tracker
            if "aither" not in tracker_data:
                tracker_data["aither"] = tomlkit.table()
            aither_data = tracker_data["aither"]
            aither_data["upload_enabled"] = (
                self.cfg_payload.aither_tracker.upload_enabled
            )
            aither_data["announce_url"] = self.cfg_payload.aither_tracker.announce_url
            aither_data["enabled"] = self.cfg_payload.aither_tracker.enabled
            aither_data["source"] = self.cfg_payload.aither_tracker.source
            aither_data["comments"] = self.cfg_payload.aither_tracker.comments
            aither_data["nfo_template"] = self.cfg_payload.aither_tracker.nfo_template
            aither_data["max_piece_size"] = (
                self.cfg_payload.aither_tracker.max_piece_size
            )
            aither_data["url_type"] = URLType(
                self.cfg_payload.aither_tracker.url_type
            ).value
            aither_data["column_s"] = self.cfg_payload.aither_tracker.column_s
            aither_data["column_space"] = self.cfg_payload.aither_tracker.column_space
            aither_data["row_space"] = self.cfg_payload.aither_tracker.row_space
            aither_data["api_key"] = self.cfg_payload.aither_tracker.api_key
            aither_data["anonymous"] = self.cfg_payload.aither_tracker.anonymous
            aither_data["internal"] = self.cfg_payload.aither_tracker.internal
            aither_data["personal_release"] = (
                self.cfg_payload.aither_tracker.personal_release
            )
            aither_data["stream_optimized"] = (
                self.cfg_payload.aither_tracker.stream_optimized
            )
            aither_data["opt_in_to_mod_queue"] = (
                self.cfg_payload.aither_tracker.opt_in_to_mod_queue
            )
            aither_data["featured"] = self.cfg_payload.aither_tracker.featured
            aither_data["free"] = self.cfg_payload.aither_tracker.free
            aither_data["double_up"] = self.cfg_payload.aither_tracker.double_up
            aither_data["sticky"] = self.cfg_payload.aither_tracker.sticky
            aither_data["image_width"] = self.cfg_payload.aither_tracker.image_width

            # torrent client
            torrent_client_data = self._toml_data["torrent_client"]

            # qbittorrent
            if "qbittorrent" not in torrent_client_data:
                qbittorrent_data = tomlkit.table()
            qbittorrent_data = torrent_client_data["qbittorrent"]
            qbittorrent_data["enabled"] = self.cfg_payload.qbittorrent.enabled
            qbittorrent_data["host"] = self.cfg_payload.qbittorrent.host
            qbittorrent_data["port"] = self.cfg_payload.qbittorrent.port
            qbittorrent_data["user"] = self.cfg_payload.qbittorrent.user
            qbittorrent_data["password"] = self.cfg_payload.qbittorrent.password
            qbittorrent_data["specific_params"] = (
                self.cfg_payload.qbittorrent.specific_params
            )

            # deluge
            if "deluge" not in torrent_client_data:
                deluge_data = tomlkit.table()
            deluge_data = torrent_client_data["deluge"]
            deluge_data["enabled"] = self.cfg_payload.deluge.enabled
            deluge_data["host"] = self.cfg_payload.deluge.host
            deluge_data["port"] = self.cfg_payload.deluge.port
            deluge_data["user"] = self.cfg_payload.deluge.user
            deluge_data["password"] = self.cfg_payload.deluge.password
            deluge_data["specific_params"] = self.cfg_payload.deluge.specific_params

            # rtorrent
            if "rtorrent" not in torrent_client_data:
                rtorrent_data = tomlkit.table()
            rtorrent_data = torrent_client_data["rtorrent"]
            rtorrent_data["enabled"] = self.cfg_payload.rtorrent.enabled
            rtorrent_data["host"] = self.cfg_payload.rtorrent.host
            rtorrent_data["port"] = self.cfg_payload.rtorrent.port
            rtorrent_data["user"] = self.cfg_payload.rtorrent.user
            rtorrent_data["password"] = self.cfg_payload.rtorrent.password
            rtorrent_data["specific_params"] = self.cfg_payload.rtorrent.specific_params

            # transmission
            if "transmission" not in torrent_client_data:
                transmission_data = tomlkit.table()
            transmission_data = torrent_client_data["transmission"]
            transmission_data["enabled"] = self.cfg_payload.transmission.enabled
            transmission_data["host"] = self.cfg_payload.transmission.host
            transmission_data["port"] = self.cfg_payload.transmission.port
            transmission_data["user"] = self.cfg_payload.transmission.user
            transmission_data["password"] = self.cfg_payload.transmission.password
            transmission_data["specific_params"] = (
                self.cfg_payload.transmission.specific_params
            )

            # watch folder
            if "watch_folder" not in self._toml_data:
                watch_folder_data = tomlkit.table()
            watch_folder_data = self._toml_data["watch_folder"]
            watch_folder_data["enabled"] = self.cfg_payload.watch_folder.enabled
            watch_folder_data["path"] = (
                str(self.cfg_payload.watch_folder.path)
                if self.cfg_payload.watch_folder.path
                else ""
            )

            # movie rename
            movie_rename = self._toml_data["movie_rename"]
            movie_rename["mvr_enabled"] = self.cfg_payload.mvr_enabled
            movie_rename["mvr_replace_illegal_chars"] = (
                self.cfg_payload.mvr_replace_illegal_chars
            )
            movie_rename["mvr_parse_with_media_info"] = (
                self.cfg_payload.mvr_parse_with_media_info
            )
            movie_rename["mvr_colon_replacement"] = ColonReplace(
                self.cfg_payload.mvr_colon_replacement
            ).value
            movie_rename["mvr_token"] = self.cfg_payload.mvr_token
            movie_rename["mvr_clean_title_rules"] = (
                self.cfg_payload.mvr_clean_title_rules
            )
            movie_rename["mvr_clean_title_rules_modified"] = (
                self.cfg_payload.mvr_clean_title_rules_modified
            )
            movie_rename["mvr_release_group"] = self.cfg_payload.mvr_release_group

            # screenshots
            screen_shot_data = self._toml_data["screenshots"]
            screen_shot_data["crop_mode"] = Cropping(self.cfg_payload.crop_mode).value
            screen_shot_data["screenshots_enabled"] = (
                self.cfg_payload.screenshots_enabled
            )
            screen_shot_data["screen_shot_count"] = self.cfg_payload.screen_shot_count
            screen_shot_data["required_selected_screens"] = (
                self.cfg_payload.required_selected_screens
            )
            screen_shot_data["ss_mode"] = ScreenShotMode(self.cfg_payload.ss_mode).value
            screen_shot_data["sub_size_height_720"] = (
                self.cfg_payload.sub_size_height_720
            )
            screen_shot_data["sub_size_height_1080"] = (
                self.cfg_payload.sub_size_height_1080
            )
            screen_shot_data["sub_size_height_2160"] = (
                self.cfg_payload.sub_size_height_2160
            )
            screen_shot_data["subtitle_alignment"] = SubtitleAlignment(
                self.cfg_payload.subtitle_alignment
            ).value
            screen_shot_data["subtitle_color"] = self.cfg_payload.subtitle_color
            screen_shot_data["trim_start"] = self.cfg_payload.trim_start
            screen_shot_data["trim_end"] = self.cfg_payload.trim_end
            screen_shot_data["comparison_subtitles"] = (
                self.cfg_payload.comparison_subtitles
            )
            screen_shot_data["comparison_subtitle_source_name"] = (
                self.cfg_payload.comparison_subtitle_source_name
            )
            screen_shot_data["comparison_subtitle_encode_name"] = (
                self.cfg_payload.comparison_subtitle_encode_name
            )
            screen_shot_data["compress_images"] = self.cfg_payload.compress_images
            screen_shot_data["optimize_dl_url_images"] = (
                self.cfg_payload.optimize_dl_url_images
            )
            screen_shot_data["optimize_dl_url_images_percentage"] = (
                self.cfg_payload.optimize_dl_url_images_percentage
            )
            screen_shot_data["indexer"] = Indexer(self.cfg_payload.indexer).value
            screen_shot_data["image_plugin"] = ImagePlugin(
                self.cfg_payload.image_plugin
            ).value

            # image hosts
            image_hosts = self._toml_data["image_hosts"]

            # chevereto_v3
            if "chevereto_v3" not in image_hosts:
                chevereto_v3_data = tomlkit.table()
            chevereto_v3_data = image_hosts["chevereto_v3"]
            chevereto_v3_data["enabled"] = self.cfg_payload.chevereto_v3.enabled
            chevereto_v3_data["base_url"] = self.cfg_payload.chevereto_v3.base_url
            chevereto_v3_data["user"] = self.cfg_payload.chevereto_v3.user
            chevereto_v3_data["password"] = self.cfg_payload.chevereto_v3.password

            # chevereto_v4
            if "chevereto_v4" not in image_hosts:
                chevereto_v4_data = tomlkit.table()
            chevereto_v4_data = image_hosts["chevereto_v4"]
            chevereto_v4_data["enabled"] = self.cfg_payload.chevereto_v4.enabled
            chevereto_v4_data["base_url"] = self.cfg_payload.chevereto_v4.base_url
            chevereto_v4_data["api_key"] = self.cfg_payload.chevereto_v4.api_key

            # image bb
            if "image_bb" not in image_hosts:
                img_bb_data = tomlkit.table()
            img_bb_data = image_hosts["image_bb"]
            img_bb_data["enabled"] = self.cfg_payload.image_bb.enabled
            img_bb_data["base_url"] = self.cfg_payload.image_bb.base_url
            img_bb_data["api_key"] = self.cfg_payload.image_bb.api_key

            # image box
            if "image_box" not in image_hosts:
                img_box_data = tomlkit.table()
            img_box_data = image_hosts["image_box"]
            img_box_data["enabled"] = self.cfg_payload.image_box.enabled
            img_box_data["base_url"] = self.cfg_payload.image_box.base_url

            # ptpimg
            if "ptpimg" not in image_hosts:
                ptpimg_data = tomlkit.table()
            ptpimg_data = image_hosts["ptpimg"]
            ptpimg_data["enabled"] = self.cfg_payload.ptpimg.enabled
            ptpimg_data["base_url"] = self.cfg_payload.ptpimg.base_url
            ptpimg_data["api_key"] = self.cfg_payload.ptpimg.api_key

            # urls
            urls_settings = self._toml_data["urls"]
            urls_settings["alt"] = self.cfg_payload.urls_alt
            urls_settings["columns"] = self.cfg_payload.urls_columns
            urls_settings["vertical"] = self.cfg_payload.urls_vertical
            urls_settings["horizontal"] = self.cfg_payload.urls_horizontal
            urls_settings["mode"] = self.cfg_payload.urls_mode
            urls_settings["type"] = URLType(self.cfg_payload.urls_type).value
            urls_settings["image_width"] = self.cfg_payload.urls_image_width
            urls_settings["urls_manual"] = self.cfg_payload.urls_manual

            # plugins
            plugins_settings = self._toml_data["plugins"]
            plugins_settings["wizard_page"] = (
                self.cfg_payload.wizard_page if self.cfg_payload.wizard_page else ""
            )
            plugins_settings["token_replacer"] = (
                self.cfg_payload.token_replacer
                if self.cfg_payload.token_replacer
                else ""
            )
            plugins_settings["pre_upload"] = (
                self.cfg_payload.pre_upload if self.cfg_payload.pre_upload else ""
            )

            # template settings
            template_settings = self._toml_data["template_settings"]
            template_settings["block_start_string"] = (
                self.cfg_payload.block_start_string
            )
            template_settings["block_syntax_color"] = (
                self.cfg_payload.block_syntax_color
            )
            template_settings["block_end_string"] = self.cfg_payload.block_end_string
            template_settings["variable_start_string"] = (
                self.cfg_payload.variable_start_string
            )
            template_settings["variable_end_string"] = (
                self.cfg_payload.variable_end_string
            )
            template_settings["variable_syntax_color"] = (
                self.cfg_payload.variable_syntax_color
            )
            template_settings["comment_start_string"] = (
                self.cfg_payload.comment_start_string
            )
            template_settings["comment_end_string"] = (
                self.cfg_payload.comment_end_string
            )
            template_settings["comment_syntax_color"] = (
                self.cfg_payload.comment_syntax_color
            )
            template_settings["line_statement_prefix"] = (
                self.cfg_payload.line_statement_prefix
            )
            template_settings["line_statement_syntax_color"] = (
                self.cfg_payload.line_statement_syntax_color
            )
            template_settings["line_comment_prefix"] = (
                self.cfg_payload.line_comment_prefix
            )
            template_settings["line_comment_syntax_color"] = (
                self.cfg_payload.line_comment_syntax_color
            )
            template_settings["trim_blocks"] = int(self.cfg_payload.trim_blocks)
            template_settings["lstrip_blocks"] = int(self.cfg_payload.lstrip_blocks)
            template_settings["newline_sequence"] = self.cfg_payload.newline_sequence
            template_settings["keep_trailing_newline"] = int(
                self.cfg_payload.keep_trailing_newline
            )

            # if last data does not equal current data, we'll write the changes to file while also updating
            # the last data variable with the latest data
            if (
                self._config_data_last
                or (self._config_data_last != self._toml_data)
                and not save_path
            ):
                if not save_path and self.program_conf.current_config:
                    save_path = self.USER_CONFIG_DIR / str(
                        self.program_conf.current_config + ".toml"
                    )

                if not save_path:
                    raise ConfigError("Failed to determine save path")

                with open(save_path, "w") as toml_file:
                    self._config_data_last = self._toml_data
                    toml_file.write(tomlkit.dumps(self._toml_data))

        except Exception as e:
            raise ConfigError(f"Error saving config file: {str(e)}")

    def update_config_payload(self, toml_data: TOMLDocument) -> None:
        """Assigns config payload attributes from a given toml document"""
        try:
            # general
            general_data = toml_data["general"]
            nfo_forge_theme = NfoForgeTheme(general_data.get("nfo_forge_theme", 1))
            profile = Profile(general_data.get("profile", 1))
            media_mode = MediaMode(general_data.get("media_mode", 1))

            # dependencies
            dependencies_data = toml_data["dependencies"]
            ffmpeg = (
                Path(dependencies_data["ffmpeg"])
                if dependencies_data["ffmpeg"]
                else None
            )
            frame_forge = (
                Path(dependencies_data["frame_forge"])
                if dependencies_data["frame_forge"]
                else None
            )

            # api keys
            api_keys_data = toml_data["api_keys"]

            # trackers
            tracker_data = toml_data["tracker"]

            # tracker settings
            tracker_settings = tracker_data["settings"]

            # tracker order
            tracker_order = [
                TrackerSelection(x)
                for x in tracker_settings.get("tracker_order", [])
                if x in TrackerSelection._value2member_map_
            ]
            tracker_order.extend(e for e in TrackerSelection if e not in tracker_order)

            # tracker data
            mtv_tracker_data = tracker_data["more_than_tv"]
            mtv_tracker = MoreThanTVInfo(
                upload_enabled=mtv_tracker_data["upload_enabled"],
                announce_url=mtv_tracker_data["announce_url"],
                enabled=mtv_tracker_data["enabled"],
                source=mtv_tracker_data["source"],
                comments=mtv_tracker_data["comments"],
                nfo_template=mtv_tracker_data["nfo_template"],
                max_piece_size=mtv_tracker_data["max_piece_size"],
                url_type=URLType(mtv_tracker_data["url_type"]),
                column_s=mtv_tracker_data["column_s"],
                column_space=mtv_tracker_data["column_space"],
                row_space=mtv_tracker_data["row_space"],
                anonymous=mtv_tracker_data["anonymous"],
                api_key=mtv_tracker_data["api_key"],
                username=mtv_tracker_data["username"],
                password=mtv_tracker_data["password"],
                totp=mtv_tracker_data["totp"],
                group_description=mtv_tracker_data["group_description"],
                additional_tags=mtv_tracker_data["additional_tags"],
                source_origin=MTVSourceOrigin(mtv_tracker_data["source_origin"]),
                image_width=mtv_tracker_data["image_width"],
            )

            tl_tracker_data = tracker_data["torrent_leech"]
            tl_tracker = TorrentLeechInfo(
                upload_enabled=tl_tracker_data["upload_enabled"],
                announce_url=tl_tracker_data["announce_url"],
                enabled=tl_tracker_data["enabled"],
                source=tl_tracker_data["source"],
                comments=tl_tracker_data["comments"],
                nfo_template=tl_tracker_data["nfo_template"],
                max_piece_size=tl_tracker_data["max_piece_size"],
                url_type=URLType(tl_tracker_data["url_type"]),
                column_s=tl_tracker_data["column_s"],
                column_space=tl_tracker_data["column_space"],
                row_space=tl_tracker_data["row_space"],
                username=tl_tracker_data["username"],
                password=tl_tracker_data["password"],
                torrent_passkey=tl_tracker_data["torrent_passkey"],
                alt_2_fa_token=tl_tracker_data["alt_2_fa_token"],
            )

            bhd_tracker_data = tracker_data["beyond_hd"]
            bhd_tracker = BeyondHDInfo(
                upload_enabled=bhd_tracker_data["upload_enabled"],
                announce_url=bhd_tracker_data["announce_url"],
                enabled=bhd_tracker_data["enabled"],
                source=bhd_tracker_data["source"],
                comments=bhd_tracker_data["comments"],
                nfo_template=bhd_tracker_data["nfo_template"],
                max_piece_size=bhd_tracker_data["max_piece_size"],
                url_type=URLType(bhd_tracker_data["url_type"]),
                column_s=bhd_tracker_data["column_s"],
                column_space=bhd_tracker_data["column_space"],
                row_space=bhd_tracker_data["row_space"],
                anonymous=bhd_tracker_data["anonymous"],
                api_key=bhd_tracker_data["api_key"],
                rss_key=bhd_tracker_data["rss_key"],
                promo=BHDPromo(bhd_tracker_data["promo"]),
                live_release=BHDLiveRelease(bhd_tracker_data["live_release"]),
                internal=bhd_tracker_data["internal"],
                image_width=bhd_tracker_data["image_width"],
            )

            ptp_tracker_data = tracker_data["pass_the_popcorn"]
            ptp_tracker = PassThePopcornInfo(
                upload_enabled=ptp_tracker_data["upload_enabled"],
                announce_url=ptp_tracker_data["announce_url"],
                enabled=ptp_tracker_data["enabled"],
                source=ptp_tracker_data["source"],
                comments=ptp_tracker_data["comments"],
                nfo_template=ptp_tracker_data["nfo_template"],
                max_piece_size=ptp_tracker_data["max_piece_size"],
                url_type=URLType(ptp_tracker_data["url_type"]),
                column_s=ptp_tracker_data["column_s"],
                column_space=ptp_tracker_data["column_space"],
                row_space=ptp_tracker_data["row_space"],
                api_user=ptp_tracker_data["api_user"],
                api_key=ptp_tracker_data["api_key"],
                username=ptp_tracker_data["username"],
                password=ptp_tracker_data["password"],
                totp=ptp_tracker_data["totp"],
            )

            rf_tracker_data = tracker_data["reelflix"]
            rf_tracker = ReelFlixInfo(
                upload_enabled=rf_tracker_data["upload_enabled"],
                announce_url=rf_tracker_data["announce_url"],
                enabled=rf_tracker_data["enabled"],
                source=rf_tracker_data["source"],
                comments=rf_tracker_data["comments"],
                nfo_template=rf_tracker_data["nfo_template"],
                max_piece_size=rf_tracker_data["max_piece_size"],
                url_type=URLType(rf_tracker_data["url_type"]),
                column_s=rf_tracker_data["column_s"],
                column_space=rf_tracker_data["column_space"],
                row_space=rf_tracker_data["row_space"],
                api_key=rf_tracker_data["api_key"],
                anonymous=rf_tracker_data["anonymous"],
                internal=rf_tracker_data["internal"],
                personal_release=rf_tracker_data["personal_release"],
                stream_optimized=rf_tracker_data["stream_optimized"],
                opt_in_to_mod_queue=rf_tracker_data["opt_in_to_mod_queue"],
                featured=rf_tracker_data["featured"],
                free=rf_tracker_data["free"],
                double_up=rf_tracker_data["double_up"],
                sticky=rf_tracker_data["sticky"],
                image_width=rf_tracker_data["image_width"],
            )

            aither_tracker_data = tracker_data["aither"]
            aither_tracker = AitherInfo(
                upload_enabled=aither_tracker_data["upload_enabled"],
                announce_url=aither_tracker_data["announce_url"],
                enabled=aither_tracker_data["enabled"],
                source=aither_tracker_data["source"],
                comments=aither_tracker_data["comments"],
                nfo_template=aither_tracker_data["nfo_template"],
                max_piece_size=aither_tracker_data["max_piece_size"],
                url_type=URLType(aither_tracker_data["url_type"]),
                column_s=aither_tracker_data["column_s"],
                column_space=aither_tracker_data["column_space"],
                row_space=aither_tracker_data["row_space"],
                api_key=aither_tracker_data["api_key"],
                anonymous=aither_tracker_data["anonymous"],
                internal=aither_tracker_data["internal"],
                personal_release=aither_tracker_data["personal_release"],
                stream_optimized=aither_tracker_data["stream_optimized"],
                opt_in_to_mod_queue=aither_tracker_data["opt_in_to_mod_queue"],
                featured=aither_tracker_data["featured"],
                free=aither_tracker_data["free"],
                double_up=aither_tracker_data["double_up"],
                sticky=aither_tracker_data["sticky"],
                image_width=aither_tracker_data["image_width"],
            )

            # torrent clients
            torrent_client_data = toml_data["torrent_client"]

            # qbittorrent
            qbittorrent = TorrentClient(**torrent_client_data["qbittorrent"])
            for qbit_specific in self.QBIT_SPECIFIC:
                if not qbittorrent.specific_params.get(qbit_specific):
                    qbittorrent.specific_params[qbit_specific] = ""

            # deluge
            deluge = TorrentClient(**torrent_client_data["deluge"])
            for deluge_specific in self.DELUGE_SPECIFIC:
                if not deluge.specific_params.get(deluge_specific):
                    deluge.specific_params[deluge_specific] = ""

            # rtorrent
            rtorrent = TorrentClient(**torrent_client_data["rtorrent"])
            for rtorrent_specific in self.RTORRENT_SPECIFIC:
                if not rtorrent.specific_params.get(rtorrent_specific):
                    rtorrent.specific_params[rtorrent_specific] = ""

            # transmission
            transmission = TorrentClient(**torrent_client_data["transmission"])
            for transmission_specific in self.TRANSMISSION_SPECIFIC:
                if not transmission.specific_params.get(transmission_specific):
                    transmission.specific_params[transmission_specific] = ""

            # watch folder
            watch_folder = WatchFolder(**toml_data["watch_folder"])

            # movie rename
            movie_rename = toml_data["movie_rename"]

            # screenshots
            screen_shot_data = toml_data["screenshots"]

            # image hosts
            image_hosts = toml_data["image_hosts"]

            # hosts
            chevereto_v3 = CheveretoV3Payload(**image_hosts["chevereto_v3"])
            chevereto_v4 = CheveretoV4Payload(**image_hosts["chevereto_v4"])
            image_bb = ImageBBPayload(**image_hosts["image_bb"])
            image_box = ImageBoxPayload(**image_hosts["image_box"])
            ptpimg = PTPIMGPayload(**image_hosts["ptpimg"])

            # urls
            urls_settings = toml_data["urls"]

            # plugins
            plugins_settings = toml_data["plugins"]

            # template settings
            template_settings = toml_data["template_settings"]

            self.cfg_payload = ConfigPayload(
                ui_suffix=general_data.get("ui_suffix", ""),
                nfo_forge_theme=nfo_forge_theme,
                profile=profile,
                media_mode=media_mode,
                source_media_ext_filter=general_data.get(
                    "source_media_ext_filter", list(self.ACCEPTED_EXTENSIONS)
                ),
                encode_media_ext_filter=general_data.get(
                    "encode_media_ext_filter", list(self.ACCEPTED_EXTENSIONS)
                ),
                media_input_dir=general_data.get("media_input_dir"),
                releasers_name=general_data.get("releasers_name", ""),
                timeout=general_data.get("timeout", 60),
                log_level=LogLevel(general_data.get("log_level", 20)),
                log_total=general_data.get("log_total", 50),
                ffmpeg=ffmpeg,
                frame_forge=frame_forge,
                tmdb_api_key=api_keys_data.get("tmdb_api_key", ""),
                tvdb_api_key=api_keys_data.get("tvdb_api_key", ""),
                tracker_order=tracker_order,
                mtv_tracker=mtv_tracker,
                tl_tracker=tl_tracker,
                bhd_tracker=bhd_tracker,
                ptp_tracker=ptp_tracker,
                rf_tracker=rf_tracker,
                aither_tracker=aither_tracker,
                qbittorrent=qbittorrent,
                deluge=deluge,
                rtorrent=rtorrent,
                transmission=transmission,
                watch_folder=watch_folder,
                mvr_enabled=movie_rename.get("mvr_enabled", False),
                mvr_replace_illegal_chars=movie_rename.get(
                    "mvr_replace_illegal_chars", True
                ),
                mvr_parse_with_media_info=movie_rename.get(
                    "mvr_parse_with_media_info", True
                ),
                mvr_colon_replacement=ColonReplace(
                    movie_rename.get("mvr_colon_replacement", 2)
                ),
                mvr_clean_title_rules=movie_rename["mvr_clean_title_rules"],
                mvr_clean_title_rules_modified=movie_rename[
                    "mvr_clean_title_rules_modified"
                ],
                mvr_token=movie_rename.get(
                    "mvr_token",
                    (
                        "{movie_title} {release_year} {re_release} {source} "
                        "{resolution} {mi_audio_codec} {mi_audio_channel_s} "
                        "{mi_video_codec}{:opt=-:release_group}"
                    ),
                ),
                mvr_release_group=movie_rename.get("mvr_release_group", ""),
                crop_mode=Cropping(screen_shot_data.get("crop_mode", 2)),
                screenshots_enabled=screen_shot_data.get("screenshots_enabled", False),
                screen_shot_count=screen_shot_data.get("screen_shot_count", 20),
                required_selected_screens=screen_shot_data.get(
                    "required_selected_screens", 0
                ),
                ss_mode=ScreenShotMode(screen_shot_data.get("ss_mode", 1)),
                sub_size_height_720=screen_shot_data.get("sub_size_height_720", 12),
                sub_size_height_1080=screen_shot_data.get("sub_size_height_1080", 16),
                sub_size_height_2160=screen_shot_data.get("sub_size_height_2160", 32),
                subtitle_alignment=SubtitleAlignment(
                    screen_shot_data.get("subtitle_alignment", 7)
                ),
                subtitle_color=screen_shot_data.get("subtitle_color", "#f5c70a"),
                trim_start=screen_shot_data.get("trim_start", 20),
                trim_end=screen_shot_data.get("trim_end", 20),
                comparison_subtitles=screen_shot_data.get("comparison_subtitles", True),
                comparison_subtitle_source_name=screen_shot_data.get(
                    "comparison_subtitle_source_name", "Source"
                ),
                comparison_subtitle_encode_name=screen_shot_data.get(
                    "comparison_subtitle_encode_name", "Encode"
                ),
                compress_images=screen_shot_data.get("compress_images", True),
                optimize_dl_url_images=screen_shot_data.get(
                    "optimize_dl_url_images", True
                ),
                optimize_dl_url_images_percentage=screen_shot_data.get(
                    "optimize_dl_url_images_percentage", 0.25
                ),
                indexer=Indexer(screen_shot_data.get("indexer", 1)),
                image_plugin=ImagePlugin(screen_shot_data.get("image_plugin", 1)),
                chevereto_v3=chevereto_v3,
                chevereto_v4=chevereto_v4,
                image_bb=image_bb,
                image_box=image_box,
                ptpimg=ptpimg,
                urls_alt=urls_settings.get("alt", ""),
                urls_columns=urls_settings.get("columns", 1),
                urls_vertical=urls_settings.get("vertical", 1),
                urls_horizontal=urls_settings.get("horizontal", 1),
                urls_mode=urls_settings.get("mode", 0),
                urls_type=URLType(urls_settings.get("type", 1)),
                urls_image_width=urls_settings.get("image_width", 0),
                urls_manual=urls_settings.get("urls_manual", 0),
                wizard_page=plugins_settings.get("wizard_page"),
                token_replacer=plugins_settings.get("token_replacer"),
                pre_upload=plugins_settings.get("pre_upload"),
                block_start_string=template_settings.get("block_start_string", "{%"),
                block_syntax_color=template_settings.get(
                    "block_syntax_color", "#A4036F"
                ),
                block_end_string=template_settings.get("block_end_string", "%}"),
                variable_start_string=template_settings.get(
                    "variable_start_string", "{{"
                ),
                variable_end_string=template_settings.get("variable_end_string", "}}"),
                variable_syntax_color=template_settings.get(
                    "variable_syntax_color", "#048BA8"
                ),
                comment_start_string=template_settings.get(
                    "comment_start_string", "{#"
                ),
                comment_end_string=template_settings.get("comment_end_string", "#}"),
                comment_syntax_color=template_settings.get(
                    "comment_syntax_color", "#16DB93"
                ),
                line_statement_prefix=template_settings.get(
                    "line_statement_prefix", ""
                ),
                line_statement_syntax_color=template_settings.get(
                    "line_statement_syntax_color", "#ff0000"
                ),
                line_comment_prefix=template_settings.get("line_comment_prefix", ""),
                line_comment_syntax_color=template_settings.get(
                    "line_comment_syntax_color", "#00aaff"
                ),
                trim_blocks=bool(template_settings.get("trim_blocks", 1)),
                lstrip_blocks=bool(template_settings.get("lstrip_blocks", 1)),
                newline_sequence=template_settings.get("newline_sequence", "\\n"),
                keep_trailing_newline=bool(
                    template_settings.get("keep_trailing_newline", 0)
                ),
            )
        except Exception as e:
            raise ConfigError(f"Error parsing config file: {str(e)}")

    def _tracker_map(self) -> dict[TrackerSelection, TrackerInfo]:
        """
        As more trackers are added, this needs to be updated with each one. This is the default map
        that is ordered based on the saved config or the TrackerSelection enum class if no saved
        config exists.
        """
        return {
            TrackerSelection.MORE_THAN_TV: self.cfg_payload.mtv_tracker,
            TrackerSelection.TORRENT_LEECH: self.cfg_payload.tl_tracker,
            TrackerSelection.BEYOND_HD: self.cfg_payload.bhd_tracker,
            TrackerSelection.PASS_THE_POPCORN: self.cfg_payload.ptp_tracker,
            TrackerSelection.REELFLIX: self.cfg_payload.rf_tracker,
            TrackerSelection.AITHER: self.cfg_payload.aither_tracker,
        }

    def _client_map(self) -> dict[TorrentClientSelection, TorrentClient | WatchFolder]:
        """Map all of the torrent clients to their Enum for easy usage through out the program"""
        return {
            TorrentClientSelection.QBITTORRENT: self.cfg_payload.qbittorrent,
            TorrentClientSelection.DELUGE: self.cfg_payload.deluge,
            TorrentClientSelection.RTORRENT: self.cfg_payload.rtorrent,
            TorrentClientSelection.TRANSMISSION: self.cfg_payload.transmission,
            TorrentClientSelection.WATCH_FOLDER: self.cfg_payload.watch_folder,
        }

    def _image_host_map(
        self,
    ) -> dict[ImageHost, ImagePayloadBase]:
        """Map all of the image hosts to their enum/payloads for easy usage through out the program"""
        return {
            ImageHost.CHEVERETO_V3: self.cfg_payload.chevereto_v3,
            ImageHost.CHEVERETO_V4: self.cfg_payload.chevereto_v4,
            ImageHost.IMAGE_BB: self.cfg_payload.image_bb,
            ImageHost.IMAGE_BOX: self.cfg_payload.image_box,
            ImageHost.PTPIMG: self.cfg_payload.ptpimg,
        }

    def _init_dependencies(self) -> None:
        """Initialize dependencies and updates the config if needed"""
        FindDependencies().update_dependencies(self)

    def _jinja_env_settings(self) -> dict:
        env_settings = {
            "block_start_string": self.cfg_payload.block_start_string,
            "block_end_string": self.cfg_payload.block_end_string,
            "variable_start_string": self.cfg_payload.variable_start_string,
            "variable_end_string": self.cfg_payload.variable_end_string,
            "comment_start_string": self.cfg_payload.comment_start_string,
            "comment_end_string": self.cfg_payload.comment_end_string,
            "trim_blocks": self.cfg_payload.trim_blocks,
            "lstrip_blocks": self.cfg_payload.lstrip_blocks,
            "keep_trailing_newline": self.cfg_payload.keep_trailing_newline,
        }
        if self.cfg_payload.line_statement_prefix:
            env_settings["line_statement_prefix"] = (
                self.cfg_payload.line_statement_prefix
            )
        if self.cfg_payload.line_comment_prefix:
            env_settings["line_comment_prefix"] = self.cfg_payload.line_comment_prefix
        return env_settings

    @staticmethod
    def resolve_dependency(path_attr: Path | None) -> str:
        """Ensure that we're returning a toml safe string to save the paths"""
        if path_attr:
            return str(Path(path_attr))
        else:
            return ""

    # TODO: all these methods can be re activated when self.shared_data is needed IF they are needed
    # def set_shared_data(self, key, value):
    #     self.shared_data[key] = value

    # def get_shared_data(self, key):
    #     return self.shared_data.get(key)

    # # TODO: handle message box on FE
    # def save_config_data(self):
    # try:
    #     self.config.save_config()
    # except ConfigError as e:
    #     QMessageBox.critical(self, "Error", str(e))
