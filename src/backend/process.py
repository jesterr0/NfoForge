import asyncio
import shutil
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import niquests
from PySide6.QtCore import SignalInstance
from tenacity import Retrying, retry_if_exception, stop_after_attempt
from tenacity.wait import wait_exponential
from torf import Torrent

from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.backend.image_host_uploading.chevereto_v3 import CheveretoV3Uploader
from src.backend.image_host_uploading.chevereto_v4 import CheveretoV4Uploader
from src.backend.image_host_uploading.img_box import ImageBoxUploader
from src.backend.image_host_uploading.img_downloader import ImageDownloader
from src.backend.image_host_uploading.img_uploader import ImageUploader
from src.backend.image_host_uploading.imgbb import ImageBBUploader
from src.backend.template_selector import TemplateSelectorBackEnd
from src.backend.token_replacer import TokenReplacer
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
    OnlyEncodesSearch,
    PTPSearch,
    ReelFlixSearch,
    ShareIslandSearch,
    TLSearch,
    UploadCXSearch,
    aither_uploader,
    bhd_uploader,
    dp_uploader,
    huno_uploader,
    lst_uploader,
    mtv_uploader,
    oe_uploader,
    ptp_uploader,
    rf_uploader,
    shri_uploader,
    tl_upload,
    ulcx_uploader,
)
from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.health import ensure_tracker_health
from src.backend.trackers.media_support import UNSUPPORTED_SERIES_TRACKERS
from src.backend.trackers.morethantv import MTVUploader
from src.backend.trackers.torrentleech import TLUploader
from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.backend.trackers.utils import format_image_tag
from src.backend.upload_retry import (
    UploadFailure,
    UploadFailurePhase,
    UploadRetryAction,
)
from src.backend.utils.anime import is_anime_release
from src.backend.utils.image_optimizer import MultiProcessImageOptimizer
from src.backend.utils.images import (
    format_image_data_to_comparison,
    format_image_data_to_str,
    get_parity_images,
    get_parity_images_to_str,
)
from src.backend.utils.token_utils import get_prompt_tokens
from src.config.config import ConfigManager
from src.config.tv_tokens import get_tvr_title_token
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.token_replacer import UnfilledTokenRemoval
from src.enums.torrent_client import TorrentClientSelection
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import ImageHostError, ProcessCancelled, TrackerError
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import ImageUploadData, ImageUploadFromTo
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.series import SeriesReleaseInfo, build_series_release_info
from src.payloads.tracker_search_result import TrackerSearchResult
from src.payloads.trackers import TrackerInfo
from src.payloads.watch_folder import WatchFolder


class ProcessBackEnd:
    AUTOMATIC_UPLOAD_ATTEMPTS = 3

    def __init__(self, config: ConfigManager) -> None:
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
        processing_queue: list[TrackerSelection],
        media_input_payload: MediaInputPayload,
        media_search_payload: MediaSearchPayload,
    ) -> dict[
        TrackerSelection, tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]
    ]:
        # TODO: test this when we add disc & tv support, as this will likely require different
        # checks to accurately obtain dupes
        tasks = []
        release_info = build_series_release_info(media_input_payload)
        for tracker_sel in processing_queue:
            if release_info.is_series and tracker_sel in UNSUPPORTED_SERIES_TRACKERS:
                tasks.append(
                    self._unsupported_series_tracker_dupe(
                        tracker_sel=tracker_sel,
                    )
                )
                continue
            file_input = media_input_payload.require_first_file()
            search_input = release_info.search_path or file_input
            if tracker_sel is TrackerSelection.MORE_THAN_TV:
                tasks.append(
                    self._dupe_mtv(
                        tracker_sel=tracker_sel,
                        # file_input prioritizes folder name > file since the api doesn't
                        # support directly looking for files
                        file_input=search_input,
                        media_search_payload=media_search_payload,
                    )
                )
            elif tracker_sel is TrackerSelection.TORRENT_LEECH:
                tasks.append(
                    self._dupe_tl(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.BEYOND_HD:
                tasks.append(
                    self._dupe_bhd(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.PASS_THE_POPCORN:
                tasks.append(
                    self._dupe_ptp(
                        tracker_sel=tracker_sel,
                        # file_input prioritizes folder name > file since the api doesn't
                        # support directly looking for files
                        file_input=search_input,
                        media_search_payload=media_search_payload,
                    )
                )
            elif tracker_sel is TrackerSelection.REELFLIX:
                tasks.append(
                    self._dupe_rf(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.AITHER:
                tasks.append(
                    self._dupe_aither(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.HUNO:
                tasks.append(
                    self._dupe_huno(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.LST:
                tasks.append(
                    self._dupe_lst(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.DARK_PEERS:
                tasks.append(
                    self._dupe_dp(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.SHARE_ISLAND:
                tasks.append(
                    self._dupe_shri(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.UPLOAD_CX:
                tasks.append(
                    self._dupe_ulcx(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.ONLY_ENCODES:
                tasks.append(
                    self._dupe_oe(tracker_sel=tracker_sel, file_input=search_input)
                )

        async_results = await asyncio.gather(*tasks, return_exceptions=True)

        dupes: dict[
            TrackerSelection,
            tuple[TrackerSelection, bool, list[TrackerSearchResult] | str],
        ] = {}
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

    async def _unsupported_series_tracker_dupe(
        self, tracker_sel: TrackerSelection
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return tracker_sel, False, f"{tracker_sel} does not support series uploads yet"

    async def _dupe_mtv(
        self,
        tracker_sel: TrackerSelection,
        file_input: Path,
        media_search_payload: MediaSearchPayload,
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.settings.trackers.more_than_tv.api_key
        if not api_key:
            return tracker_sel, False, "MTV API key missing"
        try:
            imdb_id = media_search_payload.imdb_id
            tmdb_id = media_search_payload.tmdb_id
            tvdb_id = media_search_payload.tvdb_id
            if not file_input or not imdb_id or (not tmdb_id and not tvdb_id):
                return (
                    tracker_sel,
                    False,
                    "Required MTV search parameters missing",
                )
            mtv_search = MTVSearch(
                api_key,
                timeout=self.config.settings.general.timeout,
            ).search(
                title=file_input.stem,  # must not have an extension
                imdb_id=imdb_id,
                tmdb_id=tmdb_id,
                tvdb_id=tvdb_id,
            )
            if mtv_search:
                return tracker_sel, True, mtv_search
            else:
                return tracker_sel, True, []
        except Exception as e:
            return tracker_sel, False, str(e)

    async def _dupe_tl(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        username = self.config.settings.trackers.torrent_leech.username
        password = self.config.settings.trackers.torrent_leech.password
        if not username or not password:
            return (
                tracker_sel,
                False,
                "TL username or password missing",
            )
        try:
            tl_search = TLSearch(
                username=username,
                password=password,
                cookie_dir=self.config.paths.tracker_cookies,
                alt_2_fa_token=self.config.settings.trackers.torrent_leech.alt_2_fa_token,
                timeout=self.config.settings.general.timeout,
            ).search(file_input)
            if tl_search:
                return tracker_sel, True, tl_search
            else:
                return tracker_sel, True, []
        except Exception as e:
            return tracker_sel, False, str(e)

    async def _dupe_bhd(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_key = self.config.settings.trackers.beyond_hd.api_key
        rss_key = self.config.settings.trackers.beyond_hd.rss_key
        if not api_key or not rss_key:
            return (
                tracker_sel,
                False,
                "BHD API key or RSS key missing",
            )
        try:
            bhd_search = BHDSearch(
                api_key=api_key,
                rss_key=rss_key,
                timeout=self.config.settings.general.timeout,
            ).search(file_input)
            if bhd_search:
                return tracker_sel, True, bhd_search
            else:
                return tracker_sel, True, []
        except Exception as e:
            return tracker_sel, False, str(e)

    async def _dupe_ptp(
        self,
        tracker_sel: TrackerSelection,
        file_input: Path,
        media_search_payload: MediaSearchPayload,
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        api_user = self.config.settings.trackers.pass_the_popcorn.api_user
        api_key = self.config.settings.trackers.pass_the_popcorn.api_key
        title = media_search_payload.title
        year = media_search_payload.year
        imdb_id = media_search_payload.imdb_id
        if not api_user or not api_key or not title or year is None or not imdb_id:
            return (
                tracker_sel,
                False,
                "PTP API user/key or search parameters missing",
            )
        try:
            ptp_search = PTPSearch(
                api_user=api_user,
                api_key=api_key,
                timeout=self.config.settings.general.timeout,
            ).search(
                movie_title=title,
                movie_year=year,
                file_name=file_input.stem if file_input.is_dir() else file_input.name,
                imdb_id=imdb_id,
            )
            if ptp_search:
                return tracker_sel, True, ptp_search
            else:
                return tracker_sel, True, []
        except Exception as e:
            return tracker_sel, False, str(e)

    async def _dupe_rf(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            ReelFlixSearch,
            {"api_key": self.config.settings.trackers.reelflix.api_key},
        )

    async def _dupe_aither(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            AitherSearch,
            {"api_key": self.config.settings.trackers.aither.api_key},
        )

    async def _dupe_huno(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            HunoSearch,
            {"api_key": self.config.settings.trackers.huno.api_key},
        )

    async def _dupe_lst(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            LSTSearch,
            {"api_key": self.config.settings.trackers.lst.api_key},
        )

    async def _dupe_dp(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            DarkPeersSearch,
            {"api_key": self.config.settings.trackers.dark_peers.api_key},
        )

    async def _dupe_shri(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            ShareIslandSearch,
            {"api_key": self.config.settings.trackers.share_island.api_key},
        )

    async def _dupe_ulcx(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            UploadCXSearch,
            {"api_key": self.config.settings.trackers.upload_cx.api_key},
        )

    async def _dupe_oe(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            OnlyEncodesSearch,
            {"api_key": self.config.settings.trackers.only_encodes.api_key},
        )

    async def _aither_dupe_check(
        self,
        tracker_sel: TrackerSelection,
        file_input: Path,
        search_cls: type[Unit3dBaseSearch],
        kwargs: dict[str, Any],
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        """Used solely for UNIT3D trackers."""
        try:
            # check to ensure we have data
            for k, v in kwargs.items():
                if not v:
                    return tracker_sel, False, f"{tracker_sel} key '{k}' is missing"
            # execute the search
            search = search_cls(**kwargs).search(file_name=file_input.name)
            if search:
                return tracker_sel, True, search
            else:
                return tracker_sel, True, []
        except Exception as e:
            return tracker_sel, False, str(e)

    @staticmethod
    def _upload_error_phase(error: Exception) -> UploadFailurePhase:
        phase = getattr(error, "phase", None)
        if phase == "health_check":
            return UploadFailurePhase.HEALTH_CHECK
        if phase == "download":
            return UploadFailurePhase.DOWNLOAD
        if phase == "injection":
            return UploadFailurePhase.INJECTION
        return UploadFailurePhase.UPLOAD

    @staticmethod
    def _is_automatic_upload_retryable(error: BaseException) -> bool:
        """Return whether retrying the upload request is safe enough to automate."""
        if getattr(error, "server_accepted", False):
            # The POST may already have succeeded. Retrying the whole upload can
            # create a duplicate; only an explicit user decision may continue.
            return False

        retryable = getattr(error, "retryable", None)
        if retryable is not None:
            return bool(retryable)

        status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int):
            return status_code == 408 or status_code == 429 or status_code >= 500

        if isinstance(error, niquests.exceptions.RequestException):
            return True
        if isinstance(error.__cause__, niquests.exceptions.RequestException):
            return True
        if isinstance(error.__context__, niquests.exceptions.RequestException):
            return True

        message = str(error).lower()
        return any(
            marker in message
            for marker in (
                "timed out",
                "timeout",
                "connection reset",
                "connection aborted",
                "temporarily unavailable",
                "service unavailable",
                "http 408",
                "http 429",
                "http 500",
                "http 502",
                "http 503",
                "http 504",
                "status code: 408",
                "status code: 429",
                "status code: 500",
                "status code: 502",
                "status code: 503",
                "status code: 504",
            )
        )

    def _upload_tracker_with_retry(
        self,
        *,
        tracker: TrackerSelection,
        torrent_path: Path,
        tracker_health_cache: dict[TrackerSelection, bool],
        upload_request: Callable[[], Path | bool | str | None],
        queued_status_update: Callable[[str, str], None],
        queued_text_update: Callable[[str], None],
        caught_error: SignalInstance,
        upload_retry_cb: Callable[[UploadFailure], UploadRetryAction] | None,
    ) -> tuple[Path | bool | str | None, bool]:
        """Run one tracker upload with bounded automatic and user retries."""
        total_attempts = 0
        manual_retries = 0

        while True:

            def upload_once() -> Path | bool | str:
                nonlocal total_attempts
                total_attempts += 1
                if total_attempts > 1:
                    # A previous health result may have become stale while the
                    # user waited or the automatic backoff elapsed.
                    tracker_health_cache.pop(tracker, None)
                ensure_tracker_health(
                    tracker=tracker,
                    timeout=self.config.settings.general.timeout,
                    cache=tracker_health_cache,
                )
                result = upload_request()
                if not result:
                    raise TrackerError(
                        f"{tracker} did not report a successful upload",
                        retryable=False,
                    )
                return result

            def before_sleep(retry_state: object) -> None:
                # Retrying's concrete state exposes the attempt number, but the
                # callback is intentionally kept duck-typed for static checks.
                attempt_number = getattr(retry_state, "attempt_number", total_attempts)
                tracker_health_cache.pop(tracker, None)
                queued_status_update(
                    str(tracker),
                    f"↻ Retrying upload ({attempt_number}/{self.AUTOMATIC_UPLOAD_ATTEMPTS})",
                )
                queued_text_update(
                    f"<br /><span>Temporary upload failure for <b>{tracker}</b>; "
                    f"retrying ({attempt_number}/{self.AUTOMATIC_UPLOAD_ATTEMPTS})</span>"
                )

            try:
                retrying = Retrying(
                    retry=retry_if_exception(self._is_automatic_upload_retryable),
                    stop=stop_after_attempt(self.AUTOMATIC_UPLOAD_ATTEMPTS),
                    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
                    before_sleep=before_sleep,
                    reraise=True,
                )
                return retrying(upload_once), False
            except ProcessCancelled:
                raise
            except Exception as error:
                retryable = self._is_automatic_upload_retryable(error)
                failure = UploadFailure(
                    tracker=tracker,
                    phase=self._upload_error_phase(error),
                    message=str(error),
                    attempt=total_attempts,
                    automatic_attempts=self.AUTOMATIC_UPLOAD_ATTEMPTS,
                    retryable=retryable,
                    server_accepted=bool(getattr(error, "server_accepted", False)),
                    torrent_path=torrent_path,
                )
                queued_status_update(str(tracker), "⚠️ Failed - awaiting action")
                queued_text_update(
                    f'<br /><span style="font-weight: bold; color: red;">'
                    f"Upload failed for {tracker}: {error}</span>"
                )
                caught_error.emit(f"Upload Error: {traceback.format_exc()}")

                if upload_retry_cb is None:
                    return None, False

                action = upload_retry_cb(failure)
                if action is UploadRetryAction.RETRY:
                    manual_retries += 1
                    queued_status_update(
                        str(tracker),
                        f"↻ Retrying upload (manual attempt {manual_retries})",
                    )
                    continue
                if action is UploadRetryAction.CANCEL:
                    queued_status_update(str(tracker), "⏹ Cancelled")
                    raise ProcessCancelled from error
                queued_status_update(str(tracker), "⏭ Skipped")
                return None, True

    def process_trackers(
        self,
        process_dict: dict[str, Any],
        queued_status_update: Callable[[str, str], None],
        queued_text_update: Callable[[str], None],
        queued_text_update_replace_last_line: Callable[[str], None],
        progress_bar_cb: Callable[[float], None],
        caught_error: SignalInstance,
        context: ProcessingContext,
        token_prompt_cb: Callable[[Sequence[str] | None], dict[str, str] | None]
        | None = None,
        overview_cb: Callable[
            [dict[TrackerSelection, dict[str, str | None]] | None],
            dict[TrackerSelection, dict[str, str | None]] | None,
        ]
        | None = None,
        upload_retry_cb: Callable[[UploadFailure], UploadRetryAction] | None = None,
    ) -> None:
        # make sure we have all the latest templates in case changes was made during the wizard
        self.template_selector_be.load_templates()

        # handle image uploading
        images = self.handle_images_for_trackers(
            context, process_dict, queued_text_update, progress_bar_cb
        )

        self.progress_bar_cb = progress_bar_cb
        base_torrent_file: Path | None = None
        tracker_health_cache: dict[TrackerSelection, bool] = {}

        # determine maximum piece size for the current tracker(s)
        max_piece_size = self.determine_max_piece_size(process_dict)
        if max_piece_size:
            queued_text_update(
                '<br /><h3 style="margin-bottom: 0; padding-bottom: 0;">🔎 Detected maximum piece size:</h3>'
            )
            queued_text_update(f"<br /><span>{max_piece_size} (bytes)</span>")

        # get media input - use context instead of config
        media_input = context.media_input.require_input_path()
        release_info = build_series_release_info(context.media_input)

        # process
        queued_text_update(
            '<br /><h3 style="margin-bottom: 0; padding-bottom: 0;">🌐 Trackers:'
        )

        # base user tokens, this will be filled with prompt tokens as well if needed
        base_usr_tokens: dict[str, str] = {}

        # find all prompt tokens
        if token_prompt_cb:
            all_prompt_tokens: list[str] = []
            for tracker_name in process_dict.keys():
                cur_tracker = TrackerSelection(tracker_name)
                tracker_info = self.config.settings.trackers.by_selection()[cur_tracker]
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
        tracker_release_data: dict[TrackerSelection, dict[str, str | None]] = {}
        queued_text_update("<br /><span>Generating tracker titles and NFOs</span>")
        for tracker_name in process_dict.keys():
            cur_tracker = TrackerSelection(tracker_name)
            tracker_info = self.config.settings.trackers.by_selection()[cur_tracker]

            # generate tracker title first
            tracker_title = None
            generated_tracker_title = self.generate_tracker_title(
                tracker_info=tracker_info,
                context=context,
                release_info=release_info,
            )
            if generated_tracker_title:
                tracker_title = self.tracker_title_formatting(
                    cur_tracker, generated_tracker_title
                )

            nfo_template = self.template_selector_be.read_template(
                name=tracker_info.nfo_template
            )
            user_tokens = base_usr_tokens | {
                k: v for k, (v, _) in self.config.settings.user_tokens.tokens.items()
            }
            nfo = ""
            tracker_images = None
            format_images_to_str: str | None = None
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
                if context.shared_data.is_comparison_images:
                    comparison_screens = format_image_data_to_comparison(tracker_images)
                    even_screens = get_parity_images(data=tracker_images)
                    odd_screens = get_parity_images(data=tracker_images, even=False)
                    even_screens_str = get_parity_images_to_str(data=tracker_images)
                    odd_screens_str = get_parity_images_to_str(
                        data=tracker_images, even=False
                    )
            if nfo_template:
                nfo_output = TokenReplacer(
                    media_input_obj=context.media_input,
                    jinja_engine=context.jinja_engine,
                    token_string=nfo_template,
                    media_search_obj=context.media_search,
                    unfilled_token_mode=UnfilledTokenRemoval.KEEP,
                    releasers_name=self.config.settings.general.releasers_name,
                    screen_shots=formatted_screens,
                    screen_shots_comparison=comparison_screens,
                    screen_shots_even_obj=even_screens,
                    screen_shots_odd_obj=odd_screens,
                    screen_shots_even_str=even_screens_str,
                    screen_shots_odd_str=odd_screens_str,
                    release_notes=context.shared_data.release_notes,
                    edition_override=context.shared_data.dynamic_data.get(
                        "edition_override"
                    ),
                    frame_size_override=context.shared_data.dynamic_data.get(
                        "frame_size_override"
                    ),
                    override_tokens=context.shared_data.dynamic_data.get(
                        "override_tokens"
                    ),
                    user_tokens=user_tokens,
                    title_clean_rules=self.config.settings.global_management.title_clean_rules,
                    video_dynamic_range=self.config.settings.global_management.video_dynamic_range,
                    **self._release_info_token_kwargs(
                        release_info,
                        self.config.settings.series.multi_episode_style,
                    ),
                ).get_output()
                if not isinstance(nfo_output, str):
                    raise ValueError("NFO should be a string")
                nfo = nfo_output

            # run token replacer plugin if available
            if self.config.settings.general.enable_plugins:
                token_replacer_plugin = self.config.settings.plugins.token_replacer
                if token_replacer_plugin:
                    nfo_plugin = self.config.plugin_registry.plugins[
                        token_replacer_plugin
                    ].token_replacer
                    if nfo_plugin and callable(nfo_plugin):
                        LOG.info(
                            LOG.LOG_SOURCE.BE,
                            f"Running token replacer plugin for tracker: {tracker_name}",
                        )
                        replace_tokens = nfo_plugin(
                            config=self.config,
                            context=context,
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
        if self.config.settings.general.enable_prompt_overview and overview_cb:
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
            tracker_info = self.config.settings.trackers.by_selection()[cur_tracker]

            # get tracker title and nfo data
            cur_tracker_release_data = tracker_release_data.get(cur_tracker, {})
            cur_tracker_title = cur_tracker_release_data.get("title") or ""

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
                    if self.config.settings.general.enable_mkbrr and (
                        self.config.settings.dependencies.mkbrr
                        and self.config.settings.dependencies.mkbrr.exists()
                    ):
                        queued_text_update(
                            '<br /><span>Generating torrent with <span style="font-weight: bold;">'
                            "mkbrr</span></span>"
                        )
                        torrent = mkbrr_generate_torrent(
                            mkbrr_path=self.config.settings.dependencies.mkbrr,
                            tracker_info=tracker_info,
                            path=media_input,
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
                        self.config.settings.general.enable_mkbrr
                        and self.config.settings.dependencies.mkbrr
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
                        path=media_input,
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

            nfo = cur_tracker_release_data.get("nfo") or ""
            if nfo:
                with open(
                    torrent_path.with_suffix(".nfo"), "w", encoding="utf-8"
                ) as log_out:
                    log_out.write(nfo)

            # pre upload plugin
            pre_upload_processing = None
            if self.config.settings.general.enable_plugins:
                pre_upload_plugin = self.config.settings.plugins.pre_upload
                if pre_upload_plugin:
                    get_pre_upload_plugin = self.config.plugin_registry.plugins[
                        pre_upload_plugin
                    ].pre_upload
                    if get_pre_upload_plugin and callable(get_pre_upload_plugin):
                        pre_upload_processing = get_pre_upload_plugin(
                            config=self.config,
                            context=context,
                            tracker=cur_tracker,
                            torrent_file=torrent_path,
                            upload_text_cb=queued_text_update,
                            upload_text_replace_last_line_cb=queued_text_update_replace_last_line,
                            progress_cb=self.progress_bar_cb,
                        )

            # upload
            if tracker_info.upload_enabled and pre_upload_processing is not False:
                queued_text_update("<br /><span>Checking tracker availability</span>")
                execute_upload = None
                skipped_upload = False
                try:
                    queued_text_update("<br /><span>Uploading release</span>")
                    execute_upload, skipped_upload = self._upload_tracker_with_retry(
                        tracker=cur_tracker,
                        torrent_path=torrent_path,
                        tracker_health_cache=tracker_health_cache,
                        upload_request=lambda: self.upload(
                            tracker=cur_tracker,
                            torrent_file=torrent_path,
                            nfo=nfo,
                            tracker_title=cur_tracker_title,
                            context=context,
                            release_info=release_info,
                        ),
                        queued_status_update=queued_status_update,
                        queued_text_update=queued_text_update,
                        caught_error=caught_error,
                        upload_retry_cb=upload_retry_cb,
                    )
                except ProcessCancelled:
                    for remaining_tracker in list(process_dict)[idx:]:
                        queued_status_update(remaining_tracker, "⏹ Cancelled")
                    self.disconnect_from_clients()
                    raise
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
                    if skipped_upload:
                        queued_text_update(
                            "<br /><span>Skipped upload after user decision</span>"
                        )
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
        context: ProcessingContext,
        process_dict: dict[str, Any],
        queued_text_update: Callable[[str], None],
        progress_bar_cb: Callable[[float], None],
    ) -> dict[TrackerSelection, dict[int, ImageUploadData]]:
        """
        Handles the uploading of images for various trackers based on the provided process dictionary.

        This function determines the image sources and destinations, downloads images if necessary,
        and uploads them to the specified image hosts.

        Args:
            context (ProcessingContext): The processing context containing state data.
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
        tracker_to_host_map: dict[TrackerSelection, ImageHost | ImageSource] = {}
        img_from: ImageSource | None = None
        files_to_upload: Sequence[Path] | None = None

        url_data: dict[TrackerSelection, dict[int, ImageUploadData]] = {}

        # build tracker_to_host_map and determine where the images are from/to
        for tracker_name, data in process_dict.items():
            image_host_data = data["image_host_data"]

            if isinstance(image_host_data, ImageUploadFromTo):
                if not img_from:
                    img_from = image_host_data.img_from
                img_to = image_host_data.img_to
                LOG.debug(
                    LOG.LOG_SOURCE.BE,
                    f"Image destination for {tracker_name}: {img_to!r} (from {image_host_data.img_from!r})",
                )

                # track the image host to be used for each tracker
                if isinstance(img_to, ImageHost) and img_to is not ImageHost.DISABLED:
                    to_image_hosts.add(img_to)
                elif not to_url and img_to is ImageSource.URLS:
                    to_url = True

                tracker_to_host_map[TrackerSelection(tracker_name)] = img_to
            else:
                # the tracker cannot be mapped to a destination at all, so it will
                # reach the NFO stage with no images and no other explanation
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"No usable image host data for {tracker_name}, expected ImageUploadFromTo "
                    f"and got {type(image_host_data).__name__}: {image_host_data!r}",
                )

        # handle image host uploads
        if to_image_hosts or to_url:
            queued_text_update(
                '<br /><h3 style="margin-bottom: 0; padding-bottom: 0;">🎥 Image Handling:</h3>'
            )
        if to_image_hosts:
            if img_from is ImageSource.URLS:
                queued_text_update(
                    f"<br />Attempting to download {len(context.shared_data.url_data)} user-provided URL(s)",
                )

                if not context.media_input.working_dir:
                    raise FileNotFoundError("Working directory was not found")
                img_output_path = context.media_input.working_dir / "dl_imgs"
                img_downloader = ImageDownloader(
                    context.shared_data.url_data,
                    img_output_path,
                    progress_bar_cb,
                )
                files_to_upload = img_downloader.download_images()
                context.shared_data.loaded_images = files_to_upload

                queued_text_update(
                    f"<br />Successfully downloaded {len(files_to_upload)} user-provided URL(s)",
                )
            else:
                files_to_upload = context.shared_data.loaded_images

            if not files_to_upload:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"No images available to upload to {len(to_image_hosts)} image host(s), "
                    "every tracker will be processed without images",
                )
                queued_text_update(
                    "<br />No images available to upload, continuing without images"
                )

            if files_to_upload:
                # optimize images if enabled
                # if we have generated images and optimization for generated images is enabled
                # or
                # if we don't have user generated images and optimize download/url images is enabled or images
                # are downloaded from URLs
                if (
                    context.shared_data.generated_images
                    and self.config.settings.screenshots.optimize_generated_images
                ) or (
                    not context.shared_data.generated_images
                    and self.config.settings.screenshots.optimize_downloaded_images
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

                LOG.debug(
                    LOG.LOG_SOURCE.BE,
                    f"Upload results returned for image host(s): {sorted(str(h) for h in upload_results)}",
                )

                # map the uploaded image hosts to the appropriate trackers
                for tracker, img_host in tracker_to_host_map.items():
                    if img_host in upload_results:
                        url_data[tracker] = upload_results[img_host]
                    else:
                        LOG.debug(
                            LOG.LOG_SOURCE.BE,
                            f"No uploaded images for {tracker}, its destination {img_host!r} "
                            "was not part of this upload",
                        )

        # using URLs as is
        if to_url:
            url_host_count = 0
            for tracker, img_host in tracker_to_host_map.items():
                if img_host is ImageSource.URLS:
                    url_data[tracker] = {
                        i: img_data
                        for i, img_data in enumerate(context.shared_data.url_data)
                    }
                    url_host_count += 1

            queued_text_update(
                f"<br />Using {len(context.shared_data.url_data)} URLs for {url_host_count} tracker(s)",
            )

        # trackers missing here reach the NFO stage with no images, which is a
        # supported outcome but an easy one to mistake for a failure, so say so
        without_images = [
            str(TrackerSelection(tracker_name))
            for tracker_name in process_dict
            if TrackerSelection(tracker_name) not in url_data
        ]
        if without_images:
            LOG.info(
                LOG.LOG_SOURCE.BE,
                f"Tracker(s) with no images: {', '.join(without_images)}",
            )
        LOG.debug(
            LOG.LOG_SOURCE.BE,
            "Image handling resolved "
            f"{ {str(tracker): len(imgs) for tracker, imgs in url_data.items()} }",
        )

        return url_data

    def _optimize_images(
        self, progress_bar_cb: Callable[[float], None], files_to_upload: Sequence[Path]
    ) -> Sequence[Path]:
        """Optimizes images and returns the optimized images in a list"""

        def img_optimizer_job_done_callback(
            _png_path: Path, completed: int, total: int
        ) -> None:
            progress_bar_cb(completed / total * 100)

        image_optimizer = MultiProcessImageOptimizer(
            on_job_done=img_optimizer_job_done_callback,
            cpu_fraction=self.config.settings.screenshots.optimize_downloaded_images_percentage,
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

        def progress_callback(_job: str, _ind: float, overall: float) -> None:
            progress_bar_cb(overall)

        image_uploader = ImageUploader(progress_signal=progress_callback)

        jobs: dict[str, ImageHost] = {}
        host_to_job: dict[ImageHost, str] = {}

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
        jobs: dict[str, ImageHost],
        host_to_job: dict[ImageHost, str],
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

            job_id = image_uploader.add_job(
                str(img_host), ImageUploadRequest(filepaths=filepaths)
            )
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
        chv4_payload = self.config.settings.image_hosts.chevereto_v4
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
        chv3_payload = self.config.settings.image_hosts.chevereto_v3
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
        imgbb_payload = self.config.settings.image_hosts.image_bb
        if not imgbb_payload.api_key or not imgbb_payload.base_url:
            raise ImageHostError("Missing 'API Key' for ImageBB.")
        return ImageBBUploader(api_key=imgbb_payload.api_key)

    def _map_uploaded_urls(
        self,
        host_to_job: dict[ImageHost, str],
        results: dict[str, dict[int, ImageUploadData]],
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
            max_piece_size = self.config.settings.trackers.by_selection()[
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
        nfo: str,
        tracker_title: str,
        context: ProcessingContext,
        release_info: SeriesReleaseInfo,
    ) -> Path | bool | str | None:
        first_file = context.media_input.require_first_file()
        mediainfo_obj = context.media_input.require_mediainfo(first_file)
        media_search_obj = context.media_search
        media_type = context.media_input.require_media_type()
        if media_type is MediaType.SERIES and tracker in UNSUPPORTED_SERIES_TRACKERS:
            raise TrackerError(f"{tracker} does not support series uploads yet")
        input_path = first_file
        if media_type is not MediaType.SERIES:
            input_path = context.media_input.require_input_path()

        if tracker is TrackerSelection.MORE_THAN_TV:
            tracker_payload = self.config.settings.trackers.more_than_tv
            if not tracker_payload.username or not tracker_payload.password:
                raise TrackerError("Username and password is required for MoreThanTV")
            return cast(
                Path | bool | str | None,
                mtv_uploader(
                    username=tracker_payload.username,
                    password=tracker_payload.password,
                    totp=tracker_payload.totp,
                    nfo=nfo,
                    group_desc=tracker_payload.group_description,
                    torrent_file=torrent_file,
                    input_path=input_path,
                    tracker_title=tracker_title,
                    mediainfo_obj=mediainfo_obj,
                    genre_ids=media_search_obj.genres,
                    media_type=media_type,
                    is_pack=release_info.is_pack,
                    anonymous=bool(tracker_payload.anonymous),
                    source_origin=tracker_payload.source_origin,
                    cookie_dir=self.config.paths.tracker_cookies,
                    timeout=self.config.settings.general.timeout,
                ),
            )
        elif tracker is TrackerSelection.TORRENT_LEECH:
            announce_key = self.config.settings.trackers.torrent_leech.torrent_passkey
            if not announce_key:
                raise TrackerError("Missing announce key for TorrentLeech")
            return tl_upload(
                announce_key=announce_key,
                nfo=nfo,
                tracker_title=tracker_title,
                torrent_file=torrent_file,
                mediainfo_obj=mediainfo_obj,
                media_type=media_type,
                is_pack=release_info.is_pack,
                is_anime=is_anime_release(context.media_input, media_search_obj),
                timeout=self.config.settings.general.timeout,
            )
        elif tracker is TrackerSelection.BEYOND_HD:
            bhd_payload = self.config.settings.trackers.beyond_hd
            if not bhd_payload.api_key:
                raise TrackerError("Missing API key for BeyondHD")

            # get edition from shared data
            edition = context.shared_data.dynamic_data.get("edition_override")

            # get localization from override tokens
            override_tokens = context.shared_data.dynamic_data.get(
                "override_tokens", {}
            )
            localization = override_tokens.get("localization")

            return bhd_uploader(
                api_key=bhd_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                media_type=media_type,
                imdb_id=media_search_obj.imdb_id,
                tmdb_id=media_search_obj.tmdb_id,
                nfo=nfo,
                is_pack=release_info.is_pack,
                is_special=release_info.is_special,
                internal=bool(bhd_payload.internal),
                live_release=bhd_payload.live_release,
                anonymous=bool(bhd_payload.anonymous),
                promo=bhd_payload.promo,
                timeout=self.config.settings.general.timeout,
                edition=edition,
                localization=localization,
                add_localization_to_custom_edition=bhd_payload.add_localization_to_custom_edition,
                stream_optimized=bhd_payload.stream_optimized,
            )
        elif tracker is TrackerSelection.PASS_THE_POPCORN:
            ptp_payload = self.config.settings.trackers.pass_the_popcorn
            if (
                not ptp_payload.api_user
                or not ptp_payload.api_key
                or not ptp_payload.username
                or not ptp_payload.password
                or not ptp_payload.announce_url
            ):
                raise TrackerError(
                    "TorrentLeech requires API user, API key, username, password, and announce URL"
                )
            return ptp_uploader(
                api_user=ptp_payload.api_user,
                api_key=ptp_payload.api_key,
                username=ptp_payload.username,
                password=ptp_payload.password,
                announce_url=ptp_payload.announce_url,
                torrent_file=torrent_file,
                input_path=input_path,
                nfo=nfo,
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                cookie_dir=self.config.paths.tracker_cookies,
                totp=ptp_payload.totp,
                timeout=self.config.settings.general.timeout,
            )
        # Unit3d trackers
        elif tracker is TrackerSelection.REELFLIX:
            rf_payload = self.config.settings.trackers.reelflix
            if not rf_payload.api_key:
                raise TrackerError("Missing API key for ReelFliX")
            return rf_uploader(
                media_type=media_type,
                api_key=rf_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(rf_payload.internal),
                anonymous=bool(rf_payload.anonymous),
                personal_release=bool(rf_payload.personal_release),
                stream_optimized=bool(rf_payload.stream_optimized),
                opt_in_to_mod_queue=bool(rf_payload.opt_in_to_mod_queue),
                featured=bool(rf_payload.featured),
                free=bool(rf_payload.free),
                double_up=bool(rf_payload.double_up),
                sticky=bool(rf_payload.sticky),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
            )
        elif tracker is TrackerSelection.AITHER:
            aither_payload = self.config.settings.trackers.aither
            if not aither_payload.api_key:
                raise TrackerError("Missing API key for Aither")
            return aither_uploader(
                media_type=media_type,
                api_key=aither_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(aither_payload.internal),
                anonymous=bool(aither_payload.anonymous),
                personal_release=bool(aither_payload.personal_release),
                stream_optimized=bool(aither_payload.stream_optimized),
                opt_in_to_mod_queue=bool(aither_payload.opt_in_to_mod_queue),
                featured=bool(aither_payload.featured),
                free=bool(aither_payload.free),
                double_up=bool(aither_payload.double_up),
                sticky=bool(aither_payload.sticky),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.HUNO:
            huno_payload = self.config.settings.trackers.huno
            if not huno_payload.api_key:
                raise TrackerError("Missing API key for HUNO")
            return huno_uploader(
                media_type=media_type,
                api_key=huno_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(huno_payload.internal),
                anonymous=bool(huno_payload.anonymous),
                stream_optimized=bool(huno_payload.stream_optimized),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.LST:
            lst_payload = self.config.settings.trackers.lst
            if not lst_payload.api_key:
                raise TrackerError("Missing API key for LST")
            return lst_uploader(
                media_type=media_type,
                api_key=lst_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(lst_payload.internal),
                anonymous=bool(lst_payload.anonymous),
                personal_release=bool(lst_payload.personal_release),
                opt_in_to_mod_queue=bool(lst_payload.mod_queue_opt_in),
                draft_queue_opt_in=bool(lst_payload.draft_queue_opt_in),
                featured=bool(lst_payload.featured),
                free=bool(lst_payload.free),
                double_up=bool(lst_payload.double_up),
                sticky=bool(lst_payload.sticky),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.DARK_PEERS:
            dp_payload = self.config.settings.trackers.dark_peers
            if not dp_payload.api_key:
                raise TrackerError("Missing API key for DarkPeers")
            return dp_uploader(
                media_type=media_type,
                api_key=dp_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(dp_payload.internal),
                anonymous=bool(dp_payload.anonymous),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.SHARE_ISLAND:
            shri_payload = self.config.settings.trackers.share_island
            if not shri_payload.api_key:
                raise TrackerError("Missing API key for ShareIsland")
            return shri_uploader(
                media_type=media_type,
                api_key=shri_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(shri_payload.internal),
                anonymous=bool(shri_payload.anonymous),
                personal_release=bool(shri_payload.personal_release),
                opt_in_to_mod_queue=bool(shri_payload.opt_in_to_mod_queue),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.UPLOAD_CX:
            ulcx_payload = self.config.settings.trackers.upload_cx
            if not ulcx_payload.api_key:
                raise TrackerError("Missing API key for UploadCX")
            return ulcx_uploader(
                media_type=media_type,
                api_key=ulcx_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(ulcx_payload.internal),
                anonymous=bool(ulcx_payload.anonymous),
                personal_release=bool(ulcx_payload.personal_release),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.ONLY_ENCODES:
            oe_payload = self.config.settings.trackers.only_encodes
            if not oe_payload.api_key:
                raise TrackerError("Missing API key for OnlyEncodes")
            return oe_uploader(
                media_type=media_type,
                api_key=oe_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(oe_payload.internal),
                anonymous=bool(oe_payload.anonymous),
                personal_release=bool(oe_payload.personal_release),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )

    def generate_tracker_title(
        self,
        tracker_info: TrackerInfo,
        context: ProcessingContext,
        release_info: SeriesReleaseInfo,
    ) -> str | None:
        if release_info.is_series:
            default_title = get_tvr_title_token(
                self.config.settings.series,
                release_info.episode_format,
            )
            series_override = tracker_info.tvr_title_overrides.get(
                release_info.episode_format
            )
            override_enabled = bool(series_override and series_override.enabled)
            token_string = (
                series_override.token
                if (
                    override_enabled
                    and series_override is not None
                    and series_override.token
                )
                else default_title
            )
            colon_replace = (
                series_override.colon_replace
                if override_enabled and series_override is not None
                else self.config.settings.series.title_colon_replace
            )
            override_title_rules = (
                series_override.replace_map
                if (
                    override_enabled
                    and series_override is not None
                    and series_override.replace_map
                )
                else None
            )
        else:
            token_string = (
                tracker_info.mvr_title_token_override
                if (
                    tracker_info.mvr_title_token_override
                    and tracker_info.mvr_title_override_enabled
                )
                else self.config.settings.movie.title_token
            )
            colon_replace = (
                tracker_info.mvr_title_colon_replace
                if (
                    tracker_info.mvr_title_colon_replace
                    and tracker_info.mvr_title_override_enabled
                )
                else self.config.settings.movie.title_colon_replace
            )
            override_title_rules = (
                tracker_info.mvr_title_replace_map
                if (
                    tracker_info.mvr_title_replace_map
                    and tracker_info.mvr_title_override_enabled
                )
                else None
            )
        user_tokens = {
            k: v
            for k, (v, t) in self.config.settings.user_tokens.tokens.items()
            if TokenSelection(t) is TokenSelection.FILE_TOKEN
        }
        format_str = TokenReplacer(
            media_input_obj=context.media_input,
            token_string=token_string,
            colon_replace=colon_replace,
            media_search_obj=context.media_search,
            flatten=True,
            file_name_mode=False,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            edition_override=context.shared_data.dynamic_data.get("edition_override"),
            frame_size_override=context.shared_data.dynamic_data.get(
                "frame_size_override"
            ),
            override_tokens=context.shared_data.dynamic_data.get("override_tokens"),
            title_clean_rules=self.config.settings.global_management.title_clean_rules,
            user_tokens=user_tokens,
            override_title_rules=override_title_rules,
            video_dynamic_range=self.config.settings.global_management.video_dynamic_range,
            **self._release_info_token_kwargs(
                release_info,
                self.config.settings.series.multi_episode_style,
            ),
        )
        output = format_str.get_output()
        return output if output else None

    @staticmethod
    def _release_info_token_kwargs(
        release_info: SeriesReleaseInfo,
        multi_episode_style: MultiEpisodeStyle,
    ) -> dict[str, Any]:
        return {
            "season_number": release_info.season,
            "season_end": release_info.season_end,
            "episode_number": (
                release_info.episode_start if not release_info.is_pack else None
            ),
            "episode_format": release_info.episode_format,
            "multi_episode_style": multi_episode_style,
        }

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
            TrackerSelection.UPLOAD_CX,
            TrackerSelection.ONLY_ENCODES,
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
        for (
            client,
            client_settings,
        ) in self.config.settings.torrent_clients.by_selection().items():
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
                self.config.settings.torrent_clients.qbittorrent,
                self.config.settings.general.timeout,
            )
            self.qbit_client.login()
        return self.qbit_client.inject_torrent(torrent_path)

    def deluge_inject(self, torrent_path: Path) -> tuple[bool, str]:
        if not self.deluge_client:
            self.deluge_client = DelugeClient(
                self.config.settings.torrent_clients.deluge,
                self.config.settings.general.timeout,
            )
            self.deluge_client.login()
        return self.deluge_client.inject_torrent(torrent_path)

    def rtorrent_inject(self, torrent_path: Path, file_path: Path) -> tuple[bool, str]:
        if not self.rtorrent_client:
            self.rtorrent_client = RTorrentClient(
                self.config.settings.torrent_clients.rtorrent,
                self.config.settings.general.timeout,
            )
        return self.rtorrent_client.inject_torrent(torrent_path, file_path, True)

    def transmission_inject(self, torrent_path: Path) -> tuple[bool, str]:
        if not self.transmission_client:
            self.transmission_client = TransmissionClient(
                self.config.settings.torrent_clients.transmission,
                self.config.settings.general.timeout,
            )
        return self.transmission_client.inject_torrent(torrent_path)

    def watch_folder_inject(
        self, torrent_path: Path, tracker_name: str, client_path: Path
    ) -> tuple[bool, str] | None:
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
            return True, f"File copied to watch folder ({moved_file.name})"
        return None

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
