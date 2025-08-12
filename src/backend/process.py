import asyncio
from collections.abc import Callable
from pathlib import Path
import shutil
import traceback
from typing import Any, Sequence

from PySide6.QtCore import SignalInstance
from pymediainfo import MediaInfo
from torf import Torrent

from src.backend.image_host_uploading.base_image_host import BaseImageHostUploader
from src.backend.image_host_uploading.chevereto_v3 import CheveretoV3Uploader
from src.backend.image_host_uploading.chevereto_v4 import CheveretoV4Uploader
from src.backend.image_host_uploading.img_box import ImageBoxUploader
from src.backend.image_host_uploading.img_downloader import ImageDownloader
from src.backend.image_host_uploading.img_uploader import ImageUploader
from src.backend.image_host_uploading.imgbb import ImageBBUploader
from src.backend.image_host_uploading.ptpimg import PTPIMGUploader
from src.backend.template_selector import TemplateSelectorBackEnd
from src.backend.token_replacer import TokenReplacer, UnfilledTokenRemoval
from src.backend.tokens import FileToken, TokenSelection
from src.backend.torrent_clients.deluge import DelugeClient
from src.backend.torrent_clients.qbittorrent import QBittorrentClient
from src.backend.torrent_clients.rtorrent import RTorrentClient
from src.backend.torrent_clients.transmission import TransmissionClient
from src.backend.torrents import (
    clone_torrent,
    generate_torrent,
    mkbrr_generate_torrent,
    write_torrent,
)
from src.backend.trackers import (
    AitherSearch,
    BHDSearch,
    DarkPeersSearch,
    HunoSearch,
    LSTSearch,
    MTVSearch,
    PTPSearch,
    ReelFlixSearch,
    ShareIslandSearch,
    TLSearch,
    aither_uploader,
    bhd_uploader,
    dp_uploader,
    huno_uploader,
    lst_uploader,
    mtv_uploader,
    ptp_uploader,
    rf_uploader,
    shri_uploader,
    tl_upload,
)
from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.morethantv import MTVUploader
from src.backend.trackers.torrentleech import TLUploader
from src.backend.trackers.unit3d_base import Unit3dBaseUploader
from src.backend.trackers.utils import format_image_tag
from src.backend.utils.image_optimizer import MultiProcessImageOptimizer
from src.backend.utils.images import (
    format_image_data_to_comparison,
    format_image_data_to_str,
    get_parity_images,
    get_parity_images_to_str,
)
from src.backend.utils.token_utils import get_prompt_tokens
from src.config.config import Config
from src.enums.media_mode import MediaMode
from src.enums.torrent_client import TorrentClientSelection
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import ImageHostError, TrackerError
from src.logger.nfo_forge_logger import LOG
from src.nf_jinja2 import Jinja2TemplateEngine
from src.packages.custom_types import (
    ImageHost,
    ImageSource,
    ImageUploadData,
    ImageUploadFromTo,
)
from src.payloads.media_search import MediaSearchPayload
from src.payloads.tracker_search_result import TrackerSearchResult
from src.payloads.trackers import TrackerInfo
from src.payloads.watch_folder import WatchFolder


class ProcessBackEnd:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.template_selector_be = TemplateSelectorBackEnd()
        self.template_selector_be.load_templates()

        # callables for progress
        self.progress_bar_cb: Callable[[float], None] | None = None

        # clients
        self.qbit_client: QBittorrentClient | None = None
        self.deluge_client: DelugeClient | None = None
        self.rtorrent_client: RTorrentClient | None = None
        self.transmission_client: TransmissionClient | None = None
        self.watch_folder_counter = 0
        self.clients_can_logout = (self.qbit_client, self.deluge_client)

    async def dupe_checks(
        self,
        file_input: Path,
        processing_queue: list[str],
        media_search_payload: MediaSearchPayload,
    ) -> dict[str, tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]]:
        tasks = []
        for tracker_name in processing_queue:
            tracker_sel = TrackerSelection(tracker_name)
            if tracker_sel == TrackerSelection.MORE_THAN_TV:
                tasks.append(
                    self._dupe_mtv(
                        tracker_name=tracker_name,
                        file_input=file_input,
                        media_search_payload=media_search_payload,
                    )
                )
            elif tracker_sel == TrackerSelection.TORRENT_LEECH:
                tasks.append(
                    self._dupe_tl(tracker_name=tracker_name, file_input=file_input)
                )
            elif tracker_sel == TrackerSelection.BEYOND_HD:
                tasks.append(
                    self._dupe_bhd(tracker_name=tracker_name, file_input=file_input)
                )
            elif tracker_sel == TrackerSelection.PASS_THE_POPCORN:
                tasks.append(
                    self._dupe_ptp(tracker_name=tracker_name, file_input=file_input)
                )
            elif tracker_sel == TrackerSelection.REELFLIX:
                tasks.append(
                    self._dupe_rf(tracker_name=tracker_name, file_input=file_input)
                )
            elif tracker_sel == TrackerSelection.AITHER:
                tasks.append(
                    self._dupe_aither(tracker_name=tracker_name, file_input=file_input)
                )
            elif tracker_sel == TrackerSelection.HUNO:
                tasks.append(
                    self._dupe_huno(tracker_name=tracker_name, file_input=file_input)
                )
            elif tracker_sel == TrackerSelection.LST:
                tasks.append(
                    self._dupe_lst(tracker_name=tracker_name, file_input=file_input)
                )
            elif tracker_sel == TrackerSelection.DARK_PEERS:
                tasks.append(
                    self._dupe_dp(tracker_name=tracker_name, file_input=file_input)
                )
            elif tracker_sel == TrackerSelection.SHARE_ISLAND:
                tasks.append(
                    self._dupe_shri(tracker_name=tracker_name, file_input=file_input)
                )

        async_results = await asyncio.gather(*tasks, return_exceptions=True)

        dupes = {}
        for tracker_sel, item in zip(processing_queue, async_results):
            if isinstance(item, tuple) and len(item) == 3:
                dupes[TrackerSelection(tracker_sel)] = item
            elif isinstance(item, Exception):
                LOG.error(
                    LOG.LOG_SOURCE.BE,
                    "".join(
                        traceback.format_exception(type(item), item, item.__traceback__)
                    ),
                )
                dupes[tracker_sel] = (tracker_sel, False, str(item))
            else:
                dupes[tracker_sel] = (tracker_sel, False, f"Unexpected result: {item}")

        return dupes

    async def _dupe_mtv(
        self,
        tracker_name: str,
        file_input: Path,
        media_search_payload: MediaSearchPayload,
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.cfg_payload.mtv_tracker.api_key
        if not api_key:
            return TrackerSelection(tracker_name), False, "MTV API key missing"
        try:
            title = file_input.stem
            imdb_id = media_search_payload.imdb_id
            tmdb_id = media_search_payload.tmdb_id
            if not title or not imdb_id or not tmdb_id:
                return (
                    TrackerSelection(tracker_name),
                    False,
                    "Required MTV search parameters missing",
                )
            mtv_search = MTVSearch(
                api_key,
                timeout=self.config.cfg_payload.timeout,
            ).search(
                title=title,
                imdb_id=imdb_id,
                tmdb_id=tmdb_id,
            )
            if mtv_search:
                return TrackerSelection(tracker_name), True, mtv_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    async def _dupe_tl(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        username = self.config.cfg_payload.tl_tracker.username
        password = self.config.cfg_payload.tl_tracker.password
        if not username or not password:
            return (
                TrackerSelection(tracker_name),
                False,
                "TL username or password missing",
            )
        try:
            tl_search = TLSearch(
                username=username,
                password=password,
                cookie_dir=self.config.TRACKER_COOKIE_PATH,
                alt_2_fa_token=self.config.cfg_payload.tl_tracker.alt_2_fa_token,
                timeout=self.config.cfg_payload.timeout,
            ).search(file_input)
            if tl_search:
                return TrackerSelection(tracker_name), True, tl_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    async def _dupe_bhd(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.cfg_payload.bhd_tracker.api_key
        rss_key = self.config.cfg_payload.bhd_tracker.rss_key
        if not api_key or not rss_key:
            return (
                TrackerSelection(tracker_name),
                False,
                "BHD API key or RSS key missing",
            )
        try:
            bhd_search = BHDSearch(
                api_key=api_key,
                rss_key=rss_key,
                timeout=self.config.cfg_payload.timeout,
            ).search(file_input.stem)
            if bhd_search:
                return TrackerSelection(tracker_name), True, bhd_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    async def _dupe_ptp(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_user = self.config.cfg_payload.ptp_tracker.api_user
        api_key = self.config.cfg_payload.ptp_tracker.api_key
        title = self.config.media_search_payload.title
        year = self.config.media_search_payload.year
        imdb_id = self.config.media_search_payload.imdb_id
        if not api_user or not api_key or not title or year is None or not imdb_id:
            return (
                TrackerSelection(tracker_name),
                False,
                "PTP API user/key or search parameters missing",
            )
        try:
            ptp_search = PTPSearch(
                api_user=api_user,
                api_key=api_key,
                timeout=self.config.cfg_payload.timeout,
            ).search(
                movie_title=title,
                movie_year=year,
                file_name=file_input.stem,
                imdb_id=imdb_id,
            )
            if ptp_search:
                return TrackerSelection(tracker_name), True, ptp_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    async def _dupe_rf(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.cfg_payload.rf_tracker.api_key
        if not api_key:
            return TrackerSelection(tracker_name), False, "ReelFlix API key missing"
        try:
            rf_search = ReelFlixSearch(
                api_key=api_key,
            ).search(file_name=str(file_input))
            if rf_search:
                return TrackerSelection(tracker_name), True, rf_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    async def _dupe_aither(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.cfg_payload.aither_tracker.api_key
        if not api_key:
            return TrackerSelection(tracker_name), False, "Aither API key missing"
        try:
            aither_search = AitherSearch(
                api_key=api_key,
            ).search(file_name=str(file_input))
            if aither_search:
                return TrackerSelection(tracker_name), True, aither_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    async def _dupe_huno(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.cfg_payload.huno_tracker.api_key
        if not api_key:
            return TrackerSelection(tracker_name), False, "Huno API key missing"
        try:
            huno_search = HunoSearch(
                api_key=api_key,
            ).search(file_name=str(file_input))
            if huno_search:
                return TrackerSelection(tracker_name), True, huno_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    async def _dupe_lst(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.cfg_payload.lst_tracker.api_key
        if not api_key:
            return TrackerSelection(tracker_name), False, "LST API key missing"
        try:
            lst_search = LSTSearch(
                api_key=api_key,
            ).search(file_name=str(file_input))
            if lst_search:
                return TrackerSelection(tracker_name), True, lst_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    async def _dupe_dp(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.cfg_payload.darkpeers_tracker.api_key
        if not api_key:
            return TrackerSelection(tracker_name), False, "DarkPeers API key missing"
        try:
            dp_search = DarkPeersSearch(
                api_key=api_key,
            ).search(file_name=str(file_input))
            if dp_search:
                return TrackerSelection(tracker_name), True, dp_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    async def _dupe_shri(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.cfg_payload.shareisland_tracker.api_key
        if not api_key:
            return TrackerSelection(tracker_name), False, "ShareIsland API key missing"
        try:
            shri_search = ShareIslandSearch(
                api_key=api_key,
            ).search(file_name=str(file_input))
            if shri_search:
                return TrackerSelection(tracker_name), True, shri_search
            else:
                return TrackerSelection(tracker_name), True, []
        except Exception as e:
            return TrackerSelection(tracker_name), False, str(e)

    def process_trackers(
        self,
        media_input: Path,
        jinja_engine: Jinja2TemplateEngine,
        source_file: Path | None,
        process_dict: dict[str, Any],
        queued_status_update: Callable[[str, str], None],
        queued_text_update: Callable[[str], None],
        queued_text_update_replace_last_line: Callable[[str], None],
        progress_bar_cb: Callable[[float], None],
        caught_error: SignalInstance,
        mediainfo_obj: MediaInfo,
        source_file_mi_obj: MediaInfo | None,
        media_mode: MediaMode,
        media_search_payload: MediaSearchPayload,
        releasers_name: str,
        encode_file_dir: Path | None = None,
        token_prompt_cb: Callable[[Sequence[str] | None], dict[str, str] | None]
        | None = None,
        overview_cb: Callable[
            [dict[TrackerSelection, dict[str | None, str]] | None],
            dict[TrackerSelection, dict[str | None, str]] | None,
        ]
        | None = None,
    ) -> None:
        # make sure we have all the latest templates in case changes was made during the wizard
        self.template_selector_be.load_templates()

        # handle image uploading
        images = self.handle_images_for_trackers(
            process_dict, queued_text_update, progress_bar_cb
        )

        self.progress_bar_cb = progress_bar_cb
        base_torrent_file: Path | None = None

        # determine maximum piece size for the current tracker(s)
        max_piece_size = self.determine_max_piece_size(process_dict)
        if max_piece_size:
            queued_text_update(
                '<br /><h3 style="margin-bottom: 0; padding-bottom: 0;">🔎 Detected maximum piece size:</h3>'
            )
            queued_text_update(f"<br /><span>{max_piece_size} (bytes)</span>")

        # use encode_file_dir as the source for torrent if set, else use media_input
        torrent_source = encode_file_dir if encode_file_dir else media_input

        # process
        queued_text_update(
            '<br /><h3 style="margin-bottom: 0; padding-bottom: 0;">🌐 Trackers:'
        )

        # base user tokens, this will be filled with prompt tokens as well if needed
        base_usr_tokens = {}

        # find all prompt tokens
        if token_prompt_cb:
            all_prompt_tokens = []
            for tracker_name in process_dict.keys():
                cur_tracker = TrackerSelection(tracker_name)
                tracker_info = self.config.tracker_map[cur_tracker]
                nfo_template = self.template_selector_be.read_template(
                    name=tracker_info.nfo_template
                )
                if nfo_template:
                    prompt_tokens = get_prompt_tokens(nfo_template)
                    all_prompt_tokens.extend(prompt_tokens)

            # remove duplicates but maintain order from prompt tokens
            if all_prompt_tokens:
                # use a callback to wait for a response from the frontend
                response = token_prompt_cb(list(dict.fromkeys(all_prompt_tokens)))
                if response:
                    base_usr_tokens.update(response)

        # generate tracker titles first, then NFOs
        tracker_release_data = {}
        queued_text_update("<br /><span>Generating tracker titles and NFOs</span>")
        for tracker_name in process_dict.keys():
            cur_tracker = TrackerSelection(tracker_name)
            tracker_info = self.config.tracker_map[cur_tracker]

            # generate tracker title first
            tracker_title = None
            generated_tracker_title = self.generate_tracker_title(
                file_name=media_input,
                tracker_info=tracker_info,
            )
            if generated_tracker_title:
                tracker_title = self.tracker_title_formatting(
                    cur_tracker, generated_tracker_title
                )

            nfo_template = self.template_selector_be.read_template(
                name=tracker_info.nfo_template
            )
            user_tokens = base_usr_tokens | {
                k: v for k, (v, _) in self.config.cfg_payload.user_tokens.items()
            }
            nfo = ""
            tracker_images = None
            formatted_screens = None
            comparison_screens = None
            even_screens = None
            even_screens_str = None
            odd_screens = None
            odd_screens_str = None
            if cur_tracker in images:
                tracker_images = images[cur_tracker]
                format_images_to_str = format_image_data_to_str(
                    cur_tracker,
                    tracker_images,
                    tracker_info.url_type,
                    tracker_info.column_s,
                    tracker_info.column_space,
                    tracker_info.row_space,
                )
                formatted_screens = format_image_tag(
                    cur_tracker,
                    format_images_to_str,
                    getattr(tracker_info, "image_width", 350),
                )
                if self.config.shared_data.is_comparison_images:
                    comparison_screens = format_image_data_to_comparison(tracker_images)
                    even_screens = get_parity_images(data=tracker_images)
                    odd_screens = get_parity_images(data=tracker_images, even=False)
                    even_screens_str = get_parity_images_to_str(data=tracker_images)
                    odd_screens_str = get_parity_images_to_str(
                        data=tracker_images, even=False
                    )
            if nfo_template:
                nfo = TokenReplacer(
                    media_input=media_input,
                    jinja_engine=jinja_engine,
                    source_file=source_file,
                    token_string=nfo_template,
                    media_search_obj=media_search_payload,
                    source_file_mi_obj=source_file_mi_obj,
                    media_info_obj=mediainfo_obj,
                    unfilled_token_mode=UnfilledTokenRemoval.KEEP,
                    releasers_name=releasers_name,
                    screen_shots=formatted_screens,
                    screen_shots_comparison=comparison_screens,
                    screen_shots_even_obj=even_screens,
                    screen_shots_odd_obj=odd_screens,
                    screen_shots_even_str=even_screens_str,
                    screen_shots_odd_str=odd_screens_str,
                    release_notes=self.config.shared_data.release_notes,
                    edition_override=self.config.shared_data.dynamic_data.get(
                        "edition_override"
                    ),
                    frame_size_override=self.config.shared_data.dynamic_data.get(
                        "frame_size_override"
                    ),
                    override_tokens=self.config.shared_data.dynamic_data.get(
                        "override_tokens"
                    ),
                    user_tokens=user_tokens,
                    movie_clean_title_rules=self.config.cfg_payload.mvr_clean_title_rules,
                    mi_video_dynamic_range=self.config.cfg_payload.mvr_mi_video_dynamic_range,
                ).get_output()
                if not isinstance(nfo, str):
                    raise ValueError("NFO should be a string")

            # run token replacer plugin if available
            token_replacer_plugin = self.config.cfg_payload.token_replacer
            if token_replacer_plugin:
                nfo_plugin = self.config.loaded_plugins[
                    token_replacer_plugin
                ].token_replacer
                if nfo_plugin and callable(nfo_plugin):
                    LOG.info(
                        LOG.LOG_SOURCE.BE,
                        f"Running token replacer plugin for tracker: {tracker_name}",
                    )
                    replace_tokens = nfo_plugin(
                        config=self.config,
                        input_str=nfo,
                        tracker_s=(cur_tracker,),
                        tracker_images=tracker_images
                        if cur_tracker in images
                        else None,
                        format_images_to_str=formatted_screens,
                        formatted_screens=formatted_screens,
                    )
                    nfo = replace_tokens if replace_tokens else nfo

            tracker_release_data[cur_tracker] = {"title": tracker_title, "nfo": nfo}

        # update nfos with user updates from front end if enabled
        if self.config.cfg_payload.enable_prompt_overview and overview_cb:
            confirm_overview = overview_cb(tracker_release_data)
            if confirm_overview:
                nfo_updates = [
                    str(k)
                    for k in tracker_release_data
                    if k in confirm_overview
                    and tracker_release_data[k] != confirm_overview[k]
                ]
                if nfo_updates:
                    queued_text_update(
                        "<br /><i><span>Applying user edits from overview to trackers "
                        f'<span style="font-weight: bold;">{", ".join(nfo_updates)}</span></span></i><br />'
                    )
                tracker_release_data = confirm_overview

        # loop from the start and process jobs
        for idx, (tracker_name, path_data) in enumerate(process_dict.items()):
            queued_status_update(tracker_name, "▶️ Processing")
            queued_text_update(
                f'<br /><span>Starting work for <span style="font-weight: bold;">{tracker_name}</span></span>'
            )

            # screenshots stuff, updated below for each tracker in the loop
            tracker_images = None
            format_images_to_str = None
            formatted_screens = None

            # get tracker object and tracker info
            cur_tracker = TrackerSelection(tracker_name)
            tracker_info = self.config.tracker_map[cur_tracker]

            # get tracker title and nfo data
            cur_tracker_release_data = tracker_release_data.get(cur_tracker, {})
            cur_tracker_title = cur_tracker_release_data.get("title", "")

            # get just the torrent path (there is other data that we currently aren't using)
            # >>> {'path': WindowsPath('path.torrent'), 'image_host': 'URLs',
            # 'image_host_data': ImageUploadFromTo(img_from=<ImageSource.URLS: 'URLs'>, img_to=<ImageSource.URLS: 'URLs'>)}
            torrent_path: Path = path_data["path"]

            # output current tracker title we're using
            if cur_tracker_title:
                queued_text_update(f"<br />Release title: {cur_tracker_title}")

            # torrent file
            if idx == 0:
                # try mkbrr first if enabled, fallback to torf if not available or on error
                try:
                    if self.config.cfg_payload.enable_mkbrr and (
                        self.config.cfg_payload.mkbrr
                        and self.config.cfg_payload.mkbrr.exists()
                    ):
                        queued_text_update(
                            '<br /><span>Generating torrent with <span style="font-weight: bold;">'
                            "mkbrr</span></span>"
                        )
                        torrent = mkbrr_generate_torrent(
                            mkbrr_path=self.config.cfg_payload.mkbrr,
                            tracker_info=tracker_info,
                            path=torrent_source,
                            output_path=torrent_path,
                            max_piece_size=max_piece_size,
                            cb=self.mkbrr_torrent_gen_cb,
                        )
                        base_torrent_file = torrent_path
                    else:
                        raise Exception("mkbrr not configured or not found")
                except Exception as mkbrr_error:
                    # only show error if mkbrr was available but failed
                    if (
                        self.config.cfg_payload.enable_mkbrr
                        and self.config.cfg_payload.mkbrr
                    ):
                        queued_text_update(
                            f'<br /><span style="color: red;">mkbrr failed: {mkbrr_error} '
                            "(falling back to torf)</span>"
                        )

                    queued_text_update(
                        '<br /><span>Generating torrent with <span style="font-weight: bold;">'
                        "torf</span></span>"
                    )
                    torrent = generate_torrent(
                        tracker_info=tracker_info,
                        path=torrent_source,
                        max_piece_size=max_piece_size,
                        cb=self.torrent_gen_cb,
                    )
                    write_to_disk = write_torrent(torrent, torrent_path)
                    base_torrent_file = write_to_disk
            else:
                queued_text_update("<br /><span>Cloning torrent</span>")
                if not base_torrent_file:
                    raise FileNotFoundError(
                        "Failed to determine base torrent file to clone"
                    )
                clone = clone_torrent(
                    tracker_info=tracker_info,
                    torrent_path=torrent_path,
                    base_torrent_file=base_torrent_file,
                )
                _ = write_torrent(torrent_instance=clone, torrent_path=torrent_path)

            nfo = cur_tracker_release_data.get("nfo", "")
            if nfo:
                with open(
                    torrent_path.with_suffix(".nfo"), "w", encoding="utf-8"
                ) as log_out:
                    log_out.write(nfo)

            # pre upload plugin
            pre_upload_processing = None
            pre_upload_plugin = self.config.cfg_payload.pre_upload
            if pre_upload_plugin:
                get_pre_upload_plugin = self.config.loaded_plugins[
                    pre_upload_plugin
                ].pre_upload
                if get_pre_upload_plugin and callable(get_pre_upload_plugin):
                    pre_upload_processing = get_pre_upload_plugin(
                        config=self.config,
                        tracker=cur_tracker,
                        torrent_file=torrent_path,
                        media_file=media_input,
                        mi_obj=mediainfo_obj,
                        source_path=torrent_source,
                        upload_text_cb=queued_text_update,
                        upload_text_replace_last_line_cb=queued_text_update_replace_last_line,
                        progress_cb=self.progress_bar_cb,
                    )

            # upload
            if tracker_info.upload_enabled and pre_upload_processing is not False:
                queued_text_update("<br /><span>Uploading release</span>")
                execute_upload = None
                try:
                    execute_upload = self.upload(
                        tracker=cur_tracker,
                        torrent_file=torrent_path,
                        file_input=Path(media_input),
                        mediainfo_obj=mediainfo_obj,
                        media_mode=media_mode,
                        media_search_payload=media_search_payload,
                        nfo=nfo,
                        tracker_title=cur_tracker_title,
                    )
                except Exception as upload_error:
                    queued_text_update(
                        '<br /><br /><p style="font-weight: bold; color: red;">Failed to upload '
                        f"release, check logs for information ({upload_error})</p>",
                    )
                    caught_error.emit(f"Upload Error: {traceback.format_exc()}")
                    queued_status_update(tracker_name, "❌ Failed")

                if execute_upload:
                    queued_text_update(
                        "<br /><span>Successfully uploaded release</span>"
                    )
                    # handle injection
                    try:
                        self._handle_injection(
                            queued_text_update=queued_text_update,
                            tracker_name=tracker_name,
                            torrent_path=torrent_path,
                            file_input=media_input,
                        )
                        queued_status_update(tracker_name, "✅ Complete")
                    except Exception as e:
                        queued_status_update(
                            tracker_name, f"❌ Failed to inject torrent ({e})"
                        )
                        caught_error.emit(f"Injection Error: {traceback.format_exc()}")
                else:
                    queued_text_update(
                        '<br /><span style="font-weight: bold; color: red;">Failed to upload release, '
                        "check logs for information</span>"
                    )
                    queued_status_update(tracker_name, "❌ Failed")
            elif not tracker_info.upload_enabled and pre_upload_processing is None:
                queued_text_update(
                    "<br /><span>Skipping upload & injection, upload is disabled</span>"
                )
                queued_status_update(tracker_name, "✅ Complete")
            elif tracker_info.upload_enabled and pre_upload_processing is False:
                queued_text_update(
                    "<br /><span>Skipping upload & injection, upload is disabled via plugin</span>"
                )
                queued_status_update(tracker_name, "✅ Complete")

            nfo_generated_str = "NFO & " if nfo else ""
            queued_text_update(
                f"<br /><span>Generated {nfo_generated_str}torrent output directory:\n{torrent_path.parent}</span><br />",
            )

        # disconnect from clients and reset related variables after use
        self.disconnect_from_clients()

    def handle_images_for_trackers(
        self,
        process_dict: dict[str, Any],
        queued_text_update: Callable[[str], None],
        progress_bar_cb: Callable[[float], None],
    ) -> dict[TrackerSelection, dict[int, ImageUploadData]]:
        """
        Handles the uploading of images for various trackers based on the provided process dictionary.

        This function determines the image sources and destinations, downloads images if necessary,
        and uploads them to the specified image hosts.

        Args:
            process_dict (dict[str, Any]): A dictionary containing tracker-specific data,
                including image hosting information.
            queued_text_update (Callable[[str], None]): A callback function to update the UI
                or log messages related to the upload process.
            progress_bar_cb (Callable[[float], None]): A callback function to track
                the progress of the torrent generation.

        Returns:
            dict[TrackerSelection, dict[int, ImageUploadData]]: A dictionary mapping trackers to their
            corresponding uploaded image data.
        """
        to_image_hosts: set[ImageHost] = set()
        to_url = False
        tracker_to_host_map = {}
        img_from = None
        files_to_upload = None

        url_data = {}

        # build tracker_to_host_map and determine where the images are from/to
        for tracker, data in process_dict.items():
            image_host_data = data["image_host_data"]

            if isinstance(image_host_data, ImageUploadFromTo):
                if not img_from:
                    img_from = image_host_data.img_from
                img_to = image_host_data.img_to

                # track the image host to be used for each tracker
                if isinstance(img_to, ImageHost) and img_to is not ImageHost.DISABLED:
                    to_image_hosts.add(img_to)
                elif not to_url and img_to is ImageSource.URLS:
                    to_url = True

                tracker_to_host_map[TrackerSelection(tracker)] = img_to

        # handle image host uploads
        if to_image_hosts or to_url:
            queued_text_update(
                '<br /><h3 style="margin-bottom: 0; padding-bottom: 0;">🎥 Image Handling:</h3>'
            )
        if to_image_hosts:
            if img_from is ImageSource.URLS:
                queued_text_update(
                    f"<br />Attempting to download {len(self.config.shared_data.url_data)} user-provided URL(s)",
                )

                if not self.config.media_input_payload.working_dir:
                    raise FileNotFoundError("Working directory was not found")
                img_output_path = (
                    self.config.media_input_payload.working_dir / "dl_imgs"
                )
                img_downloader = ImageDownloader(
                    self.config.shared_data.url_data,
                    img_output_path,
                    progress_bar_cb,
                )
                files_to_upload = img_downloader.download_images()
                self.config.shared_data.loaded_images = files_to_upload

                queued_text_update(
                    f"<br />Successfully downloaded {len(files_to_upload)} user-provided URL(s)",
                )
            else:
                files_to_upload = self.config.shared_data.loaded_images

            if files_to_upload:
                # optimize images if enabled
                # if we have generated images and optimization for generated images is enabled
                # or
                # if we don't have user generated images and optimize download/url images is enabled or images
                # are downloaded from URLs
                if (
                    self.config.shared_data.generated_images
                    and self.config.cfg_payload.optimize_generated_images
                ) or (
                    not self.config.shared_data.generated_images
                    and self.config.cfg_payload.optimize_dl_url_images
                    or img_from is ImageSource.URLS
                ):
                    queued_text_update(
                        f"<br />Optimizing {len(files_to_upload)} image(s)"
                    )
                    try:
                        files_to_upload = self._optimize_images(
                            progress_bar_cb, files_to_upload
                        )
                    except Exception as opt_e:
                        queued_text_update(
                            f"<br />Failed to optimize image(s) ({opt_e})"
                        )

                # upload images
                queued_text_update(
                    f"<br />Uploading {len(files_to_upload)} images to {len(to_image_hosts)} image host(s)",
                )
                async_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(async_loop)
                upload_results: dict[ImageHost, dict[int, ImageUploadData]] = (
                    async_loop.run_until_complete(
                        self.handle_image_upload(
                            to_image_hosts, files_to_upload, progress_bar_cb
                        )
                    )
                )
                async_loop.close()

                # map the uploaded image hosts to the appropriate trackers
                for tracker, img_host in tracker_to_host_map.items():
                    if img_host in upload_results:
                        url_data[tracker] = upload_results[img_host]

        # using URLs as is
        if to_url:
            url_host_count = 0
            for tracker, img_host in tracker_to_host_map.items():
                if img_host is ImageSource.URLS:
                    url_data[tracker] = {
                        i: img_data
                        for i, img_data in enumerate(self.config.shared_data.url_data)
                    }
                    url_host_count += 1

            queued_text_update(
                f"<br />Using {len(self.config.shared_data.url_data)} URLs for {url_host_count} tracker(s)",
            )

        return url_data

    def _optimize_images(
        self, progress_bar_cb: Callable[[float], None], files_to_upload: Sequence[Path]
    ) -> Sequence[Path]:
        """Optimizes images and returns the optimized images in a list"""

        def img_optimizer_job_done_callback(
            _png_path: Path, completed: int, total: int
        ):
            progress_bar_cb(completed / total * 100)

        image_optimizer = MultiProcessImageOptimizer(
            on_job_done=img_optimizer_job_done_callback,
            cpu_fraction=self.config.cfg_payload.optimize_dl_url_images_percentage,
        )
        img_opt_output_dir = files_to_upload[0].parent / "optimized"
        try:
            optimized_files = image_optimizer.process_jobs(
                files_to_upload, img_opt_output_dir
            )
        except:
            # clean up extra images if failed
            shutil.rmtree(img_opt_output_dir)
            raise
        return optimized_files

    async def handle_image_upload(
        self,
        to_image_hosts: set[ImageHost],
        filepaths: Sequence[Path],
        progress_bar_cb: Callable[[float], None],
    ) -> dict[ImageHost, dict[int, ImageUploadData]]:
        """
        Handles the image upload process to multiple image hosts asynchronously.

        Args:
            to_image_hosts (set[ImageHost]): The set of image hosts to upload to.
            filepaths (Sequence[Path]): The file paths of the images to be uploaded.
            progress_bar_cb (Callable[[float], None): Callback function to track upload progress.

        Returns:
            dict[ImageHost, dict[int, ImageUploadData]]: A mapping of image hosts to uploaded image data.
        """

        def progress_callback(_job: str, _ind: float, overall: float):
            progress_bar_cb(overall)

        image_uploader = ImageUploader(progress_signal=progress_callback)

        jobs = {}
        host_to_job = {}

        # register image hosts and their corresponding uploaders
        self._register_image_hosts(
            to_image_hosts, filepaths, image_uploader, jobs, host_to_job
        )

        # start all jobs and wait for results
        results = await image_uploader.start_jobs()

        # map uploaded URLs back to each tracker
        uploaded_urls = self._map_uploaded_urls(host_to_job, results)

        return uploaded_urls

    def _register_image_hosts(
        self,
        to_image_hosts: set[ImageHost],
        filepaths: Sequence[Path],
        image_uploader: ImageUploader,
        jobs: dict,
        host_to_job: dict,
    ) -> None:
        """
        Registers image hosts and associates them with upload jobs.

        Args:
            to_image_hosts (set[ImageHost]): The set of image hosts to register.
            filepaths (Sequence[Path]): The file paths of images to be uploaded.
            image_uploader (ImageUploader): The image uploader instance.
            jobs (dict): Dictionary mapping job IDs to image hosts.
            host_to_job (dict): Dictionary mapping image hosts to job IDs.
        """
        for img_host in to_image_hosts:
            if img_host in host_to_job:
                continue

            uploader = self._get_uploader_for_host(img_host)
            image_uploader.register_uploader(str(img_host), uploader)

            job_id = image_uploader.add_job(str(img_host), filepaths)
            jobs[job_id] = img_host
            host_to_job[img_host] = job_id

    def _get_uploader_for_host(self, img_host: ImageHost) -> BaseImageHostUploader:
        """
        Retrieves the appropriate uploader instance for a given image host.

        Args:
            img_host (ImageHost): The image host.

        Returns:
            BaseImageHostUploader: The corresponding uploader instance.

        Raises:
            ImageHostError: If the image host is unsupported.
        """
        if img_host is ImageHost.CHEVERETO_V4:
            return self._create_chevereto_v4_uploader()
        elif img_host is ImageHost.CHEVERETO_V3:
            return self._create_chevereto_v3_uploader()
        elif img_host is ImageHost.IMAGE_BOX:
            return ImageBoxUploader()
        elif img_host is ImageHost.IMAGE_BB:
            return self._create_imgbb_uploader()
        elif img_host is ImageHost.PTPIMG:
            return self._create_ptpimg_uploader()
        else:
            raise ImageHostError(f"Unsupported image host: {img_host}")

    def _create_chevereto_v4_uploader(self) -> CheveretoV4Uploader:
        """
        Creates an uploader instance for Chevereto V4.

        Returns:
            CheveretoV4Uploader: The uploader instance.

        Raises:
            ImageHostError: If required credentials are missing.
        """
        chv4_payload = self.config.cfg_payload.chevereto_v4
        if not chv4_payload.api_key or not chv4_payload.base_url:
            raise ImageHostError("Missing 'API Key' or 'Base URL' for CheveretoV4.")
        return CheveretoV4Uploader(
            api_key=chv4_payload.api_key, url=chv4_payload.base_url
        )

    def _create_chevereto_v3_uploader(self) -> CheveretoV3Uploader:
        """
        Creates an uploader instance for Chevereto V3.

        Returns:
            CheveretoV3Uploader: The uploader instance.

        Raises:
            ImageHostError: If required credentials are missing.
        """
        chv3_payload = self.config.cfg_payload.chevereto_v3
        if (
            not chv3_payload.base_url
            or not chv3_payload.user
            or not chv3_payload.password
        ):
            raise ImageHostError("Missing credentials for CheveretoV3.")
        return CheveretoV3Uploader(
            base_url=chv3_payload.base_url,
            user=chv3_payload.user,
            password=chv3_payload.password,
        )

    def _create_imgbb_uploader(self) -> ImageBBUploader:
        """
        Creates an uploader instance for ImageBB.

        Returns:
            ImageBBUploader: The uploader instance.

        Raises:
            ImageHostError: If required credentials are missing.
        """
        imgbb_payload = self.config.cfg_payload.image_bb
        if not imgbb_payload.api_key or not imgbb_payload.base_url:
            raise ImageHostError("Missing 'API Key' for ImageBB.")
        return ImageBBUploader(api_key=imgbb_payload.api_key)

    def _create_ptpimg_uploader(self) -> PTPIMGUploader:
        """
        Creates an uploader instance for PTPIMG.

        Returns:
            PTPIMGUploader: The uploader instance.

        Raises:
            ImageHostError: If required credentials are missing.
        """
        ptpimg_payload = self.config.cfg_payload.ptpimg
        if not ptpimg_payload.api_key or not ptpimg_payload.base_url:
            raise ImageHostError("Missing 'API Key' for PTPIMG.")
        return PTPIMGUploader(api_key=ptpimg_payload.api_key)

    def _map_uploaded_urls(
        self, host_to_job: dict, results: dict[str, dict[int, ImageUploadData]]
    ) -> dict[ImageHost, dict[int, ImageUploadData]]:
        """
        Maps uploaded URLs to their respective image hosts.

        Args:
            host_to_job (dict): Mapping of image hosts to job IDs.
            results (dict[str, dict[int, ImageUploadData]]): The upload results.

        Returns:
            dict[ImageHost, dict[int, ImageUploadData]]: The mapped results.
        """
        return {tracker: results[job_id] for tracker, job_id in host_to_job.items()}

    def determine_max_piece_size(self, process_dict: dict[str, Path]) -> int | None:
        """
        Determines the max piece size across a dictionary of trackers.
        Ensures that the piece size is is divisible by 16 KiB and
        rounds down to the nearest divisible value.

        Args:
            process_dict (dict[str, Path]): Dictionary of trackers.

        Returns:
            int | None
        """
        piece_sizes = set()
        for tracker in process_dict.keys():
            max_piece_size = self.config.tracker_map[
                TrackerSelection(tracker)
            ].max_piece_size
            if max_piece_size > 0:
                piece_sizes.add(max_piece_size)

        calculated_size = min(piece_sizes, default=None)
        if calculated_size:
            calculated_size = calculated_size - (calculated_size % 16384)
        return calculated_size

    def upload(
        self,
        tracker: TrackerSelection,
        torrent_file: Path,
        file_input: Path,
        mediainfo_obj: MediaInfo,
        media_mode: MediaMode,
        media_search_payload: MediaSearchPayload,
        nfo: str,
        tracker_title: str,
    ) -> Path | bool | str | None:
        if tracker is TrackerSelection.MORE_THAN_TV:
            tracker_payload = self.config.cfg_payload.mtv_tracker
            if not tracker_payload.username or not tracker_payload.password:
                raise TrackerError("Username and password is required for MoreThanTV")
            return mtv_uploader(
                username=tracker_payload.username,
                password=tracker_payload.password,
                totp=tracker_payload.totp,
                nfo=nfo,
                group_desc=tracker_payload.group_description,
                torrent_file=Path(torrent_file),
                file_input=file_input,
                tracker_title=tracker_title,
                mediainfo_obj=mediainfo_obj,
                genre_ids=media_search_payload.genres,
                media_mode=media_mode,
                anonymous=bool(tracker_payload.anonymous),
                source_origin=tracker_payload.source_origin,
                cookie_dir=self.config.TRACKER_COOKIE_PATH,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker is TrackerSelection.TORRENT_LEECH:
            announce_key = self.config.cfg_payload.tl_tracker.torrent_passkey
            if not announce_key:
                raise TrackerError("Missing announce key for TorrentLeech")
            return tl_upload(
                announce_key=announce_key,
                nfo=nfo,
                tracker_title=tracker_title,
                torrent_file=torrent_file,
                mediainfo_obj=mediainfo_obj,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker is TrackerSelection.BEYOND_HD:
            tracker_payload = self.config.cfg_payload.bhd_tracker
            if not tracker_payload.api_key:
                raise TrackerError("Missing API key for BeyondHD")
            return bhd_uploader(
                api_key=tracker_payload.api_key,
                torrent_file=torrent_file,
                file_input=file_input,
                tracker_title=tracker_title,
                media_mode=media_mode,
                imdb_id=media_search_payload.imdb_id,
                tmdb_id=media_search_payload.tmdb_id,
                nfo=nfo,
                internal=bool(tracker_payload.internal),
                live_release=tracker_payload.live_release,
                anonymous=bool(tracker_payload.anonymous),
                promo=tracker_payload.promo,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker is TrackerSelection.PASS_THE_POPCORN:
            tracker_payload = self.config.cfg_payload.ptp_tracker
            if (
                not tracker_payload.api_user
                or not tracker_payload.api_key
                or not tracker_payload.username
                or not tracker_payload.password
                or not tracker_payload.announce_url
            ):
                raise TrackerError(
                    "TorrentLeech requires API user, API key, username, password, and announce URL"
                )
            return ptp_uploader(
                api_user=tracker_payload.api_user,
                api_key=tracker_payload.api_key,
                username=tracker_payload.username,
                password=tracker_payload.password,
                announce_url=tracker_payload.announce_url,
                torrent_file=torrent_file,
                file_input=file_input,
                nfo=nfo,
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_payload,
                ptp_img_api_key=self.config.cfg_payload.ptp_tracker.api_key,
                cookie_dir=self.config.TRACKER_COOKIE_PATH,
                totp=tracker_payload.totp,
                timeout=self.config.cfg_payload.timeout,
            )
        # Unit3d trackers
        elif tracker is TrackerSelection.REELFLIX:
            tracker_payload = self.config.cfg_payload.rf_tracker
            if not tracker_payload.api_key:
                raise TrackerError("Missing API key for ReelFliX")
            return rf_uploader(
                media_mode=media_mode,
                api_key=tracker_payload.api_key,
                torrent_file=torrent_file,
                file_input=file_input,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(tracker_payload.internal),
                anonymous=bool(tracker_payload.anonymous),
                personal_release=bool(tracker_payload.personal_release),
                stream_optimized=bool(tracker_payload.stream_optimized),
                opt_in_to_mod_queue=bool(tracker_payload.opt_in_to_mod_queue),
                featured=bool(tracker_payload.featured),
                free=bool(tracker_payload.free),
                double_up=bool(tracker_payload.double_up),
                sticky=bool(tracker_payload.sticky),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_payload,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker is TrackerSelection.AITHER:
            tracker_payload = self.config.cfg_payload.aither_tracker
            if not tracker_payload.api_key:
                raise TrackerError("Missing API key for Aither")
            return aither_uploader(
                media_mode=media_mode,
                api_key=tracker_payload.api_key,
                torrent_file=torrent_file,
                file_input=file_input,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(tracker_payload.internal),
                anonymous=bool(tracker_payload.anonymous),
                personal_release=bool(tracker_payload.personal_release),
                stream_optimized=bool(tracker_payload.stream_optimized),
                opt_in_to_mod_queue=bool(tracker_payload.opt_in_to_mod_queue),
                featured=bool(tracker_payload.featured),
                free=bool(tracker_payload.free),
                double_up=bool(tracker_payload.double_up),
                sticky=bool(tracker_payload.sticky),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_payload,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker is TrackerSelection.HUNO:
            tracker_payload = self.config.cfg_payload.huno_tracker
            if not tracker_payload.api_key:
                raise TrackerError("Missing API key for HUNO")
            return huno_uploader(
                media_mode=media_mode,
                api_key=tracker_payload.api_key,
                torrent_file=torrent_file,
                file_input=file_input,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(tracker_payload.internal),
                anonymous=bool(tracker_payload.anonymous),
                stream_optimized=bool(tracker_payload.stream_optimized),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_payload,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker is TrackerSelection.LST:
            tracker_payload = self.config.cfg_payload.lst_tracker
            if not tracker_payload.api_key:
                raise TrackerError("Missing API key for LST")
            return lst_uploader(
                media_mode=media_mode,
                api_key=tracker_payload.api_key,
                torrent_file=torrent_file,
                file_input=file_input,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(tracker_payload.internal),
                anonymous=bool(tracker_payload.anonymous),
                personal_release=bool(tracker_payload.personal_release),
                opt_in_to_mod_queue=bool(tracker_payload.mod_queue_opt_in),
                draft_queue_opt_in=bool(tracker_payload.draft_queue_opt_in),
                featured=bool(tracker_payload.featured),
                free=bool(tracker_payload.free),
                double_up=bool(tracker_payload.double_up),
                sticky=bool(tracker_payload.sticky),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_payload,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker is TrackerSelection.DARK_PEERS:
            tracker_payload = self.config.cfg_payload.darkpeers_tracker
            if not tracker_payload.api_key:
                raise TrackerError("Missing API key for DarkPeers")
            return dp_uploader(
                media_mode=media_mode,
                api_key=tracker_payload.api_key,
                torrent_file=torrent_file,
                file_input=file_input,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(tracker_payload.internal),
                anonymous=bool(tracker_payload.anonymous),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_payload,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker is TrackerSelection.SHARE_ISLAND:
            tracker_payload = self.config.cfg_payload.shareisland_tracker
            if not tracker_payload.api_key:
                raise TrackerError("Missing API key for ShareIsland")
            return shri_uploader(
                media_mode=media_mode,
                api_key=tracker_payload.api_key,
                torrent_file=torrent_file,
                file_input=file_input,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(tracker_payload.internal),
                anonymous=bool(tracker_payload.anonymous),
                personal_release=bool(tracker_payload.personal_release),
                opt_in_to_mod_queue=bool(tracker_payload.opt_in_to_mod_queue),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_payload,
                timeout=self.config.cfg_payload.timeout,
            )

    def generate_tracker_title(
        self,
        file_name: Path,
        tracker_info: TrackerInfo,
    ) -> str | None:
        token_string = (
            tracker_info.mvr_title_token_override
            if tracker_info.mvr_title_token_override
            else self.config.cfg_payload.mvr_title_token
        )
        colon_replace = (
            tracker_info.mvr_title_colon_replace
            if tracker_info.mvr_title_colon_replace
            else self.config.cfg_payload.mvr_colon_replace_title
        )
        override_title_rules = (
            tracker_info.mvr_title_replace_map
            if tracker_info.mvr_title_replace_map
            else None
        )
        user_tokens = {
            k: v
            for k, (v, t) in self.config.cfg_payload.user_tokens.items()
            if TokenSelection(t) is TokenSelection.FILE_TOKEN
        }
        format_str = TokenReplacer(
            media_input=file_name,
            jinja_engine=None,
            source_file=None,
            token_string=token_string,
            colon_replace=colon_replace,
            media_search_obj=self.config.media_search_payload,
            media_info_obj=self.config.media_input_payload.encode_file_mi_obj,
            flatten=True,
            file_name_mode=False,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            edition_override=self.config.shared_data.dynamic_data.get(
                "edition_override"
            ),
            frame_size_override=self.config.shared_data.dynamic_data.get(
                "frame_size_override"
            ),
            override_tokens=self.config.shared_data.dynamic_data.get("override_tokens"),
            movie_clean_title_rules=self.config.cfg_payload.mvr_clean_title_rules,
            user_tokens=user_tokens,
            override_title_rules=override_title_rules,
            mi_video_dynamic_range=self.config.cfg_payload.mvr_mi_video_dynamic_range,
        )
        output = format_str.get_output()
        return output if output else None

    def tracker_title_formatting(self, tracker: TrackerSelection, title: str) -> str:
        """Apply tracker specific formatting if it has any, else return the title as it is."""
        if tracker is TrackerSelection.MORE_THAN_TV:
            return MTVUploader.generate_release_title(title)
        elif tracker is TrackerSelection.TORRENT_LEECH:
            return TLUploader.generate_release_title(title)
        elif tracker is TrackerSelection.BEYOND_HD:
            return BHDUploader.generate_release_title(title)
        # Unit3d trackers
        elif tracker in {
            TrackerSelection.REELFLIX,
            TrackerSelection.AITHER,
            TrackerSelection.HUNO,
            TrackerSelection.LST,
            TrackerSelection.DARK_PEERS,
            TrackerSelection.SHARE_ISLAND,
        }:
            return Unit3dBaseUploader.generate_release_title(title)

        return title

    def torrent_gen_cb(
        self,
        _torrent: Torrent,
        _filepath: str,
        pieces_done: int,
        pieces_total: int,
    ) -> None:
        if self.progress_bar_cb:
            self.progress_bar_cb(round(pieces_done / pieces_total * 100, 2))

    def mkbrr_torrent_gen_cb(self, progress: int) -> None:
        if self.progress_bar_cb:
            self.progress_bar_cb(progress)

    def _handle_injection(
        self,
        queued_text_update: Callable[[str], None],
        tracker_name: str,
        torrent_path: Path,
        file_input: Path,
    ) -> None:
        for client, client_settings in self.config.client_map.items():
            if client_settings.enabled:
                inj_success, inj_msg = False, "Failed"
                queued_text_update(
                    f"<br />Injecting torrent [Tracker: {tracker_name} | Client: {client}]",
                )
                if client is TorrentClientSelection.QBITTORRENT:
                    inj_success, inj_msg = self.qbittorrent_inject(torrent_path)
                elif client is TorrentClientSelection.DELUGE:
                    inj_success, inj_msg = self.deluge_inject(torrent_path)
                elif client is TorrentClientSelection.RTORRENT:
                    inj_success, inj_msg = self.rtorrent_inject(
                        torrent_path, file_input
                    )
                elif client is TorrentClientSelection.TRANSMISSION:
                    inj_success, inj_msg = self.transmission_inject(torrent_path)
                elif (
                    client is TorrentClientSelection.WATCH_FOLDER
                    and isinstance(client_settings, WatchFolder)
                    and client_settings.path
                ):
                    watch_folder_func = self.watch_folder_inject(
                        Path(torrent_path), tracker_name, client_settings.path
                    )
                    if watch_folder_func:
                        inj_success, inj_msg = watch_folder_func

                queued_text_update(
                    f"<br />{'Completed' if inj_success else 'Failed'}, status: {inj_msg}",
                )

    def qbittorrent_inject(self, torrent_path: Path) -> tuple[bool, str]:
        if not self.qbit_client:
            self.qbit_client = QBittorrentClient(
                self.config.cfg_payload.qbittorrent, self.config.cfg_payload.timeout
            )
            self.qbit_client.login()
        return self.qbit_client.inject_torrent(torrent_path)

    def deluge_inject(self, torrent_path: Path) -> tuple[bool, str]:
        if not self.deluge_client:
            self.deluge_client = DelugeClient(
                self.config.cfg_payload.deluge, self.config.cfg_payload.timeout
            )
            self.deluge_client.login()
        return self.deluge_client.inject_torrent(torrent_path)

    def rtorrent_inject(self, torrent_path: Path, file_path: Path) -> tuple[bool, str]:
        if not self.rtorrent_client:
            self.rtorrent_client = RTorrentClient(
                self.config.cfg_payload.rtorrent, self.config.cfg_payload.timeout
            )
        return self.rtorrent_client.inject_torrent(torrent_path, file_path, True)

    def transmission_inject(self, torrent_path: Path) -> tuple[bool, str]:
        if not self.transmission_client:
            self.transmission_client = TransmissionClient(
                self.config.cfg_payload.transmission, self.config.cfg_payload.timeout
            )
        return self.transmission_client.inject_torrent(torrent_path)

    def watch_folder_inject(
        self, torrent_path: Path, tracker_name: str, client_path: Path
    ) -> tuple[Path, str] | None:
        moved_file = Path(
            shutil.copy(
                torrent_path,
                client_path
                / Path(
                    torrent_path.stem
                    + f"_nf_{tracker_name.lower()}_{self.watch_folder_counter}.torrent"
                ),
            )
        )
        self.watch_folder_counter += 1
        if moved_file.exists():
            return moved_file, f"File copied to watch folder ({moved_file.name})"

    def disconnect_from_clients(self) -> None:
        for client in (
            self.qbit_client,
            self.deluge_client,
            self.rtorrent_client,
            self.transmission_client,
        ):
            if client and client in self.clients_can_logout:
                client.logout()
            client = None
        self.watch_folder_counter = 0

    @staticmethod
    def rename_file(f_in: Path, f_out: Path) -> Path:
        return f_in.rename(f_out)
