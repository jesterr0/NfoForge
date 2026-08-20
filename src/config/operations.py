from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any, cast

import tomlkit
from tomlkit.items import AbstractTable

from src.backend.tokens import TokenSelection
from src.config.codec import TomlConfigCodec
from src.config.models import (
    ApiKeysSettings,
    AppConfig,
    ClaimSwitches,
    DependencySettings,
    DynamicRangeSettings,
    GeneralSettings,
    GlobalManagementSettings,
    HdrType,
    ImageHostSettings,
    MovieSettings,
    PluginSettings,
    ProgramConfig,
    ReleaseNoteSettings,
    ResolutionKey,
    ScreenshotSettings,
    SeriesSettings,
    TemplateSettings,
    TorrentClientSettings,
    TrackerSettings,
    UrlSettings,
    UserTokenSettings,
    WidgetSettings,
)
from src.config.paths import ConfigPaths
from src.config.persistence import atomic_write_text
from src.config.tv_tokens import SUPPORTED_TVR_FORMATS
from src.enums.cropping import Cropping
from src.enums.image_host import ImageHost, ImageSource
from src.enums.image_plugin import ImagePlugin
from src.enums.indexer import Indexer
from src.enums.logging_settings import LogLevel
from src.enums.media_search_mode import MediaSearchMode
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.series import EpisodeFormat
from src.enums.subtitles import SubtitleAlignment
from src.enums.theme import NfoForgeTheme
from src.enums.token_replacer import ColonReplace
from src.enums.torrent_client import QBittorrentSavePathMode
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.beyondhd import BHDLiveRelease, BHDPromo
from src.enums.url_type import URLType
from src.exceptions import ConfigError
from src.payloads.clients import (
    DelugeConfig,
    QBittorrentConfig,
    RTorrentConfig,
    TransmissionConfig,
)
from src.payloads.image_hosts import (
    CheveretoV3Payload,
    CheveretoV4Payload,
    ImageBBPayload,
    ImageBoxPayload,
    LensdumpPayload,
    OnlyImagePayload,
    PixhostPayload,
)
from src.payloads.trackers import (
    AitherInfo,
    BeyondHDInfo,
    BlutopiaInfo,
    DarkPeersInfo,
    FearNoPeerInfo,
    HDBInfo,
    HunoInfo,
    LSTInfo,
    OnlyEncodesInfo,
    PassThePopcornInfo,
    ReelFlixInfo,
    SeedPoolInfo,
    ShareIslandInfo,
    TitleOverridePayload,
    TorrentLeechInfo,
    TrackerInfo,
    UploadCXInfo,
    UTPInfo,
    YuSceneInfo,
)
from src.payloads.watch_folder import WatchFolder

_CLAIM_KEYS = (
    "edition",
    "frame_size",
    "localization",
    "re_release",
    "remux",
    "hybrid",
)


def _load_claims(section: Mapping[str, Any], prefix: str) -> ClaimSwitches:
    """Read the claim switches, defaulting anything absent to on.

    `.get` throughout: these keys arrived with schema 9, and a profile
    written before it that reached this code without the migration is still
    readable rather than a hard failure.
    """
    return ClaimSwitches(
        enabled=bool(section.get(f"{prefix}_parse_claims", True)),
        **{
            claim: bool(section.get(f"{prefix}_parse_claim_{claim}", True))
            for claim in _CLAIM_KEYS
        },
    )


class TypedTomlOperations:
    settings: AppConfig
    defaults: AppConfig
    program: ProgramConfig
    paths: ConfigPaths
    codec: TomlConfigCodec
    _toml_data: MutableMapping[str, Any]
    _config_snapshot: str | None
    _active_profile_path: Path | None

    def save_program(self) -> None:
        """Persist program-level config.

        Implemented by ConfigManager. Declared here because save() is shared by
        the typed TOML operations base.
        """
        raise NotImplementedError

    @staticmethod
    def _toml_table(
        parent: Mapping[str, Any],
        key: str,
    ) -> AbstractTable:
        return cast(AbstractTable, parent[key])

    @classmethod
    def _ensure_toml_table(
        cls,
        parent: MutableMapping[str, Any],
        key: str,
    ) -> AbstractTable:
        if key not in parent:
            parent[key] = tomlkit.table()
        return cls._toml_table(parent, key)

    @classmethod
    def _toml_mapping(
        cls,
        parent: Mapping[str, Any],
        key: str,
    ) -> dict[str, Any]:
        return cls._toml_table(parent, key).unwrap()

    def save(self, save_path: Path | None = None) -> None:
        """Converts config payload object to TOML and writes to a file"""
        try:
            self.codec.validate_settings(self.settings)
            # update program conf
            self.save_program()

            # Update the toml object
            # general
            general_data = self._toml_table(self._toml_data, "general")
            general_data["ui_suffix"] = self.settings.general.ui_suffix
            general_data["ui_scale_factor"] = self.settings.general.ui_scale_factor
            general_data["nfo_forge_theme"] = NfoForgeTheme(
                self.settings.general.theme
            ).value
            general_data["enable_plugins"] = self.settings.general.enable_plugins
            general_data["releasers_name"] = self.settings.general.releasers_name
            general_data["tmdb_language"] = self.settings.general.tmdb_language
            general_data["media_search_mode"] = (
                self.settings.general.media_search_mode.value
            )
            general_data["timeout"] = self.settings.general.timeout
            general_data["enable_prompt_overview"] = (
                self.settings.general.enable_prompt_overview
            )
            general_data["enable_mkbrr"] = self.settings.general.enable_mkbrr
            general_data["log_level"] = LogLevel(self.settings.general.log_level).value
            general_data["log_total"] = self.settings.general.log_total
            general_data["working_dir"] = str(self.settings.general.working_dir)

            # dependencies
            dependencies_data = self._toml_table(self._toml_data, "dependencies")
            dependencies_data["ffmpeg"] = self.resolve_dependency(
                self.settings.dependencies.ffmpeg
            )
            dependencies_data["ffprobe"] = self.resolve_dependency(
                self.settings.dependencies.ffprobe
            )
            dependencies_data["frame_forge"] = self.resolve_dependency(
                self.settings.dependencies.frame_forge
            )
            dependencies_data["mkbrr"] = self.resolve_dependency(
                self.settings.dependencies.mkbrr
            )

            # api keys
            api_keys_data = self._ensure_toml_table(self._toml_data, "api_keys")
            api_keys_data["tmdb_api_key"] = self.settings.api_keys.tmdb_api_key

            # trackers
            tracker_data = self._toml_table(self._toml_data, "tracker")

            # tracker settings
            tracker_settings = self._toml_table(tracker_data, "settings")
            tracker_settings["tracker_order"] = [
                str(x) for x in self.settings.trackers.order
            ]
            last_used_img_host = tomlkit.inline_table()
            for (
                tracker,
                image_host,
            ) in self.settings.trackers.last_used_image_host.items():
                last_used_img_host[str(tracker)] = str(image_host)
            tracker_settings["last_used_img_host"] = last_used_img_host

            # torrent_leech tracker
            tl_data = self._ensure_toml_table(tracker_data, "torrent_leech")
            tl_data["upload_enabled"] = (
                self.settings.trackers.torrent_leech.upload_enabled
            )
            tl_data["announce_url"] = self.settings.trackers.torrent_leech.announce_url
            tl_data["enabled"] = self.settings.trackers.torrent_leech.enabled
            tl_data["source"] = self.settings.trackers.torrent_leech.source
            tl_data["comments"] = self.settings.trackers.torrent_leech.comments
            tl_data["nfo_template"] = self.settings.trackers.torrent_leech.nfo_template
            tl_data["url_type"] = URLType(
                self.settings.trackers.torrent_leech.url_type
            ).value
            tl_data["column_s"] = self.settings.trackers.torrent_leech.column_s
            tl_data["column_space"] = self.settings.trackers.torrent_leech.column_space
            tl_data["row_space"] = self.settings.trackers.torrent_leech.row_space
            tl_data["mvr_title_override_enabled"] = (
                self.settings.trackers.torrent_leech.mvr_title_override_enabled
            )
            tl_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.torrent_leech.mvr_title_colon_replace
            ).value
            tl_data["mvr_title_token_override"] = (
                self.settings.trackers.torrent_leech.mvr_title_token_override
            )
            tl_data["mvr_title_replace_map"] = (
                self.settings.trackers.torrent_leech.mvr_title_replace_map
            )
            tl_data["username"] = self.settings.trackers.torrent_leech.username
            tl_data["password"] = self.settings.trackers.torrent_leech.password
            tl_data["torrent_passkey"] = (
                self.settings.trackers.torrent_leech.torrent_passkey
            )
            tl_data["alt_2_fa_token"] = (
                self.settings.trackers.torrent_leech.alt_2_fa_token
            )

            # BeyondHD tracker
            bhd_data = self._ensure_toml_table(tracker_data, "beyond_hd")
            bhd_data["upload_enabled"] = self.settings.trackers.beyond_hd.upload_enabled
            bhd_data["announce_url"] = self.settings.trackers.beyond_hd.announce_url
            bhd_data["enabled"] = self.settings.trackers.beyond_hd.enabled
            bhd_data["source"] = self.settings.trackers.beyond_hd.source
            bhd_data["comments"] = self.settings.trackers.beyond_hd.comments
            bhd_data["nfo_template"] = self.settings.trackers.beyond_hd.nfo_template
            bhd_data["url_type"] = URLType(
                self.settings.trackers.beyond_hd.url_type
            ).value
            bhd_data["column_s"] = self.settings.trackers.beyond_hd.column_s
            bhd_data["column_space"] = self.settings.trackers.beyond_hd.column_space
            bhd_data["row_space"] = self.settings.trackers.beyond_hd.row_space
            bhd_data["mvr_title_override_enabled"] = (
                self.settings.trackers.beyond_hd.mvr_title_override_enabled
            )
            bhd_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.beyond_hd.mvr_title_colon_replace
            ).value
            bhd_data["mvr_title_token_override"] = (
                self.settings.trackers.beyond_hd.mvr_title_token_override
            )
            bhd_data["mvr_title_replace_map"] = (
                self.settings.trackers.beyond_hd.mvr_title_replace_map
            )
            bhd_data["anonymous"] = self.settings.trackers.beyond_hd.anonymous
            bhd_data["api_key"] = self.settings.trackers.beyond_hd.api_key
            bhd_data["rss_key"] = self.settings.trackers.beyond_hd.rss_key
            bhd_data["promo"] = BHDPromo(self.settings.trackers.beyond_hd.promo).value
            bhd_data["live_release"] = BHDLiveRelease(
                self.settings.trackers.beyond_hd.live_release
            ).value
            bhd_data["internal"] = self.settings.trackers.beyond_hd.internal
            bhd_data["image_width"] = self.settings.trackers.beyond_hd.image_width
            bhd_data["add_localization_to_custom_edition"] = (
                self.settings.trackers.beyond_hd.add_localization_to_custom_edition
            )
            bhd_data["stream_optimized"] = (
                self.settings.trackers.beyond_hd.stream_optimized
            )

            # PassThePopcorn tracker
            ptp_data = self._ensure_toml_table(tracker_data, "pass_the_popcorn")
            ptp_data["upload_enabled"] = (
                self.settings.trackers.pass_the_popcorn.upload_enabled
            )
            ptp_data["announce_url"] = (
                self.settings.trackers.pass_the_popcorn.announce_url
            )
            ptp_data["enabled"] = self.settings.trackers.pass_the_popcorn.enabled
            ptp_data["source"] = self.settings.trackers.pass_the_popcorn.source
            ptp_data["comments"] = self.settings.trackers.pass_the_popcorn.comments
            ptp_data["nfo_template"] = (
                self.settings.trackers.pass_the_popcorn.nfo_template
            )
            ptp_data["url_type"] = URLType(
                self.settings.trackers.pass_the_popcorn.url_type
            ).value
            ptp_data["column_s"] = self.settings.trackers.pass_the_popcorn.column_s
            ptp_data["column_space"] = (
                self.settings.trackers.pass_the_popcorn.column_space
            )
            ptp_data["row_space"] = self.settings.trackers.pass_the_popcorn.row_space
            ptp_data["mvr_title_override_enabled"] = (
                self.settings.trackers.pass_the_popcorn.mvr_title_override_enabled
            )
            ptp_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.pass_the_popcorn.mvr_title_colon_replace
            ).value
            ptp_data["mvr_title_token_override"] = (
                self.settings.trackers.pass_the_popcorn.mvr_title_token_override
            )
            ptp_data["mvr_title_replace_map"] = (
                self.settings.trackers.pass_the_popcorn.mvr_title_replace_map
            )
            ptp_data["api_user"] = self.settings.trackers.pass_the_popcorn.api_user
            ptp_data["api_key"] = self.settings.trackers.pass_the_popcorn.api_key
            ptp_data["username"] = self.settings.trackers.pass_the_popcorn.username
            ptp_data["password"] = self.settings.trackers.pass_the_popcorn.password
            ptp_data["totp"] = self.settings.trackers.pass_the_popcorn.totp

            # ReelFliX tracker
            rf_data = self._ensure_toml_table(tracker_data, "reelflix")
            rf_data["upload_enabled"] = self.settings.trackers.reelflix.upload_enabled
            rf_data["announce_url"] = self.settings.trackers.reelflix.announce_url
            rf_data["enabled"] = self.settings.trackers.reelflix.enabled
            rf_data["source"] = self.settings.trackers.reelflix.source
            rf_data["comments"] = self.settings.trackers.reelflix.comments
            rf_data["nfo_template"] = self.settings.trackers.reelflix.nfo_template
            rf_data["url_type"] = URLType(
                self.settings.trackers.reelflix.url_type
            ).value
            rf_data["column_s"] = self.settings.trackers.reelflix.column_s
            rf_data["column_space"] = self.settings.trackers.reelflix.column_space
            rf_data["row_space"] = self.settings.trackers.reelflix.row_space
            rf_data["mvr_title_override_enabled"] = (
                self.settings.trackers.reelflix.mvr_title_override_enabled
            )
            rf_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.reelflix.mvr_title_colon_replace
            ).value
            rf_data["mvr_title_token_override"] = (
                self.settings.trackers.reelflix.mvr_title_token_override
            )
            rf_data["mvr_title_replace_map"] = (
                self.settings.trackers.reelflix.mvr_title_replace_map
            )
            rf_data["api_key"] = self.settings.trackers.reelflix.api_key
            rf_data["anonymous"] = self.settings.trackers.reelflix.anonymous
            rf_data["internal"] = self.settings.trackers.reelflix.internal
            rf_data["personal_release"] = (
                self.settings.trackers.reelflix.personal_release
            )
            rf_data["stream_optimized"] = (
                self.settings.trackers.reelflix.stream_optimized
            )
            rf_data["opt_in_to_mod_queue"] = (
                self.settings.trackers.reelflix.opt_in_to_mod_queue
            )
            rf_data["featured"] = self.settings.trackers.reelflix.featured
            rf_data["free"] = self.settings.trackers.reelflix.free
            rf_data["double_up"] = self.settings.trackers.reelflix.double_up
            rf_data["sticky"] = self.settings.trackers.reelflix.sticky
            rf_data["image_width"] = self.settings.trackers.reelflix.image_width

            # Aither tracker
            aither_data = self._ensure_toml_table(tracker_data, "aither")
            aither_data["upload_enabled"] = self.settings.trackers.aither.upload_enabled
            aither_data["announce_url"] = self.settings.trackers.aither.announce_url
            aither_data["enabled"] = self.settings.trackers.aither.enabled
            aither_data["source"] = self.settings.trackers.aither.source
            aither_data["comments"] = self.settings.trackers.aither.comments
            aither_data["nfo_template"] = self.settings.trackers.aither.nfo_template
            aither_data["url_type"] = URLType(
                self.settings.trackers.aither.url_type
            ).value
            aither_data["column_s"] = self.settings.trackers.aither.column_s
            aither_data["column_space"] = self.settings.trackers.aither.column_space
            aither_data["row_space"] = self.settings.trackers.aither.row_space
            aither_data["mvr_title_override_enabled"] = (
                self.settings.trackers.aither.mvr_title_override_enabled
            )
            aither_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.aither.mvr_title_colon_replace
            ).value
            aither_data["mvr_title_token_override"] = (
                self.settings.trackers.aither.mvr_title_token_override
            )
            aither_data["mvr_title_replace_map"] = (
                self.settings.trackers.aither.mvr_title_replace_map
            )
            aither_data["api_key"] = self.settings.trackers.aither.api_key
            aither_data["anonymous"] = self.settings.trackers.aither.anonymous
            aither_data["internal"] = self.settings.trackers.aither.internal
            aither_data["personal_release"] = (
                self.settings.trackers.aither.personal_release
            )
            aither_data["stream_optimized"] = (
                self.settings.trackers.aither.stream_optimized
            )
            aither_data["opt_in_to_mod_queue"] = (
                self.settings.trackers.aither.opt_in_to_mod_queue
            )
            aither_data["featured"] = self.settings.trackers.aither.featured
            aither_data["free"] = self.settings.trackers.aither.free
            aither_data["double_up"] = self.settings.trackers.aither.double_up
            aither_data["sticky"] = self.settings.trackers.aither.sticky
            aither_data["image_width"] = self.settings.trackers.aither.image_width

            # HUNO tracker
            huno_data = self._ensure_toml_table(tracker_data, "huno")
            huno_data["upload_enabled"] = self.settings.trackers.huno.upload_enabled
            huno_data["announce_url"] = self.settings.trackers.huno.announce_url
            huno_data["enabled"] = self.settings.trackers.huno.enabled
            huno_data["source"] = self.settings.trackers.huno.source
            huno_data["comments"] = self.settings.trackers.huno.comments
            huno_data["nfo_template"] = self.settings.trackers.huno.nfo_template
            huno_data["url_type"] = URLType(self.settings.trackers.huno.url_type).value
            huno_data["column_s"] = self.settings.trackers.huno.column_s
            huno_data["column_space"] = self.settings.trackers.huno.column_space
            huno_data["row_space"] = self.settings.trackers.huno.row_space
            huno_data["mvr_title_override_enabled"] = (
                self.settings.trackers.huno.mvr_title_override_enabled
            )
            huno_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.huno.mvr_title_colon_replace
            ).value
            huno_data["mvr_title_token_override"] = (
                self.settings.trackers.huno.mvr_title_token_override
            )
            huno_data["mvr_title_replace_map"] = (
                self.settings.trackers.huno.mvr_title_replace_map
            )
            huno_data["api_key"] = self.settings.trackers.huno.api_key
            huno_data["anonymous"] = self.settings.trackers.huno.anonymous
            huno_data["internal"] = self.settings.trackers.huno.internal
            huno_data["stream_optimized"] = self.settings.trackers.huno.stream_optimized
            huno_data["image_width"] = self.settings.trackers.huno.image_width

            # LST tracker
            lst_data = self._ensure_toml_table(tracker_data, "lst")
            lst_data["upload_enabled"] = self.settings.trackers.lst.upload_enabled
            lst_data["announce_url"] = self.settings.trackers.lst.announce_url
            lst_data["enabled"] = self.settings.trackers.lst.enabled
            lst_data["source"] = self.settings.trackers.lst.source
            lst_data["comments"] = self.settings.trackers.lst.comments
            lst_data["nfo_template"] = self.settings.trackers.lst.nfo_template
            lst_data["url_type"] = URLType(self.settings.trackers.lst.url_type).value
            lst_data["column_s"] = self.settings.trackers.lst.column_s
            lst_data["column_space"] = self.settings.trackers.lst.column_space
            lst_data["row_space"] = self.settings.trackers.lst.row_space
            lst_data["mvr_title_override_enabled"] = (
                self.settings.trackers.lst.mvr_title_override_enabled
            )
            lst_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.lst.mvr_title_colon_replace
            ).value
            lst_data["mvr_title_token_override"] = (
                self.settings.trackers.lst.mvr_title_token_override
            )
            lst_data["mvr_title_replace_map"] = (
                self.settings.trackers.lst.mvr_title_replace_map
            )
            lst_data["api_key"] = self.settings.trackers.lst.api_key
            lst_data["anonymous"] = self.settings.trackers.lst.anonymous
            lst_data["internal"] = self.settings.trackers.lst.internal
            lst_data["personal_release"] = self.settings.trackers.lst.personal_release
            lst_data["mod_queue_opt_in"] = self.settings.trackers.lst.mod_queue_opt_in
            lst_data["draft_queue_opt_in"] = (
                self.settings.trackers.lst.draft_queue_opt_in
            )
            lst_data["featured"] = self.settings.trackers.lst.featured
            lst_data["free"] = self.settings.trackers.lst.free
            lst_data["double_up"] = self.settings.trackers.lst.double_up
            lst_data["sticky"] = self.settings.trackers.lst.sticky
            lst_data["image_width"] = self.settings.trackers.lst.image_width

            # DarkPeers tracker
            dark_peers_data = self._ensure_toml_table(tracker_data, "dark_peers")
            dark_peers_data["upload_enabled"] = (
                self.settings.trackers.dark_peers.upload_enabled
            )
            dark_peers_data["announce_url"] = (
                self.settings.trackers.dark_peers.announce_url
            )
            dark_peers_data["enabled"] = self.settings.trackers.dark_peers.enabled
            dark_peers_data["source"] = self.settings.trackers.dark_peers.source
            dark_peers_data["comments"] = self.settings.trackers.dark_peers.comments
            dark_peers_data["nfo_template"] = (
                self.settings.trackers.dark_peers.nfo_template
            )
            dark_peers_data["url_type"] = URLType(
                self.settings.trackers.dark_peers.url_type
            ).value
            dark_peers_data["column_s"] = self.settings.trackers.dark_peers.column_s
            dark_peers_data["column_space"] = (
                self.settings.trackers.dark_peers.column_space
            )
            dark_peers_data["row_space"] = self.settings.trackers.dark_peers.row_space
            dark_peers_data["mvr_title_override_enabled"] = (
                self.settings.trackers.dark_peers.mvr_title_override_enabled
            )
            dark_peers_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.dark_peers.mvr_title_colon_replace
            ).value
            dark_peers_data["mvr_title_token_override"] = (
                self.settings.trackers.dark_peers.mvr_title_token_override
            )
            dark_peers_data["mvr_title_replace_map"] = (
                self.settings.trackers.dark_peers.mvr_title_replace_map
            )
            dark_peers_data["api_key"] = self.settings.trackers.dark_peers.api_key
            dark_peers_data["anonymous"] = self.settings.trackers.dark_peers.anonymous
            dark_peers_data["internal"] = self.settings.trackers.dark_peers.internal
            dark_peers_data["personal_release"] = (
                self.settings.trackers.dark_peers.personal_release
            )
            dark_peers_data["image_width"] = (
                self.settings.trackers.dark_peers.image_width
            )

            # ShareIsland tracker
            shareisland_data = self._ensure_toml_table(tracker_data, "shareisland")
            shareisland_data["upload_enabled"] = (
                self.settings.trackers.share_island.upload_enabled
            )
            shareisland_data["announce_url"] = (
                self.settings.trackers.share_island.announce_url
            )
            shareisland_data["enabled"] = self.settings.trackers.share_island.enabled
            shareisland_data["source"] = self.settings.trackers.share_island.source
            shareisland_data["comments"] = self.settings.trackers.share_island.comments
            shareisland_data["nfo_template"] = (
                self.settings.trackers.share_island.nfo_template
            )
            shareisland_data["url_type"] = URLType(
                self.settings.trackers.share_island.url_type
            ).value
            shareisland_data["column_s"] = self.settings.trackers.share_island.column_s
            shareisland_data["column_space"] = (
                self.settings.trackers.share_island.column_space
            )
            shareisland_data["row_space"] = (
                self.settings.trackers.share_island.row_space
            )
            shareisland_data["mvr_title_override_enabled"] = (
                self.settings.trackers.share_island.mvr_title_override_enabled
            )
            shareisland_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.share_island.mvr_title_colon_replace
            ).value
            shareisland_data["mvr_title_token_override"] = (
                self.settings.trackers.share_island.mvr_title_token_override
            )
            shareisland_data["mvr_title_replace_map"] = (
                self.settings.trackers.share_island.mvr_title_replace_map
            )
            shareisland_data["api_key"] = self.settings.trackers.share_island.api_key
            shareisland_data["anonymous"] = (
                self.settings.trackers.share_island.anonymous
            )
            shareisland_data["internal"] = self.settings.trackers.share_island.internal
            shareisland_data["personal_release"] = (
                self.settings.trackers.share_island.personal_release
            )
            shareisland_data["opt_in_to_mod_queue"] = (
                self.settings.trackers.share_island.opt_in_to_mod_queue
            )
            shareisland_data["image_width"] = (
                self.settings.trackers.share_island.image_width
            )

            # UploadCX tracker
            uploadcx_data = self._ensure_toml_table(tracker_data, "uploadcx")
            uploadcx_data["upload_enabled"] = (
                self.settings.trackers.upload_cx.upload_enabled
            )
            uploadcx_data["announce_url"] = (
                self.settings.trackers.upload_cx.announce_url
            )
            uploadcx_data["enabled"] = self.settings.trackers.upload_cx.enabled
            uploadcx_data["source"] = self.settings.trackers.upload_cx.source
            uploadcx_data["comments"] = self.settings.trackers.upload_cx.comments
            uploadcx_data["nfo_template"] = (
                self.settings.trackers.upload_cx.nfo_template
            )
            uploadcx_data["url_type"] = URLType(
                self.settings.trackers.upload_cx.url_type
            ).value
            uploadcx_data["column_s"] = self.settings.trackers.upload_cx.column_s
            uploadcx_data["column_space"] = (
                self.settings.trackers.upload_cx.column_space
            )
            uploadcx_data["row_space"] = self.settings.trackers.upload_cx.row_space
            uploadcx_data["mvr_title_override_enabled"] = (
                self.settings.trackers.upload_cx.mvr_title_override_enabled
            )
            uploadcx_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.upload_cx.mvr_title_colon_replace
            ).value
            uploadcx_data["mvr_title_token_override"] = (
                self.settings.trackers.upload_cx.mvr_title_token_override
            )
            uploadcx_data["mvr_title_replace_map"] = (
                self.settings.trackers.upload_cx.mvr_title_replace_map
            )
            uploadcx_data["api_key"] = self.settings.trackers.upload_cx.api_key
            uploadcx_data["anonymous"] = self.settings.trackers.upload_cx.anonymous
            uploadcx_data["internal"] = self.settings.trackers.upload_cx.internal
            uploadcx_data["personal_release"] = (
                self.settings.trackers.upload_cx.personal_release
            )
            uploadcx_data["image_width"] = self.settings.trackers.upload_cx.image_width

            # OnlyEncodes tracker
            oe_data = self._ensure_toml_table(tracker_data, "only_encodes")
            oe_data["upload_enabled"] = (
                self.settings.trackers.only_encodes.upload_enabled
            )
            oe_data["announce_url"] = self.settings.trackers.only_encodes.announce_url
            oe_data["enabled"] = self.settings.trackers.only_encodes.enabled
            oe_data["source"] = self.settings.trackers.only_encodes.source
            oe_data["comments"] = self.settings.trackers.only_encodes.comments
            oe_data["nfo_template"] = self.settings.trackers.only_encodes.nfo_template
            oe_data["url_type"] = URLType(
                self.settings.trackers.only_encodes.url_type
            ).value
            oe_data["column_s"] = self.settings.trackers.only_encodes.column_s
            oe_data["column_space"] = self.settings.trackers.only_encodes.column_space
            oe_data["row_space"] = self.settings.trackers.only_encodes.row_space
            oe_data["mvr_title_override_enabled"] = (
                self.settings.trackers.only_encodes.mvr_title_override_enabled
            )
            oe_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.only_encodes.mvr_title_colon_replace
            ).value
            oe_data["mvr_title_token_override"] = (
                self.settings.trackers.only_encodes.mvr_title_token_override
            )
            oe_data["mvr_title_replace_map"] = (
                self.settings.trackers.only_encodes.mvr_title_replace_map
            )
            oe_data["api_key"] = self.settings.trackers.only_encodes.api_key
            oe_data["anonymous"] = self.settings.trackers.only_encodes.anonymous
            oe_data["internal"] = self.settings.trackers.only_encodes.internal
            oe_data["personal_release"] = (
                self.settings.trackers.only_encodes.personal_release
            )
            oe_data["image_width"] = self.settings.trackers.only_encodes.image_width

            # HDBits tracker
            hdb_data = self._ensure_toml_table(tracker_data, "hdb")
            hdb_data["upload_enabled"] = self.settings.trackers.hdb.upload_enabled
            hdb_data["announce_url"] = self.settings.trackers.hdb.announce_url
            hdb_data["enabled"] = self.settings.trackers.hdb.enabled
            hdb_data["source"] = self.settings.trackers.hdb.source
            hdb_data["comments"] = self.settings.trackers.hdb.comments
            hdb_data["nfo_template"] = self.settings.trackers.hdb.nfo_template
            hdb_data["url_type"] = URLType(self.settings.trackers.hdb.url_type).value
            hdb_data["column_s"] = self.settings.trackers.hdb.column_s
            hdb_data["column_space"] = self.settings.trackers.hdb.column_space
            hdb_data["row_space"] = self.settings.trackers.hdb.row_space
            hdb_data["mvr_title_override_enabled"] = (
                self.settings.trackers.hdb.mvr_title_override_enabled
            )
            hdb_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.hdb.mvr_title_colon_replace
            ).value
            hdb_data["mvr_title_token_override"] = (
                self.settings.trackers.hdb.mvr_title_token_override
            )
            hdb_data["mvr_title_replace_map"] = (
                self.settings.trackers.hdb.mvr_title_replace_map
            )
            hdb_data["username"] = self.settings.trackers.hdb.username
            hdb_data["passkey"] = self.settings.trackers.hdb.passkey
            hdb_data["session_cookie"] = self.settings.trackers.hdb.session_cookie
            hdb_data["internal"] = self.settings.trackers.hdb.internal
            hdb_data["image_width"] = self.settings.trackers.hdb.image_width

            # Blutopia tracker
            blutopia_data = self._ensure_toml_table(tracker_data, "blutopia")
            blutopia_data["upload_enabled"] = (
                self.settings.trackers.blutopia.upload_enabled
            )
            blutopia_data["announce_url"] = self.settings.trackers.blutopia.announce_url
            blutopia_data["enabled"] = self.settings.trackers.blutopia.enabled
            blutopia_data["source"] = self.settings.trackers.blutopia.source
            blutopia_data["comments"] = self.settings.trackers.blutopia.comments
            blutopia_data["nfo_template"] = self.settings.trackers.blutopia.nfo_template
            blutopia_data["url_type"] = URLType(
                self.settings.trackers.blutopia.url_type
            ).value
            blutopia_data["column_s"] = self.settings.trackers.blutopia.column_s
            blutopia_data["column_space"] = self.settings.trackers.blutopia.column_space
            blutopia_data["row_space"] = self.settings.trackers.blutopia.row_space
            blutopia_data["mvr_title_override_enabled"] = (
                self.settings.trackers.blutopia.mvr_title_override_enabled
            )
            blutopia_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.blutopia.mvr_title_colon_replace
            ).value
            blutopia_data["mvr_title_token_override"] = (
                self.settings.trackers.blutopia.mvr_title_token_override
            )
            blutopia_data["mvr_title_replace_map"] = (
                self.settings.trackers.blutopia.mvr_title_replace_map
            )
            blutopia_data["api_key"] = self.settings.trackers.blutopia.api_key
            blutopia_data["anonymous"] = self.settings.trackers.blutopia.anonymous
            blutopia_data["internal"] = self.settings.trackers.blutopia.internal
            blutopia_data["personal_release"] = (
                self.settings.trackers.blutopia.personal_release
            )
            blutopia_data["opt_in_to_mod_queue"] = (
                self.settings.trackers.blutopia.opt_in_to_mod_queue
            )
            blutopia_data["image_width"] = self.settings.trackers.blutopia.image_width

            # SeedPool tracker
            seedpool_data = self._ensure_toml_table(tracker_data, "seedpool")
            seedpool_data["upload_enabled"] = (
                self.settings.trackers.seedpool.upload_enabled
            )
            seedpool_data["announce_url"] = self.settings.trackers.seedpool.announce_url
            seedpool_data["enabled"] = self.settings.trackers.seedpool.enabled
            seedpool_data["source"] = self.settings.trackers.seedpool.source
            seedpool_data["comments"] = self.settings.trackers.seedpool.comments
            seedpool_data["nfo_template"] = self.settings.trackers.seedpool.nfo_template
            seedpool_data["url_type"] = URLType(
                self.settings.trackers.seedpool.url_type
            ).value
            seedpool_data["column_s"] = self.settings.trackers.seedpool.column_s
            seedpool_data["column_space"] = self.settings.trackers.seedpool.column_space
            seedpool_data["row_space"] = self.settings.trackers.seedpool.row_space
            seedpool_data["mvr_title_override_enabled"] = (
                self.settings.trackers.seedpool.mvr_title_override_enabled
            )
            seedpool_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.seedpool.mvr_title_colon_replace
            ).value
            seedpool_data["mvr_title_token_override"] = (
                self.settings.trackers.seedpool.mvr_title_token_override
            )
            seedpool_data["mvr_title_replace_map"] = (
                self.settings.trackers.seedpool.mvr_title_replace_map
            )
            seedpool_data["api_key"] = self.settings.trackers.seedpool.api_key
            seedpool_data["anonymous"] = self.settings.trackers.seedpool.anonymous
            seedpool_data["internal"] = self.settings.trackers.seedpool.internal
            seedpool_data["personal_release"] = (
                self.settings.trackers.seedpool.personal_release
            )
            seedpool_data["image_width"] = self.settings.trackers.seedpool.image_width

            # UTP tracker
            utp_data = self._ensure_toml_table(tracker_data, "utp")
            utp_data["upload_enabled"] = self.settings.trackers.utp.upload_enabled
            utp_data["announce_url"] = self.settings.trackers.utp.announce_url
            utp_data["enabled"] = self.settings.trackers.utp.enabled
            utp_data["source"] = self.settings.trackers.utp.source
            utp_data["comments"] = self.settings.trackers.utp.comments
            utp_data["nfo_template"] = self.settings.trackers.utp.nfo_template
            utp_data["url_type"] = URLType(self.settings.trackers.utp.url_type).value
            utp_data["column_s"] = self.settings.trackers.utp.column_s
            utp_data["column_space"] = self.settings.trackers.utp.column_space
            utp_data["row_space"] = self.settings.trackers.utp.row_space
            utp_data["mvr_title_override_enabled"] = (
                self.settings.trackers.utp.mvr_title_override_enabled
            )
            utp_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.utp.mvr_title_colon_replace
            ).value
            utp_data["mvr_title_token_override"] = (
                self.settings.trackers.utp.mvr_title_token_override
            )
            utp_data["mvr_title_replace_map"] = (
                self.settings.trackers.utp.mvr_title_replace_map
            )
            utp_data["api_key"] = self.settings.trackers.utp.api_key
            utp_data["anonymous"] = self.settings.trackers.utp.anonymous
            utp_data["internal"] = self.settings.trackers.utp.internal
            utp_data["personal_release"] = self.settings.trackers.utp.personal_release
            utp_data["image_width"] = self.settings.trackers.utp.image_width

            # Yu-scene tracker
            yuscene_data = self._ensure_toml_table(tracker_data, "yuscene")
            yuscene_data["upload_enabled"] = (
                self.settings.trackers.yuscene.upload_enabled
            )
            yuscene_data["announce_url"] = self.settings.trackers.yuscene.announce_url
            yuscene_data["enabled"] = self.settings.trackers.yuscene.enabled
            yuscene_data["source"] = self.settings.trackers.yuscene.source
            yuscene_data["comments"] = self.settings.trackers.yuscene.comments
            yuscene_data["nfo_template"] = self.settings.trackers.yuscene.nfo_template
            yuscene_data["url_type"] = URLType(
                self.settings.trackers.yuscene.url_type
            ).value
            yuscene_data["column_s"] = self.settings.trackers.yuscene.column_s
            yuscene_data["column_space"] = self.settings.trackers.yuscene.column_space
            yuscene_data["row_space"] = self.settings.trackers.yuscene.row_space
            yuscene_data["mvr_title_override_enabled"] = (
                self.settings.trackers.yuscene.mvr_title_override_enabled
            )
            yuscene_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.yuscene.mvr_title_colon_replace
            ).value
            yuscene_data["mvr_title_token_override"] = (
                self.settings.trackers.yuscene.mvr_title_token_override
            )
            yuscene_data["mvr_title_replace_map"] = (
                self.settings.trackers.yuscene.mvr_title_replace_map
            )
            yuscene_data["api_key"] = self.settings.trackers.yuscene.api_key
            yuscene_data["anonymous"] = self.settings.trackers.yuscene.anonymous
            yuscene_data["internal"] = self.settings.trackers.yuscene.internal
            yuscene_data["personal_release"] = (
                self.settings.trackers.yuscene.personal_release
            )
            yuscene_data["image_width"] = self.settings.trackers.yuscene.image_width

            # FearNoPeer tracker
            fearnopeer_data = self._ensure_toml_table(tracker_data, "fearnopeer")
            fearnopeer_data["upload_enabled"] = (
                self.settings.trackers.fearnopeer.upload_enabled
            )
            fearnopeer_data["announce_url"] = (
                self.settings.trackers.fearnopeer.announce_url
            )
            fearnopeer_data["enabled"] = self.settings.trackers.fearnopeer.enabled
            fearnopeer_data["source"] = self.settings.trackers.fearnopeer.source
            fearnopeer_data["comments"] = self.settings.trackers.fearnopeer.comments
            fearnopeer_data["nfo_template"] = (
                self.settings.trackers.fearnopeer.nfo_template
            )
            fearnopeer_data["url_type"] = URLType(
                self.settings.trackers.fearnopeer.url_type
            ).value
            fearnopeer_data["column_s"] = self.settings.trackers.fearnopeer.column_s
            fearnopeer_data["column_space"] = (
                self.settings.trackers.fearnopeer.column_space
            )
            fearnopeer_data["row_space"] = self.settings.trackers.fearnopeer.row_space
            fearnopeer_data["mvr_title_override_enabled"] = (
                self.settings.trackers.fearnopeer.mvr_title_override_enabled
            )
            fearnopeer_data["mvr_title_colon_replace"] = ColonReplace(
                self.settings.trackers.fearnopeer.mvr_title_colon_replace
            ).value
            fearnopeer_data["mvr_title_token_override"] = (
                self.settings.trackers.fearnopeer.mvr_title_token_override
            )
            fearnopeer_data["mvr_title_replace_map"] = (
                self.settings.trackers.fearnopeer.mvr_title_replace_map
            )
            fearnopeer_data["api_key"] = self.settings.trackers.fearnopeer.api_key
            fearnopeer_data["anonymous"] = self.settings.trackers.fearnopeer.anonymous
            fearnopeer_data["internal"] = self.settings.trackers.fearnopeer.internal
            fearnopeer_data["personal_release"] = (
                self.settings.trackers.fearnopeer.personal_release
            )
            fearnopeer_data["image_width"] = (
                self.settings.trackers.fearnopeer.image_width
            )

            for tracker_key, tracker_info in (
                ("torrent_leech", self.settings.trackers.torrent_leech),
                ("beyond_hd", self.settings.trackers.beyond_hd),
                ("pass_the_popcorn", self.settings.trackers.pass_the_popcorn),
                ("reelflix", self.settings.trackers.reelflix),
                ("aither", self.settings.trackers.aither),
                ("huno", self.settings.trackers.huno),
                ("lst", self.settings.trackers.lst),
                ("dark_peers", self.settings.trackers.dark_peers),
                ("shareisland", self.settings.trackers.share_island),
                ("uploadcx", self.settings.trackers.upload_cx),
                ("only_encodes", self.settings.trackers.only_encodes),
                ("hdb", self.settings.trackers.hdb),
                ("blutopia", self.settings.trackers.blutopia),
                ("seedpool", self.settings.trackers.seedpool),
                ("utp", self.settings.trackers.utp),
                ("yuscene", self.settings.trackers.yuscene),
                ("fearnopeer", self.settings.trackers.fearnopeer),
            ):
                tracker_table = self._ensure_toml_table(tracker_data, tracker_key)
                tracker_table["tvr_title_overrides"] = (
                    self._serialize_series_title_overrides(tracker_info)
                )
                # Retired: piece size now comes from one hardcoded curve that is
                # the same for every tracker (see
                # src/backend/torrents/piece_size.py), so a per-tracker maximum
                # has nothing left to constrain. Dropped here rather than in a
                # migration because a removed key needs no schema bump -- see the
                # policy in src/config/migrations.py -- and this cleans the key
                # out of a user's profile the next time it is written.
                tracker_table.pop("max_piece_size", None)

            # torrent client
            torrent_client_data = self._toml_table(self._toml_data, "torrent_client")

            # qbittorrent
            qbittorrent_data = self._ensure_toml_table(
                torrent_client_data, "qbittorrent"
            )
            qbittorrent_data["enabled"] = (
                self.settings.torrent_clients.qbittorrent.enabled
            )
            qbittorrent_data["host"] = self.settings.torrent_clients.qbittorrent.host
            qbittorrent_data["port"] = self.settings.torrent_clients.qbittorrent.port
            qbittorrent_data["user"] = self.settings.torrent_clients.qbittorrent.user
            qbittorrent_data["password"] = (
                self.settings.torrent_clients.qbittorrent.password
            )
            qbittorrent_specific = cast(
                MutableMapping[str, Any],
                qbittorrent_data["specific_params"],
            )
            qbittorrent_specific["category"] = (
                self.settings.torrent_clients.qbittorrent.category
            )
            qbittorrent_specific["super_seeding"] = (
                self.settings.torrent_clients.qbittorrent.super_seeding
            )
            qbittorrent_specific["save_path_mode"] = (
                self.settings.torrent_clients.qbittorrent.save_path_mode.value
            )
            qbittorrent_specific["save_path_template"] = (
                self.settings.torrent_clients.qbittorrent.save_path_template
            )

            # deluge
            deluge_data = self._ensure_toml_table(torrent_client_data, "deluge")
            deluge_data["enabled"] = self.settings.torrent_clients.deluge.enabled
            deluge_data["host"] = self.settings.torrent_clients.deluge.host
            deluge_data["port"] = self.settings.torrent_clients.deluge.port
            deluge_data["user"] = self.settings.torrent_clients.deluge.user
            deluge_data["password"] = self.settings.torrent_clients.deluge.password
            deluge_specific = cast(
                MutableMapping[str, Any],
                deluge_data["specific_params"],
            )
            deluge_specific["label"] = self.settings.torrent_clients.deluge.label
            deluge_specific["path"] = self.settings.torrent_clients.deluge.path

            # rtorrent
            rtorrent_data = self._ensure_toml_table(torrent_client_data, "rtorrent")
            rtorrent_data["enabled"] = self.settings.torrent_clients.rtorrent.enabled
            rtorrent_data["host"] = self.settings.torrent_clients.rtorrent.host
            rtorrent_data["port"] = self.settings.torrent_clients.rtorrent.port
            rtorrent_data["user"] = self.settings.torrent_clients.rtorrent.user
            rtorrent_data["password"] = self.settings.torrent_clients.rtorrent.password
            rtorrent_specific = cast(
                MutableMapping[str, Any],
                rtorrent_data["specific_params"],
            )
            rtorrent_specific["label"] = self.settings.torrent_clients.rtorrent.label
            rtorrent_specific["path"] = self.settings.torrent_clients.rtorrent.path
            rtorrent_specific["verify_tls"] = (
                self.settings.torrent_clients.rtorrent.verify_tls
            )
            rtorrent_specific["ca_bundle"] = (
                self.settings.torrent_clients.rtorrent.ca_bundle
            )

            # transmission
            transmission_data = self._ensure_toml_table(
                torrent_client_data, "transmission"
            )
            transmission_data["enabled"] = (
                self.settings.torrent_clients.transmission.enabled
            )
            transmission_data["host"] = self.settings.torrent_clients.transmission.host
            transmission_data["port"] = self.settings.torrent_clients.transmission.port
            transmission_data["user"] = self.settings.torrent_clients.transmission.user
            transmission_data["password"] = (
                self.settings.torrent_clients.transmission.password
            )
            transmission_specific = cast(
                MutableMapping[str, Any],
                transmission_data["specific_params"],
            )
            transmission_specific["label"] = (
                self.settings.torrent_clients.transmission.label
            )
            transmission_specific["path"] = (
                self.settings.torrent_clients.transmission.path
            )

            # watch folder
            watch_folder_data = self._ensure_toml_table(self._toml_data, "watch_folder")
            watch_folder_data["enabled"] = (
                self.settings.torrent_clients.watch_folder.enabled
            )
            watch_folder_data["path"] = (
                str(self.settings.torrent_clients.watch_folder.path)
                if self.settings.torrent_clients.watch_folder.path
                else ""
            )

            # movie management
            movie_management = self._toml_table(self._toml_data, "movie_management")
            movie_management["mvr_enabled"] = self.settings.movie.enabled
            movie_management["mvr_colon_replace_filename"] = ColonReplace(
                self.settings.movie.filename_colon_replace
            ).value
            movie_management["mvr_colon_replace_title"] = ColonReplace(
                self.settings.movie.title_colon_replace
            ).value
            movie_management["mvr_parse_claims"] = self.settings.movie.claims.enabled
            for claim in _CLAIM_KEYS:
                movie_management[f"mvr_parse_claim_{claim}"] = getattr(
                    self.settings.movie.claims, claim
                )
            movie_management["mvr_token"] = self.settings.movie.filename_token
            movie_management["mvr_title_token"] = self.settings.movie.title_token
            movie_management["mvr_release_group"] = self.settings.movie.release_group

            # series management
            series_management = self._toml_table(self._toml_data, "series_management")
            series_management["tvr_enabled"] = self.settings.series.enabled
            series_management["tvr_colon_replace_filename"] = ColonReplace(
                self.settings.series.filename_colon_replace
            ).value
            series_management["tvr_colon_replace_title"] = ColonReplace(
                self.settings.series.title_colon_replace
            ).value
            series_management["tvr_parse_claims"] = self.settings.series.claims.enabled
            for claim in _CLAIM_KEYS:
                series_management[f"tvr_parse_claim_{claim}"] = getattr(
                    self.settings.series.claims, claim
                )
            series_management["tvr_standard_episode_token"] = (
                self.settings.series.standard_episode_token
            )
            series_management["tvr_daily_episode_token"] = (
                self.settings.series.daily_episode_token
            )
            series_management["tvr_anime_episode_token"] = (
                self.settings.series.anime_episode_token
            )
            series_management["tvr_season_folder_token"] = (
                self.settings.series.season_folder_token
            )
            series_management["tvr_season_subfolder_token"] = (
                self.settings.series.season_subfolder_token
            )
            series_management["tvr_multi_episode_style"] = (
                self.settings.series.multi_episode_style.value
            )
            series_management["tvr_standard_title_token"] = (
                self.settings.series.standard_title_token
            )
            series_management["tvr_daily_title_token"] = (
                self.settings.series.daily_title_token
            )
            series_management["tvr_anime_title_token"] = (
                self.settings.series.anime_title_token
            )
            series_management.pop("tvr_title_token", None)
            series_management["tvr_release_group"] = self.settings.series.release_group

            # global management
            global_management = self._toml_table(self._toml_data, "global_management")
            global_management["title_clean_rules"] = (
                self.settings.global_management.title_clean_rules
            )
            global_management["title_clean_rules_modified"] = (
                self.settings.global_management.title_clean_rules_modified
            )
            global_management["video_dynamic_range"] = (
                self.settings.global_management.video_dynamic_range.to_dict()
            )

            # user tokens
            user_token_data = self._toml_table(self._toml_data, "user_tokens")
            user_token_data["tokens"] = {
                key: [value, str(selection)]
                for key, (value, selection) in self.settings.user_tokens.tokens.items()
            }

            # screenshots
            screen_shot_data = self._toml_table(self._toml_data, "screenshots")
            screen_shot_data["crop_mode"] = Cropping(
                self.settings.screenshots.crop_mode
            ).value
            screen_shot_data["screenshots_enabled"] = self.settings.screenshots.enabled
            screen_shot_data["screen_shot_count"] = self.settings.screenshots.count
            screen_shot_data["min_required_selected_screens"] = (
                self.settings.screenshots.min_required_selected
            )
            screen_shot_data["max_required_selected_screens"] = (
                self.settings.screenshots.max_required_selected
            )
            screen_shot_data["ss_mode"] = ScreenShotMode(
                self.settings.screenshots.mode
            ).value
            screen_shot_data["sub_size_height_720"] = (
                self.settings.screenshots.subtitle_height_720
            )
            screen_shot_data["sub_size_height_1080"] = (
                self.settings.screenshots.subtitle_height_1080
            )
            screen_shot_data["sub_size_height_2160"] = (
                self.settings.screenshots.subtitle_height_2160
            )
            screen_shot_data["subtitle_alignment"] = SubtitleAlignment(
                self.settings.screenshots.subtitle_alignment
            ).value
            screen_shot_data["subtitle_color"] = (
                self.settings.screenshots.subtitle_color
            )
            screen_shot_data["subtitle_outline_color"] = (
                self.settings.screenshots.subtitle_outline_color
            )
            screen_shot_data["trim_start"] = self.settings.screenshots.trim_start
            screen_shot_data["trim_end"] = self.settings.screenshots.trim_end
            screen_shot_data["comparison_subtitles"] = (
                self.settings.screenshots.comparison_subtitles
            )
            screen_shot_data["comparison_subtitle_source_name"] = (
                self.settings.screenshots.comparison_source_name
            )
            screen_shot_data["comparison_subtitle_encode_name"] = (
                self.settings.screenshots.comparison_encode_name
            )
            screen_shot_data["optimize_generated_images"] = (
                self.settings.screenshots.optimize_generated_images
            )
            screen_shot_data["optimize_dl_url_images"] = (
                self.settings.screenshots.optimize_downloaded_images
            )
            screen_shot_data["optimize_dl_url_images_percentage"] = (
                self.settings.screenshots.optimize_downloaded_images_percentage
            )
            screen_shot_data["indexer"] = Indexer(
                self.settings.screenshots.indexer
            ).value
            screen_shot_data["image_plugin"] = ImagePlugin(
                self.settings.screenshots.image_plugin
            ).value

            # image hosts
            image_hosts = self._toml_table(self._toml_data, "image_hosts")

            # chevereto_v3
            chevereto_v3_data = self._ensure_toml_table(image_hosts, "chevereto_v3")
            chevereto_v3_data["enabled"] = (
                self.settings.image_hosts.chevereto_v3.enabled
            )
            chevereto_v3_data["base_url"] = (
                self.settings.image_hosts.chevereto_v3.base_url
            )
            chevereto_v3_data["user"] = self.settings.image_hosts.chevereto_v3.user
            chevereto_v3_data["password"] = (
                self.settings.image_hosts.chevereto_v3.password
            )

            # chevereto_v4
            chevereto_v4_data = self._ensure_toml_table(image_hosts, "chevereto_v4")
            chevereto_v4_data["enabled"] = (
                self.settings.image_hosts.chevereto_v4.enabled
            )
            chevereto_v4_data["base_url"] = (
                self.settings.image_hosts.chevereto_v4.base_url
            )
            chevereto_v4_data["api_key"] = (
                self.settings.image_hosts.chevereto_v4.api_key
            )

            # image bb
            img_bb_data = self._ensure_toml_table(image_hosts, "image_bb")
            img_bb_data["enabled"] = self.settings.image_hosts.image_bb.enabled
            img_bb_data["base_url"] = self.settings.image_hosts.image_bb.base_url
            img_bb_data["api_key"] = self.settings.image_hosts.image_bb.api_key

            # image box
            img_box_data = self._ensure_toml_table(image_hosts, "image_box")
            img_box_data["enabled"] = self.settings.image_hosts.image_box.enabled
            img_box_data["base_url"] = self.settings.image_hosts.image_box.base_url

            # only image
            only_image_data = self._ensure_toml_table(image_hosts, "only_image")
            only_image_data["enabled"] = self.settings.image_hosts.only_image.enabled
            only_image_data["base_url"] = self.settings.image_hosts.only_image.base_url
            only_image_data["api_key"] = self.settings.image_hosts.only_image.api_key

            # pixhost
            pixhost_data = self._ensure_toml_table(image_hosts, "pixhost")
            pixhost_data["enabled"] = self.settings.image_hosts.pixhost.enabled
            pixhost_data["base_url"] = self.settings.image_hosts.pixhost.base_url

            # lensdump
            lensdump_data = self._ensure_toml_table(image_hosts, "lensdump")
            lensdump_data["enabled"] = self.settings.image_hosts.lensdump.enabled
            lensdump_data["base_url"] = self.settings.image_hosts.lensdump.base_url
            lensdump_data["api_key"] = self.settings.image_hosts.lensdump.api_key

            # urls
            urls_settings = self._toml_table(self._toml_data, "urls")
            urls_settings["alt"] = self.settings.urls.alt
            urls_settings["columns"] = self.settings.urls.columns
            urls_settings["vertical"] = self.settings.urls.vertical
            urls_settings["horizontal"] = self.settings.urls.horizontal
            urls_settings["mode"] = self.settings.urls.mode
            urls_settings["type"] = URLType(self.settings.urls.type).value
            urls_settings["image_width"] = self.settings.urls.image_width
            urls_settings["urls_manual"] = self.settings.urls.manual

            # plugins
            plugins_settings = self._toml_table(self._toml_data, "plugins")
            plugins_settings["wizard_page"] = (
                self.settings.plugins.wizard_page
                if self.settings.plugins.wizard_page
                else ""
            )
            plugins_settings["token_replacer"] = (
                self.settings.plugins.token_replacer
                if self.settings.plugins.token_replacer
                else ""
            )
            plugins_settings["pre_upload"] = (
                self.settings.plugins.pre_upload
                if self.settings.plugins.pre_upload
                else ""
            )
            plugins_settings["post_upload"] = (
                self.settings.plugins.post_upload
                if self.settings.plugins.post_upload
                else ""
            )
            plugins_settings["metadata_transformer"] = (
                self.settings.plugins.metadata_transformer
                if self.settings.plugins.metadata_transformer
                else ""
            )
            plugins_settings["image_host_uploader"] = (
                self.settings.plugins.image_host_uploader
                if self.settings.plugins.image_host_uploader
                else ""
            )
            plugins_settings["duplicate_checker"] = (
                self.settings.plugins.duplicate_checker
                if self.settings.plugins.duplicate_checker
                else ""
            )

            # template settings
            template_settings = self._toml_table(self._toml_data, "template_settings")
            template_settings["block_syntax_color"] = (
                self.settings.templates.block_syntax_color
            )
            template_settings["variable_syntax_color"] = (
                self.settings.templates.variable_syntax_color
            )
            template_settings["comment_syntax_color"] = (
                self.settings.templates.comment_syntax_color
            )
            template_settings["warning_syntax_color"] = (
                self.settings.templates.warning_syntax_color
            )
            template_settings["trim_blocks"] = int(self.settings.templates.trim_blocks)
            template_settings["lstrip_blocks"] = int(
                self.settings.templates.lstrip_blocks
            )
            template_settings["newline_sequence"] = (
                self.settings.templates.newline_sequence
            )
            template_settings["keep_trailing_newline"] = int(
                self.settings.templates.keep_trailing_newline
            )

            # sandbox template setting
            template_settings["enable_sandbox_prompt_tokens"] = (
                self.settings.templates.enable_sandbox_prompt_tokens
            )

            # release notes
            release_notes = self._toml_table(self._toml_data, "release_notes")
            release_notes["enable_release_notes"] = self.settings.release_notes.enabled
            release_notes["last_used_release_note"] = (
                self.settings.release_notes.last_used
            )
            release_notes["notes"] = self.settings.release_notes.notes

            # widget settings
            widget_settings = self._toml_table(self._toml_data, "widget_settings")
            widget_settings["prompt_token_editor_warn_on_missing"] = (
                self.settings.widgets.prompt_token_editor_warn_on_missing
            )

            if not save_path and self.program.current_config:
                save_path = self.paths.user_configs / (
                    self.program.current_config + ".toml"
                )
            if not save_path:
                raise ConfigError("Failed to determine save path")

            serialized = self.codec.dumps(self._toml_data)
            if (
                serialized != self._config_snapshot
                or save_path != self._active_profile_path
                or not save_path.exists()
            ):
                atomic_write_text(save_path, serialized)
                self._config_snapshot = serialized
                self._active_profile_path = save_path

        except Exception as e:
            raise ConfigError(f"Error saving config file: {str(e)}") from e

    def decode(
        self,
        toml_data: Mapping[str, Any],
        build_defaults: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Assigns config payload attributes from a given toml document.

        When ``dry_run`` is True, the document is fully decoded and
        validated (including ``validate_settings``) but the resulting
        payload is discarded instead of being assigned to
        ``self.settings``/``self.defaults``. This lets a caller prove a
        document is fully valid -- exactly as a real decode would -- without
        mutating manager state; used to validate a migrated schema-1->2
        document before it is ever persisted.
        """
        try:
            self.codec.validate_schema(toml_data)
            # general
            general_data = self._toml_mapping(toml_data, "general")
            nfo_forge_theme = NfoForgeTheme(general_data.get("nfo_forge_theme", 1))

            # dependencies
            dependencies_data = self._toml_mapping(toml_data, "dependencies")
            ffmpeg = (
                Path(dependencies_data["ffmpeg"])
                if dependencies_data["ffmpeg"]
                else None
            )
            ffprobe = (
                Path(dependencies_data["ffprobe"])
                if dependencies_data["ffprobe"]
                else None
            )
            frame_forge = (
                Path(dependencies_data["frame_forge"])
                if dependencies_data["frame_forge"]
                else None
            )
            mkbrr = (
                Path(dependencies_data["mkbrr"]) if dependencies_data["mkbrr"] else None
            )

            # trackers
            tracker_data = self._toml_mapping(toml_data, "tracker")

            # tracker settings
            tracker_settings = tracker_data["settings"]

            # tracker order
            tracker_order = [
                TrackerSelection(x)
                for x in tracker_settings.get("tracker_order", [])
                if x in TrackerSelection._value2member_map_
            ]
            tracker_order.extend(e for e in TrackerSelection if e not in tracker_order)
            last_used_img_host: dict[TrackerSelection, ImageHost | ImageSource] = {}
            for tracker, image_dest in tracker_settings.get(
                "last_used_img_host", {}
            ).items():
                try:
                    tracker_selection = TrackerSelection(tracker)
                except (TypeError, ValueError):
                    continue

                try:
                    last_used_img_host[tracker_selection] = ImageHost(image_dest)
                except (TypeError, ValueError):
                    try:
                        last_used_img_host[tracker_selection] = ImageSource(image_dest)
                    except (TypeError, ValueError):
                        # A removed or future image destination must not make
                        # an otherwise valid profile un-loadable.
                        continue

            # tracker data
            tl_tracker_data = tracker_data["torrent_leech"]
            tl_tracker = TorrentLeechInfo(
                upload_enabled=tl_tracker_data["upload_enabled"],
                announce_url=tl_tracker_data["announce_url"],
                enabled=tl_tracker_data["enabled"],
                source=tl_tracker_data["source"],
                comments=tl_tracker_data["comments"],
                nfo_template=tl_tracker_data["nfo_template"],
                url_type=URLType(tl_tracker_data["url_type"]),
                column_s=tl_tracker_data["column_s"],
                column_space=tl_tracker_data["column_space"],
                row_space=tl_tracker_data["row_space"],
                mvr_title_override_enabled=tl_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    tl_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=tl_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=tl_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(tl_tracker_data),
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
                url_type=URLType(bhd_tracker_data["url_type"]),
                column_s=bhd_tracker_data["column_s"],
                column_space=bhd_tracker_data["column_space"],
                row_space=bhd_tracker_data["row_space"],
                mvr_title_override_enabled=bhd_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    bhd_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=bhd_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=bhd_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(bhd_tracker_data),
                anonymous=bhd_tracker_data["anonymous"],
                api_key=bhd_tracker_data["api_key"],
                rss_key=bhd_tracker_data["rss_key"],
                promo=BHDPromo(bhd_tracker_data["promo"]),
                live_release=BHDLiveRelease(bhd_tracker_data["live_release"]),
                internal=bhd_tracker_data["internal"],
                image_width=bhd_tracker_data["image_width"],
                add_localization_to_custom_edition=bhd_tracker_data[
                    "add_localization_to_custom_edition"
                ],
                stream_optimized=bhd_tracker_data["stream_optimized"],
            )

            ptp_tracker_data = tracker_data["pass_the_popcorn"]
            ptp_tracker = PassThePopcornInfo(
                upload_enabled=ptp_tracker_data["upload_enabled"],
                announce_url=ptp_tracker_data["announce_url"],
                enabled=ptp_tracker_data["enabled"],
                source=ptp_tracker_data["source"],
                comments=ptp_tracker_data["comments"],
                nfo_template=ptp_tracker_data["nfo_template"],
                url_type=URLType(ptp_tracker_data["url_type"]),
                column_s=ptp_tracker_data["column_s"],
                column_space=ptp_tracker_data["column_space"],
                row_space=ptp_tracker_data["row_space"],
                mvr_title_override_enabled=ptp_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    ptp_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=ptp_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=ptp_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(ptp_tracker_data),
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
                url_type=URLType(rf_tracker_data["url_type"]),
                column_s=rf_tracker_data["column_s"],
                column_space=rf_tracker_data["column_space"],
                row_space=rf_tracker_data["row_space"],
                mvr_title_override_enabled=rf_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    rf_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=rf_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=rf_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(rf_tracker_data),
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
                url_type=URLType(aither_tracker_data["url_type"]),
                column_s=aither_tracker_data["column_s"],
                column_space=aither_tracker_data["column_space"],
                row_space=aither_tracker_data["row_space"],
                mvr_title_override_enabled=aither_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    aither_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=aither_tracker_data[
                    "mvr_title_token_override"
                ],
                mvr_title_replace_map=aither_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(
                    aither_tracker_data
                ),
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

            huno_tracker_data = tracker_data["huno"]
            huno_tracker = HunoInfo(
                upload_enabled=huno_tracker_data["upload_enabled"],
                announce_url=huno_tracker_data["announce_url"],
                enabled=huno_tracker_data["enabled"],
                source=huno_tracker_data["source"],
                comments=huno_tracker_data["comments"],
                nfo_template=huno_tracker_data["nfo_template"],
                url_type=URLType(huno_tracker_data["url_type"]),
                column_s=huno_tracker_data["column_s"],
                column_space=huno_tracker_data["column_space"],
                row_space=huno_tracker_data["row_space"],
                mvr_title_override_enabled=huno_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    huno_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=huno_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=huno_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(
                    huno_tracker_data
                ),
                api_key=huno_tracker_data["api_key"],
                anonymous=huno_tracker_data["anonymous"],
                internal=huno_tracker_data["internal"],
                stream_optimized=huno_tracker_data["stream_optimized"],
                image_width=huno_tracker_data["image_width"],
            )

            lst_tracker_data = tracker_data["lst"]
            lst_tracker = LSTInfo(
                upload_enabled=lst_tracker_data["upload_enabled"],
                announce_url=lst_tracker_data["announce_url"],
                enabled=lst_tracker_data["enabled"],
                source=lst_tracker_data["source"],
                comments=lst_tracker_data["comments"],
                nfo_template=lst_tracker_data["nfo_template"],
                url_type=URLType(lst_tracker_data["url_type"]),
                column_s=lst_tracker_data["column_s"],
                column_space=lst_tracker_data["column_space"],
                row_space=lst_tracker_data["row_space"],
                mvr_title_override_enabled=lst_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    lst_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=lst_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=lst_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(lst_tracker_data),
                api_key=lst_tracker_data["api_key"],
                anonymous=lst_tracker_data["anonymous"],
                internal=lst_tracker_data["internal"],
                personal_release=lst_tracker_data["personal_release"],
                mod_queue_opt_in=lst_tracker_data["mod_queue_opt_in"],
                draft_queue_opt_in=lst_tracker_data["draft_queue_opt_in"],
                featured=lst_tracker_data["featured"],
                free=int(lst_tracker_data["free"]),
                double_up=lst_tracker_data["double_up"],
                sticky=lst_tracker_data["sticky"],
                image_width=lst_tracker_data["image_width"],
            )

            darkpeers_tracker_data = tracker_data["dark_peers"]
            darkpeers_tracker = DarkPeersInfo(
                upload_enabled=darkpeers_tracker_data["upload_enabled"],
                announce_url=darkpeers_tracker_data["announce_url"],
                enabled=darkpeers_tracker_data["enabled"],
                source=darkpeers_tracker_data["source"],
                comments=darkpeers_tracker_data["comments"],
                nfo_template=darkpeers_tracker_data["nfo_template"],
                url_type=URLType(darkpeers_tracker_data["url_type"]),
                column_s=darkpeers_tracker_data["column_s"],
                column_space=darkpeers_tracker_data["column_space"],
                row_space=darkpeers_tracker_data["row_space"],
                mvr_title_override_enabled=darkpeers_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    darkpeers_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=darkpeers_tracker_data[
                    "mvr_title_token_override"
                ],
                mvr_title_replace_map=darkpeers_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(
                    darkpeers_tracker_data
                ),
                api_key=darkpeers_tracker_data["api_key"],
                anonymous=darkpeers_tracker_data["anonymous"],
                internal=darkpeers_tracker_data["internal"],
                personal_release=darkpeers_tracker_data["personal_release"],
                image_width=darkpeers_tracker_data["image_width"],
            )

            shri_tracker_data = tracker_data["shareisland"]
            shri_tracker = ShareIslandInfo(
                upload_enabled=shri_tracker_data["upload_enabled"],
                announce_url=shri_tracker_data["announce_url"],
                enabled=shri_tracker_data["enabled"],
                source=shri_tracker_data["source"],
                comments=shri_tracker_data["comments"],
                nfo_template=shri_tracker_data["nfo_template"],
                url_type=URLType(shri_tracker_data["url_type"]),
                column_s=shri_tracker_data["column_s"],
                column_space=shri_tracker_data["column_space"],
                row_space=shri_tracker_data["row_space"],
                mvr_title_override_enabled=shri_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    shri_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=shri_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=shri_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(
                    shri_tracker_data
                ),
                api_key=shri_tracker_data["api_key"],
                anonymous=shri_tracker_data["anonymous"],
                internal=shri_tracker_data["internal"],
                personal_release=shri_tracker_data["personal_release"],
                opt_in_to_mod_queue=shri_tracker_data["opt_in_to_mod_queue"],
                image_width=shri_tracker_data["image_width"],
            )

            ulcx_tracker_data = tracker_data["uploadcx"]
            ulcx_tracker = UploadCXInfo(
                upload_enabled=ulcx_tracker_data["upload_enabled"],
                announce_url=ulcx_tracker_data["announce_url"],
                enabled=ulcx_tracker_data["enabled"],
                source=ulcx_tracker_data["source"],
                comments=ulcx_tracker_data["comments"],
                nfo_template=ulcx_tracker_data["nfo_template"],
                url_type=URLType(ulcx_tracker_data["url_type"]),
                column_s=ulcx_tracker_data["column_s"],
                column_space=ulcx_tracker_data["column_space"],
                row_space=ulcx_tracker_data["row_space"],
                mvr_title_override_enabled=ulcx_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    ulcx_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=ulcx_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=ulcx_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(
                    ulcx_tracker_data
                ),
                api_key=ulcx_tracker_data["api_key"],
                anonymous=ulcx_tracker_data["anonymous"],
                internal=ulcx_tracker_data["internal"],
                personal_release=ulcx_tracker_data["personal_release"],
                image_width=ulcx_tracker_data["image_width"],
            )

            oe_tracker_data = tracker_data["only_encodes"]
            oe_tracker = OnlyEncodesInfo(
                upload_enabled=oe_tracker_data["upload_enabled"],
                announce_url=oe_tracker_data["announce_url"],
                enabled=oe_tracker_data["enabled"],
                source=oe_tracker_data["source"],
                comments=oe_tracker_data["comments"],
                nfo_template=oe_tracker_data["nfo_template"],
                url_type=URLType(oe_tracker_data["url_type"]),
                column_s=oe_tracker_data["column_s"],
                column_space=oe_tracker_data["column_space"],
                row_space=oe_tracker_data["row_space"],
                mvr_title_override_enabled=oe_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    oe_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=oe_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=oe_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(oe_tracker_data),
                api_key=oe_tracker_data["api_key"],
                anonymous=oe_tracker_data["anonymous"],
                internal=oe_tracker_data["internal"],
                personal_release=oe_tracker_data["personal_release"],
                image_width=oe_tracker_data["image_width"],
            )

            hdb_tracker_data = tracker_data["hdb"]
            hdb_tracker = HDBInfo(
                upload_enabled=hdb_tracker_data["upload_enabled"],
                announce_url=hdb_tracker_data["announce_url"],
                enabled=hdb_tracker_data["enabled"],
                source=hdb_tracker_data["source"],
                comments=hdb_tracker_data["comments"],
                nfo_template=hdb_tracker_data["nfo_template"],
                url_type=URLType(hdb_tracker_data["url_type"]),
                column_s=hdb_tracker_data["column_s"],
                column_space=hdb_tracker_data["column_space"],
                row_space=hdb_tracker_data["row_space"],
                mvr_title_override_enabled=hdb_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    hdb_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=hdb_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=hdb_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(hdb_tracker_data),
                username=hdb_tracker_data["username"],
                passkey=hdb_tracker_data["passkey"],
                session_cookie=hdb_tracker_data["session_cookie"],
                internal=hdb_tracker_data["internal"],
                image_width=hdb_tracker_data["image_width"],
            )

            blutopia_tracker_data = tracker_data["blutopia"]
            blutopia_tracker = BlutopiaInfo(
                upload_enabled=blutopia_tracker_data["upload_enabled"],
                announce_url=blutopia_tracker_data["announce_url"],
                enabled=blutopia_tracker_data["enabled"],
                source=blutopia_tracker_data["source"],
                comments=blutopia_tracker_data["comments"],
                nfo_template=blutopia_tracker_data["nfo_template"],
                url_type=URLType(blutopia_tracker_data["url_type"]),
                column_s=blutopia_tracker_data["column_s"],
                column_space=blutopia_tracker_data["column_space"],
                row_space=blutopia_tracker_data["row_space"],
                mvr_title_override_enabled=blutopia_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    blutopia_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=blutopia_tracker_data[
                    "mvr_title_token_override"
                ],
                mvr_title_replace_map=blutopia_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(
                    blutopia_tracker_data
                ),
                api_key=blutopia_tracker_data["api_key"],
                anonymous=blutopia_tracker_data["anonymous"],
                internal=blutopia_tracker_data["internal"],
                personal_release=blutopia_tracker_data["personal_release"],
                opt_in_to_mod_queue=blutopia_tracker_data["opt_in_to_mod_queue"],
                image_width=blutopia_tracker_data["image_width"],
            )

            seedpool_tracker_data = tracker_data["seedpool"]
            seedpool_tracker = SeedPoolInfo(
                upload_enabled=seedpool_tracker_data["upload_enabled"],
                announce_url=seedpool_tracker_data["announce_url"],
                enabled=seedpool_tracker_data["enabled"],
                source=seedpool_tracker_data["source"],
                comments=seedpool_tracker_data["comments"],
                nfo_template=seedpool_tracker_data["nfo_template"],
                url_type=URLType(seedpool_tracker_data["url_type"]),
                column_s=seedpool_tracker_data["column_s"],
                column_space=seedpool_tracker_data["column_space"],
                row_space=seedpool_tracker_data["row_space"],
                mvr_title_override_enabled=seedpool_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    seedpool_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=seedpool_tracker_data[
                    "mvr_title_token_override"
                ],
                mvr_title_replace_map=seedpool_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(
                    seedpool_tracker_data
                ),
                api_key=seedpool_tracker_data["api_key"],
                anonymous=seedpool_tracker_data["anonymous"],
                internal=seedpool_tracker_data["internal"],
                personal_release=seedpool_tracker_data["personal_release"],
                image_width=seedpool_tracker_data["image_width"],
            )

            utp_tracker_data = tracker_data["utp"]
            utp_tracker = UTPInfo(
                upload_enabled=utp_tracker_data["upload_enabled"],
                announce_url=utp_tracker_data["announce_url"],
                enabled=utp_tracker_data["enabled"],
                source=utp_tracker_data["source"],
                comments=utp_tracker_data["comments"],
                nfo_template=utp_tracker_data["nfo_template"],
                url_type=URLType(utp_tracker_data["url_type"]),
                column_s=utp_tracker_data["column_s"],
                column_space=utp_tracker_data["column_space"],
                row_space=utp_tracker_data["row_space"],
                mvr_title_override_enabled=utp_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    utp_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=utp_tracker_data["mvr_title_token_override"],
                mvr_title_replace_map=utp_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(utp_tracker_data),
                api_key=utp_tracker_data["api_key"],
                anonymous=utp_tracker_data["anonymous"],
                internal=utp_tracker_data["internal"],
                personal_release=utp_tracker_data["personal_release"],
                image_width=utp_tracker_data["image_width"],
            )

            yuscene_tracker_data = tracker_data["yuscene"]
            yuscene_tracker = YuSceneInfo(
                upload_enabled=yuscene_tracker_data["upload_enabled"],
                announce_url=yuscene_tracker_data["announce_url"],
                enabled=yuscene_tracker_data["enabled"],
                source=yuscene_tracker_data["source"],
                comments=yuscene_tracker_data["comments"],
                nfo_template=yuscene_tracker_data["nfo_template"],
                url_type=URLType(yuscene_tracker_data["url_type"]),
                column_s=yuscene_tracker_data["column_s"],
                column_space=yuscene_tracker_data["column_space"],
                row_space=yuscene_tracker_data["row_space"],
                mvr_title_override_enabled=yuscene_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    yuscene_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=yuscene_tracker_data[
                    "mvr_title_token_override"
                ],
                mvr_title_replace_map=yuscene_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(
                    yuscene_tracker_data
                ),
                api_key=yuscene_tracker_data["api_key"],
                anonymous=yuscene_tracker_data["anonymous"],
                internal=yuscene_tracker_data["internal"],
                personal_release=yuscene_tracker_data["personal_release"],
                image_width=yuscene_tracker_data["image_width"],
            )

            fearnopeer_tracker_data = tracker_data["fearnopeer"]
            fearnopeer_tracker = FearNoPeerInfo(
                upload_enabled=fearnopeer_tracker_data["upload_enabled"],
                announce_url=fearnopeer_tracker_data["announce_url"],
                enabled=fearnopeer_tracker_data["enabled"],
                source=fearnopeer_tracker_data["source"],
                comments=fearnopeer_tracker_data["comments"],
                nfo_template=fearnopeer_tracker_data["nfo_template"],
                url_type=URLType(fearnopeer_tracker_data["url_type"]),
                column_s=fearnopeer_tracker_data["column_s"],
                column_space=fearnopeer_tracker_data["column_space"],
                row_space=fearnopeer_tracker_data["row_space"],
                mvr_title_override_enabled=fearnopeer_tracker_data[
                    "mvr_title_override_enabled"
                ],
                mvr_title_colon_replace=ColonReplace(
                    fearnopeer_tracker_data["mvr_title_colon_replace"]
                ),
                mvr_title_token_override=fearnopeer_tracker_data[
                    "mvr_title_token_override"
                ],
                mvr_title_replace_map=fearnopeer_tracker_data["mvr_title_replace_map"],
                tvr_title_overrides=self._load_series_title_overrides(
                    fearnopeer_tracker_data
                ),
                api_key=fearnopeer_tracker_data["api_key"],
                anonymous=fearnopeer_tracker_data["anonymous"],
                internal=fearnopeer_tracker_data["internal"],
                personal_release=fearnopeer_tracker_data["personal_release"],
                image_width=fearnopeer_tracker_data["image_width"],
            )

            # torrent clients
            torrent_client_data = self._toml_mapping(toml_data, "torrent_client")

            # qbittorrent
            qbittorrent_data = cast(dict[str, Any], torrent_client_data["qbittorrent"])
            qbit_specific = cast(dict[str, Any], qbittorrent_data["specific_params"])
            try:
                qbit_save_path_mode = QBittorrentSavePathMode(
                    qbit_specific["save_path_mode"]
                )
            except ValueError as error:
                raise ConfigError(
                    "Invalid configuration value at "
                    "torrent_client.qbittorrent.specific_params.save_path_mode"
                ) from error
            qbittorrent = QBittorrentConfig(
                enabled=bool(qbittorrent_data["enabled"]),
                host=str(qbittorrent_data["host"]),
                port=int(qbittorrent_data["port"]),
                user=str(qbittorrent_data["user"]),
                password=str(qbittorrent_data["password"]),
                category=str(qbit_specific["category"]),
                super_seeding=bool(qbit_specific["super_seeding"]),
                save_path_mode=qbit_save_path_mode,
                save_path_template=str(qbit_specific["save_path_template"]),
            )

            # deluge
            deluge_data = cast(dict[str, Any], torrent_client_data["deluge"])
            deluge_specific = cast(dict[str, Any], deluge_data["specific_params"])
            deluge = DelugeConfig(
                enabled=bool(deluge_data["enabled"]),
                host=str(deluge_data["host"]),
                port=int(deluge_data["port"]),
                user=str(deluge_data["user"]),
                password=str(deluge_data["password"]),
                label=str(deluge_specific["label"]),
                path=str(deluge_specific["path"]),
            )

            # rtorrent
            rtorrent_data = cast(dict[str, Any], torrent_client_data["rtorrent"])
            rtorrent_specific = cast(dict[str, Any], rtorrent_data["specific_params"])
            rtorrent = RTorrentConfig(
                enabled=bool(rtorrent_data["enabled"]),
                host=str(rtorrent_data["host"]),
                port=int(rtorrent_data["port"]),
                user=str(rtorrent_data["user"]),
                password=str(rtorrent_data["password"]),
                label=str(rtorrent_specific["label"]),
                path=str(rtorrent_specific["path"]),
                verify_tls=bool(rtorrent_specific.get("verify_tls", True)),
                ca_bundle=str(rtorrent_specific.get("ca_bundle", "")),
            )

            # transmission
            transmission_data = cast(
                dict[str, Any], torrent_client_data["transmission"]
            )
            transmission_specific = cast(
                dict[str, Any], transmission_data["specific_params"]
            )
            transmission = TransmissionConfig(
                enabled=bool(transmission_data["enabled"]),
                host=str(transmission_data["host"]),
                port=int(transmission_data["port"]),
                user=str(transmission_data["user"]),
                password=str(transmission_data["password"]),
                label=str(transmission_specific["label"]),
                path=str(transmission_specific["path"]),
            )

            # watch folder
            watch_folder = WatchFolder(**self._toml_mapping(toml_data, "watch_folder"))

            # movie management
            movie_management = self._toml_mapping(toml_data, "movie_management")

            # series management
            series_management = self._toml_mapping(toml_data, "series_management")

            def load_series_token(key: str) -> str:
                value = str(series_management[key])
                if not value.strip():
                    raise ConfigError(
                        f"Configuration value cannot be blank: series_management.{key}"
                    )
                return value

            # global management
            global_management = self._toml_mapping(toml_data, "global_management")

            # user token data
            user_token_data = self._toml_mapping(toml_data, "user_tokens")

            # screenshots
            screen_shot_data = self._toml_mapping(toml_data, "screenshots")

            # image hosts
            image_hosts = self._toml_mapping(toml_data, "image_hosts")

            # hosts
            chevereto_v3 = CheveretoV3Payload(**image_hosts["chevereto_v3"])
            chevereto_v4 = CheveretoV4Payload(**image_hosts["chevereto_v4"])
            image_bb = ImageBBPayload(**image_hosts["image_bb"])
            image_box = ImageBoxPayload(**image_hosts["image_box"])
            only_image = OnlyImagePayload(**image_hosts["only_image"])
            pixhost = PixhostPayload(**image_hosts["pixhost"])
            lensdump = LensdumpPayload(**image_hosts["lensdump"])

            # urls
            urls_settings = self._toml_mapping(toml_data, "urls")

            # plugins
            plugins_settings = self._toml_mapping(toml_data, "plugins")

            # template settings
            template_settings = self._toml_mapping(toml_data, "template_settings")

            # release notes
            release_notes = self._toml_mapping(toml_data, "release_notes")

            # widget settings
            widget_settings = self._toml_mapping(toml_data, "widget_settings")

            # build payload
            dynamic_range = global_management["video_dynamic_range"]
            config_payload = AppConfig(
                general=GeneralSettings(
                    ui_suffix=str(general_data["ui_suffix"]),
                    ui_scale_factor=float(general_data["ui_scale_factor"]),
                    theme=nfo_forge_theme,
                    enable_plugins=bool(general_data["enable_plugins"]),
                    releasers_name=str(general_data["releasers_name"]),
                    tmdb_language=str(general_data["tmdb_language"]),
                    media_search_mode=MediaSearchMode(
                        general_data["media_search_mode"]
                    ),
                    timeout=int(general_data["timeout"]),
                    enable_prompt_overview=bool(general_data["enable_prompt_overview"]),
                    enable_mkbrr=bool(general_data["enable_mkbrr"]),
                    log_level=LogLevel(general_data["log_level"]),
                    log_total=int(general_data["log_total"]),
                    working_dir=Path(general_data["working_dir"])
                    if general_data["working_dir"]
                    else self.paths.default_working_dir(ensure_exists=True),
                ),
                api_keys=ApiKeysSettings(
                    tmdb_api_key=str(
                        toml_data.get("api_keys", {}).get("tmdb_api_key", "")
                    )
                ),
                dependencies=DependencySettings(
                    ffmpeg=ffmpeg,
                    ffprobe=ffprobe,
                    frame_forge=frame_forge,
                    mkbrr=mkbrr,
                ),
                trackers=TrackerSettings(
                    order=tracker_order,
                    last_used_image_host=last_used_img_host,
                    torrent_leech=tl_tracker,
                    beyond_hd=bhd_tracker,
                    pass_the_popcorn=ptp_tracker,
                    reelflix=rf_tracker,
                    aither=aither_tracker,
                    huno=huno_tracker,
                    lst=lst_tracker,
                    dark_peers=darkpeers_tracker,
                    share_island=shri_tracker,
                    upload_cx=ulcx_tracker,
                    only_encodes=oe_tracker,
                    hdb=hdb_tracker,
                    blutopia=blutopia_tracker,
                    seedpool=seedpool_tracker,
                    utp=utp_tracker,
                    yuscene=yuscene_tracker,
                    fearnopeer=fearnopeer_tracker,
                ),
                torrent_clients=TorrentClientSettings(
                    qbittorrent=qbittorrent,
                    deluge=deluge,
                    rtorrent=rtorrent,
                    transmission=transmission,
                    watch_folder=watch_folder,
                ),
                movie=MovieSettings(
                    enabled=bool(movie_management["mvr_enabled"]),
                    filename_colon_replace=ColonReplace(
                        movie_management["mvr_colon_replace_filename"]
                    ),
                    title_colon_replace=ColonReplace(
                        movie_management["mvr_colon_replace_title"]
                    ),
                    claims=_load_claims(movie_management, "mvr"),
                    filename_token=str(movie_management["mvr_token"]),
                    title_token=str(movie_management["mvr_title_token"]),
                    release_group=str(movie_management["mvr_release_group"]),
                ),
                series=SeriesSettings(
                    enabled=bool(series_management["tvr_enabled"]),
                    filename_colon_replace=ColonReplace(
                        series_management["tvr_colon_replace_filename"]
                    ),
                    title_colon_replace=ColonReplace(
                        series_management["tvr_colon_replace_title"]
                    ),
                    claims=_load_claims(series_management, "tvr"),
                    standard_episode_token=load_series_token(
                        "tvr_standard_episode_token"
                    ),
                    daily_episode_token=load_series_token("tvr_daily_episode_token"),
                    anime_episode_token=load_series_token("tvr_anime_episode_token"),
                    season_folder_token=str(
                        series_management["tvr_season_folder_token"]
                    ),
                    # `.get`: this key was added after release, and a profile
                    # written before it is still valid -- an absent value means
                    # "fall back to the season folder token", which is also the
                    # packaged default.
                    season_subfolder_token=str(
                        series_management.get("tvr_season_subfolder_token", "")
                    ),
                    multi_episode_style=MultiEpisodeStyle(
                        series_management["tvr_multi_episode_style"]
                    ),
                    standard_title_token=load_series_token("tvr_standard_title_token"),
                    daily_title_token=load_series_token("tvr_daily_title_token"),
                    anime_title_token=load_series_token("tvr_anime_title_token"),
                    release_group=str(series_management["tvr_release_group"]),
                ),
                global_management=GlobalManagementSettings(
                    title_clean_rules=[
                        (str(rule[0]), str(rule[1]))
                        for rule in global_management["title_clean_rules"]
                    ],
                    title_clean_rules_modified=bool(
                        global_management["title_clean_rules_modified"]
                    ),
                    video_dynamic_range=DynamicRangeSettings(
                        resolutions={
                            cast(ResolutionKey, str(key)): bool(value)
                            for key, value in dynamic_range["resolutions"].items()
                        },
                        hdr_types={
                            cast(HdrType, str(key)): bool(value)
                            for key, value in dynamic_range["hdr_types"].items()
                        },
                        custom_strings={
                            cast(HdrType, str(key)): str(value)
                            for key, value in dynamic_range["custom_strings"].items()
                        },
                    ),
                ),
                user_tokens=UserTokenSettings(
                    tokens={
                        str(key): (str(value[0]), TokenSelection(value[1]))
                        for key, value in user_token_data["tokens"].items()
                    }
                ),
                screenshots=ScreenshotSettings(
                    crop_mode=Cropping(screen_shot_data["crop_mode"]),
                    enabled=bool(screen_shot_data["screenshots_enabled"]),
                    count=int(screen_shot_data["screen_shot_count"]),
                    min_required_selected=int(
                        screen_shot_data["min_required_selected_screens"]
                    ),
                    max_required_selected=int(
                        screen_shot_data["max_required_selected_screens"]
                    ),
                    mode=ScreenShotMode(screen_shot_data["ss_mode"]),
                    subtitle_height_720=int(screen_shot_data["sub_size_height_720"]),
                    subtitle_height_1080=int(screen_shot_data["sub_size_height_1080"]),
                    subtitle_height_2160=int(screen_shot_data["sub_size_height_2160"]),
                    subtitle_alignment=SubtitleAlignment(
                        screen_shot_data["subtitle_alignment"]
                    ),
                    subtitle_color=str(screen_shot_data["subtitle_color"]),
                    subtitle_outline_color=str(
                        screen_shot_data["subtitle_outline_color"]
                    ),
                    trim_start=int(screen_shot_data["trim_start"]),
                    trim_end=int(screen_shot_data["trim_end"]),
                    comparison_subtitles=bool(screen_shot_data["comparison_subtitles"]),
                    comparison_source_name=str(
                        screen_shot_data["comparison_subtitle_source_name"]
                    ),
                    comparison_encode_name=str(
                        screen_shot_data["comparison_subtitle_encode_name"]
                    ),
                    optimize_generated_images=bool(
                        screen_shot_data["optimize_generated_images"]
                    ),
                    optimize_downloaded_images=bool(
                        screen_shot_data["optimize_dl_url_images"]
                    ),
                    optimize_downloaded_images_percentage=float(
                        screen_shot_data["optimize_dl_url_images_percentage"]
                    ),
                    indexer=Indexer(screen_shot_data["indexer"]),
                    image_plugin=ImagePlugin(screen_shot_data["image_plugin"]),
                ),
                image_hosts=ImageHostSettings(
                    chevereto_v3=chevereto_v3,
                    chevereto_v4=chevereto_v4,
                    image_bb=image_bb,
                    image_box=image_box,
                    only_image=only_image,
                    pixhost=pixhost,
                    lensdump=lensdump,
                ),
                urls=UrlSettings(
                    alt=str(urls_settings["alt"]),
                    columns=int(urls_settings["columns"]),
                    vertical=int(urls_settings["vertical"]),
                    horizontal=int(urls_settings["horizontal"]),
                    mode=int(urls_settings["mode"]),
                    type=URLType(urls_settings["type"]),
                    image_width=int(urls_settings["image_width"]),
                    manual=int(urls_settings["urls_manual"]),
                ),
                plugins=PluginSettings(
                    wizard_page=str(plugins_settings["wizard_page"]) or None,
                    token_replacer=str(plugins_settings["token_replacer"]) or None,
                    pre_upload=str(plugins_settings["pre_upload"]) or None,
                    post_upload=str(plugins_settings["post_upload"]) or None,
                    metadata_transformer=str(plugins_settings["metadata_transformer"])
                    or None,
                    image_host_uploader=str(plugins_settings["image_host_uploader"])
                    or None,
                    duplicate_checker=str(plugins_settings["duplicate_checker"])
                    or None,
                ),
                templates=TemplateSettings(
                    block_syntax_color=str(template_settings["block_syntax_color"]),
                    variable_syntax_color=str(
                        template_settings["variable_syntax_color"]
                    ),
                    comment_syntax_color=str(template_settings["comment_syntax_color"]),
                    warning_syntax_color=str(template_settings["warning_syntax_color"]),
                    trim_blocks=bool(template_settings["trim_blocks"]),
                    lstrip_blocks=bool(template_settings["lstrip_blocks"]),
                    newline_sequence=str(template_settings["newline_sequence"]),
                    keep_trailing_newline=bool(
                        template_settings["keep_trailing_newline"]
                    ),
                    enable_sandbox_prompt_tokens=bool(
                        template_settings["enable_sandbox_prompt_tokens"]
                    ),
                ),
                release_notes=ReleaseNoteSettings(
                    enabled=bool(release_notes["enable_release_notes"]),
                    last_used=str(release_notes["last_used_release_note"]),
                    notes={
                        str(key): str(value)
                        for key, value in release_notes["notes"].items()
                    },
                ),
                widgets=WidgetSettings(
                    prompt_token_editor_warn_on_missing=bool(
                        widget_settings["prompt_token_editor_warn_on_missing"]
                    )
                ),
            )

            # validate before ever assigning to instance state
            self.codec.validate_settings(config_payload)
            if dry_run:
                return

            # check where to store the built payload
            if build_defaults:
                self.defaults = config_payload
            else:
                self.settings = config_payload

        except Exception as e:
            raise ConfigError(f"Error parsing config file: {str(e)}") from e

    @staticmethod
    def resolve_dependency(path_attr: Path | None) -> str:
        """Ensure that we're returning a toml safe string to save the paths"""
        if path_attr:
            return str(Path(path_attr))
        else:
            return ""

    @staticmethod
    def _serialize_series_title_overrides(
        tracker_info: TrackerInfo,
    ) -> dict[str, dict[str, Any]]:
        overrides: dict[str, dict[str, Any]] = {}
        existing = tracker_info.tvr_title_overrides or {}
        for episode_format in SUPPORTED_TVR_FORMATS:
            override = existing.get(episode_format, TitleOverridePayload())
            overrides[str(episode_format).lower()] = {
                "enabled": override.enabled,
                "colon_replace": ColonReplace(override.colon_replace).value,
                "token": override.token,
                "replace_map": override.replace_map or [],
            }
        return overrides

    @staticmethod
    def _load_series_title_overrides(
        tracker_data: Mapping[str, Any],
    ) -> dict[EpisodeFormat, TitleOverridePayload]:
        override_data = cast(
            Mapping[str, Any], tracker_data.get("tvr_title_overrides", {})
        )
        overrides: dict[EpisodeFormat, TitleOverridePayload] = {}
        for episode_format in SUPPORTED_TVR_FORMATS:
            key = str(episode_format).lower()
            data = cast(Mapping[str, Any], override_data.get(key, {}))
            overrides[episode_format] = TitleOverridePayload(
                enabled=bool(data.get("enabled", False)),
                colon_replace=ColonReplace(data.get("colon_replace", 3)),
                token=data.get("token", ""),
                replace_map=data.get("replace_map", []),
            )
        return overrides
