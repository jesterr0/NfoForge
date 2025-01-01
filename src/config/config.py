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
from src.enums.tracker_selection import TrackerSelection
from src.enums.token_replacer import ColonReplace
from src.enums.torrent_client import TorrentClientSelection
from src.enums.url_type import URLType
from src.enums.logging_settings import LogLevel
from src.payloads.config import ConfigPayload, ProgramConfigPayload
from src.payloads.shared_data import SharedPayload
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.trackers import TrackerInfo
from src.payloads.clients import TorrentClient
from src.payloads.watch_folder import WatchFolder
from src.payloads.image_hosts import (
    CheveretoV3Payload,
    CheveretoV4Payload,
    ImageBBPayload,
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

    MTV_SPECIFIC = (
        "textm__api_key",
        "textm__username",
        "textm__password",
        "textm__totp",
        "textm__group_desc",
        "textm__additional_tags",
        "enum__mtv__source_origin",
    )

    TL_SPECIFIC = (
        "textm__username",
        "textm__password",
        "textm__torrent_pass_key",
        "textm__alt_2_fa_token",
    )

    BHD_SPECIFIC = (
        "textm__api_key",
        "textm__rss_key",
        "enum__bhd__promo",
        "enum__bhd__live_release",
        "check__internal",
    )

    PTP_SPECIFIC = (
        "textm__api_user",
        "textm__api_key",
        "textm__username",
        "textm__password",
        "textm__totp",
        "textm__ptpimg_api_key",
        "check__reupload_images_to_ptpimg",
    )

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

    def __init__(self):
        # load various directories as needed
        self.TRACKER_COOKIE_PATH.mkdir(exist_ok=True, parents=True)

        # keep track of plugins
        self.loaded_plugins: dict[str, "PluginPayload"] = {}

        # load program config
        self.program_conf = ProgramConfigPayload()
        self._program_conf_toml_data = None
        self.load_program_conf()

        # variables we don't want to re-calculate in the methods, we'll define these before anything else
        self.default_tracker_order = [*range(len(TrackerSelection))]

        # variables that are assigned during init
        self.cfg_payload: ConfigPayload = None
        self._toml_data = None
        self.load_config()

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
        self.order_tracker_map()
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

    def load_program_conf(self) -> None:
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
                self._program_conf_data_last = self._program_conf_toml_data
                self.update_conf_payload()
            self.save_program_conf()
        else:
            with open(self.CONF_PATH, "w") as toml_file:
                toml_file.write(self.PROGRAM_CONF_DEFAULT.read_text())
            self.load_program_conf()

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

    def load_config(self, file_path: Path | None = None):
        """Loads config file, if missing automatically creates one from the example template."""
        if file_path:
            config_path = file_path
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
            self.save_config(file_path)
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
            general_data["image_host"] = ImageHost(self.cfg_payload.image_host).value
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

            # trackers
            tracker_data = self._toml_data["tracker"]

            # tracker settings
            tracker_settings = tracker_data["settings"]
            tracker_settings["order"] = self.cfg_payload.tracker_order

            # more_than_tv tracker
            if "more_than_tv" not in tracker_data:
                tracker_data["more_than_tv"] = tomlkit.table()
            mtv_data = tracker_data["more_than_tv"]
            mtv_data["upload_enabled"] = self.cfg_payload.mtv_tracker.upload_enabled
            mtv_data["anonymous"] = self.cfg_payload.mtv_tracker.anonymous
            mtv_data["announce_url"] = self.cfg_payload.mtv_tracker.announce_url
            mtv_data["enabled"] = self.cfg_payload.mtv_tracker.enabled
            mtv_data["source"] = self.cfg_payload.mtv_tracker.source
            mtv_data["comments"] = self.cfg_payload.mtv_tracker.comments
            mtv_data["nfo_template"] = self.cfg_payload.mtv_tracker.nfo_template
            mtv_data["max_piece_size"] = self.cfg_payload.mtv_tracker.max_piece_size
            mtv_data["specific_params"] = self.cfg_payload.mtv_tracker.specific_params

            # torrent_leech tracker
            if "torrent_leech" not in tracker_data:
                tracker_data["torrent_leech"] = tomlkit.table()
            tl_data = tracker_data["torrent_leech"]
            tl_data["upload_enabled"] = self.cfg_payload.tl_tracker.upload_enabled
            tl_data["anonymous"] = self.cfg_payload.tl_tracker.anonymous
            tl_data["announce_url"] = self.cfg_payload.tl_tracker.announce_url
            tl_data["enabled"] = self.cfg_payload.tl_tracker.enabled
            tl_data["source"] = self.cfg_payload.tl_tracker.source
            tl_data["comments"] = self.cfg_payload.tl_tracker.comments
            tl_data["nfo_template"] = self.cfg_payload.tl_tracker.nfo_template
            tl_data["max_piece_size"] = self.cfg_payload.tl_tracker.max_piece_size
            tl_data["specific_params"] = self.cfg_payload.tl_tracker.specific_params

            # BeyondHD tracker
            if "beyond_hd" not in tracker_data:
                tracker_data["beyond_hd"] = tomlkit.table()
            bhd_data = tracker_data["beyond_hd"]
            bhd_data["upload_enabled"] = self.cfg_payload.bhd_tracker.upload_enabled
            bhd_data["anonymous"] = self.cfg_payload.bhd_tracker.anonymous
            bhd_data["announce_url"] = self.cfg_payload.bhd_tracker.announce_url
            bhd_data["enabled"] = self.cfg_payload.bhd_tracker.enabled
            bhd_data["source"] = self.cfg_payload.bhd_tracker.source
            bhd_data["comments"] = self.cfg_payload.bhd_tracker.comments
            bhd_data["nfo_template"] = self.cfg_payload.bhd_tracker.nfo_template
            bhd_data["max_piece_size"] = self.cfg_payload.bhd_tracker.max_piece_size
            bhd_data["specific_params"] = self.cfg_payload.bhd_tracker.specific_params

            # PassThePopcorn tracker
            if "pass_the_popcorn" not in tracker_data:
                tracker_data["pass_the_popcorn"] = tomlkit.table()
            ptp_data = tracker_data["pass_the_popcorn"]
            ptp_data["upload_enabled"] = self.cfg_payload.ptp_tracker.upload_enabled
            ptp_data["anonymous"] = self.cfg_payload.ptp_tracker.anonymous
            ptp_data["announce_url"] = self.cfg_payload.ptp_tracker.announce_url
            ptp_data["enabled"] = self.cfg_payload.ptp_tracker.enabled
            ptp_data["source"] = self.cfg_payload.ptp_tracker.source
            ptp_data["comments"] = self.cfg_payload.ptp_tracker.comments
            ptp_data["nfo_template"] = self.cfg_payload.ptp_tracker.nfo_template
            ptp_data["max_piece_size"] = self.cfg_payload.ptp_tracker.max_piece_size
            ptp_data["specific_params"] = self.cfg_payload.ptp_tracker.specific_params

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
            watch_folder_data["path"] = str(self.cfg_payload.watch_folder.path)

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
            chevereto_v3_data["base_url"] = self.cfg_payload.chevereto_v3.base_url
            chevereto_v3_data["user"] = self.cfg_payload.chevereto_v3.user
            chevereto_v3_data["password"] = self.cfg_payload.chevereto_v3.password

            # chevereto_v4
            if "chevereto_v4" not in image_hosts:
                chevereto_v4_data = tomlkit.table()
            chevereto_v4_data = image_hosts["chevereto_v4"]
            chevereto_v4_data["base_url"] = self.cfg_payload.chevereto_v4.base_url
            chevereto_v4_data["api_key"] = self.cfg_payload.chevereto_v4.api_key

            # image bb
            if "image_bb" not in image_hosts:
                img_bb_data = tomlkit.table()
            img_bb_data = image_hosts["image_bb"]
            img_bb_data["api_key"] = self.cfg_payload.image_bb.api_key

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

            # updates of None or len of saved tracker order is less than newly added trackers.
            # TODO: this may need to be handled differently at some point, this will currently wipe out the users saved trackers
            # as we update new ones.
            tracker_order = tracker_settings.get("order")
            tracker_settings_order = tracker_order
            if not tracker_settings_order or (
                len(tracker_settings_order) < len(self.default_tracker_order)
            ):
                tracker_settings_order = self.default_tracker_order

            # trackers (sites)
            mtv_tracker = TrackerInfo(**tracker_data["more_than_tv"])
            for mtv_specific in self.MTV_SPECIFIC:
                if (
                    not mtv_tracker.specific_params.get(mtv_specific)
                    and mtv_tracker.specific_params.get(mtv_specific) != 0
                ):
                    mtv_tracker.specific_params[mtv_specific] = ""

            tl_tracker = TrackerInfo(**tracker_data["torrent_leech"])
            for tl_specific in self.TL_SPECIFIC:
                if (
                    not tl_tracker.specific_params.get(tl_specific)
                    and tl_tracker.specific_params.get(tl_specific) != 0
                ):
                    tl_tracker.specific_params[tl_specific] = ""

            bhd_tracker = TrackerInfo(**tracker_data["beyond_hd"])
            for bhd_specific in self.BHD_SPECIFIC:
                if (
                    not bhd_tracker.specific_params.get(bhd_specific)
                    and bhd_tracker.specific_params.get(bhd_specific) != 0
                ):
                    bhd_tracker.specific_params[bhd_specific] = ""

            ptp_tracker = TrackerInfo(**tracker_data["pass_the_popcorn"])
            for ptp_specific in self.PTP_SPECIFIC:
                if (
                    not ptp_tracker.specific_params.get(ptp_specific)
                    and ptp_tracker.specific_params.get(ptp_specific) != 0
                ):
                    ptp_tracker.specific_params[ptp_specific] = ""

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
            chevereto_v3 = CheveretoV3Payload(**image_hosts["chevereto_v3"])
            chevereto_v4 = CheveretoV4Payload(**image_hosts["chevereto_v4"])
            image_bb = ImageBBPayload(**image_hosts["image_bb"])

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
                image_host=ImageHost(general_data.get("image_host", 1)),
                timeout=general_data.get("timeout", 60),
                log_level=LogLevel(general_data.get("log_level", 20)),
                log_total=general_data.get("log_total", 50),
                ffmpeg=ffmpeg,
                frame_forge=frame_forge,
                tmdb_api_key=api_keys_data.get("tmdb_api_key", ""),
                tracker_order=tracker_settings_order,
                mtv_tracker=mtv_tracker,
                tl_tracker=tl_tracker,
                bhd_tracker=bhd_tracker,
                ptp_tracker=ptp_tracker,
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
                indexer=Indexer(screen_shot_data.get("indexer", 1)),
                image_plugin=ImagePlugin(screen_shot_data.get("image_plugin", 1)),
                chevereto_v3=chevereto_v3,
                chevereto_v4=chevereto_v4,
                image_bb=image_bb,
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
        }

    # TODO: call this from SETTINGS later
    def order_tracker_map(
        self, order: list[int] | None = None
    ) -> dict[TrackerSelection, TrackerInfo]:
        """
        Public method that can be utilized to update the `tracker_map` order based on an input iterable.
        If `order` is provided we'll update the map based on the provided order, otherwise we'll default
        back to reading it from the saved config.

        This does not update the saved config on disk, this needs to be called separately.

        Note: We're subtracting `-1` since our enum starts at `1`, this keeps things inline.

        Args:
            order (list[int], None): List of ints. Defaults to None.

        Returns:
            dict[TrackerSelection, TrackerInfo]
        """
        if order:
            mapped_order = order
            self.cfg_payload.tracker_order = mapped_order
        else:
            mapped_order = self.cfg_payload.tracker_order
        self.tracker_map = dict(
            sorted(
                self.tracker_map.items(),
                key=lambda item: mapped_order[item[0].value - 1],
            )
        )
        return self.tracker_map

    def _client_map(self) -> dict[TorrentClientSelection, TorrentClient | WatchFolder]:
        """
        Map all of the torrent clients to their Enum for easy usage through out the program.
        """
        return {
            TorrentClientSelection.QBITTORRENT: self.cfg_payload.qbittorrent,
            TorrentClientSelection.DELUGE: self.cfg_payload.deluge,
            TorrentClientSelection.RTORRENT: self.cfg_payload.rtorrent,
            TorrentClientSelection.TRANSMISSION: self.cfg_payload.transmission,
            TorrentClientSelection.WATCH_FOLDER: self.cfg_payload.watch_folder,
        }

    def _image_host_map(
        self,
    ) -> dict[
        ImageHost,
        CheveretoV3Payload | CheveretoV4Payload | ImageBBPayload | None,
    ]:
        """
        Map all of the image hosts to their enum/payloads for easy usage through out the program.
        """
        return {
            ImageHost.DISABLED: None,
            ImageHost.CHEVERETO_V3: self.cfg_payload.chevereto_v3,
            ImageHost.CHEVERETO_V4: self.cfg_payload.chevereto_v4,
            ImageHost.IMAGE_BOX: None,
            ImageHost.IMAGE_BB: self.cfg_payload.image_bb,
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
