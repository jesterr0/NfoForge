import asyncio
from collections.abc import Callable, Sequence
from html import escape
from pathlib import Path
import shutil
import traceback
from typing import Any

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
from src.backend.image_host_uploading.img_uploader import (
    ImageUploader,
    assert_all_images_uploaded,
)
from src.backend.image_host_uploading.imgbb import ImageBBUploader
from src.backend.image_host_uploading.lensdump import LensdumpUploader
from src.backend.image_host_uploading.onlyimage import OnlyImageUploader
from src.backend.image_host_uploading.pixhost import PixhostUploader
from src.backend.jobs.assets import template_fingerprint
from src.backend.template_selector import TemplateSelectorBackEnd
from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, TokenSelection
from src.backend.torrent_clients.deluge import DelugeClient
from src.backend.torrent_clients.qbittorrent import QBittorrentClient
from src.backend.torrent_clients.qbittorrent.save_path import (
    resolve_qbittorrent_save_path,
)
from src.backend.torrent_clients.rtorrent import RTorrentClient
from src.backend.torrent_clients.transmission import TransmissionClient
from src.backend.torrents import (
    BASE_TORRENT_SUFFIX,
    clone_torrent,
    content_size,
    generate_torrent,
    mkbrr_generate_torrent,
    neutralize_base,
    piece_exponent,
    write_torrent,
)
from src.backend.trackers import (
    AitherSearch,
    BHDSearch,
    BlutopiaSearch,
    DarkPeersSearch,
    FearNoPeerSearch,
    HDBSearch,
    HunoSearch,
    LSTSearch,
    OnlyEncodesSearch,
    PTPSearch,
    ReelFlixSearch,
    SeedPoolSearch,
    ShareIslandSearch,
    TLSearch,
    UploadCXSearch,
    UTPSearch,
    YuSceneSearch,
    aither_uploader,
    bhd_uploader,
    blu_uploader,
    dp_uploader,
    fnp_uploader,
    hdb_uploader,
    huno_uploader,
    lst_uploader,
    oe_uploader,
    ptp_uploader,
    rf_uploader,
    shri_uploader,
    sp_uploader,
    tl_upload,
    ulcx_uploader,
    utp_uploader,
    yus_uploader,
)
from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.hdb import HDBUploader
from src.backend.trackers.health import ensure_tracker_health
from src.backend.trackers.media_support import (
    NO_RELEASE_NAME_FIELD,
    UNIT3D_TRACKERS,
    UNSUPPORTED_SERIES_TRACKERS,
)
from src.backend.trackers.seedpool import SeedPoolUploader
from src.backend.trackers.torrentleech import TLUploader
from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.backend.trackers.utils import format_image_tag
from src.backend.upload_retry import (
    RETRY_ATTEMPTS,
    TrackerRunOutcome,
    UploadFailure,
    UploadFailurePhase,
    UploadRetryAction,
)
from src.backend.utils.anime import is_anime_release
from src.backend.utils.file_utilities import release_stem
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
from src.enums.upload_process import RunPhase
from src.exceptions import (
    ImageHostError,
    PluginExecutionError,
    ProcessCancelled,
    TrackerError,
)
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import ImageUploadData, ImageUploadFromTo
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.series import (
    SeriesReleaseInfo,
    build_series_release_info,
    describe_missing_upload_fields,
)
from src.payloads.tracker_search_result import TrackerSearchResult
from src.payloads.trackers import TrackerInfo
from src.payloads.watch_folder import WatchFolder
from src.plugins.api import (
    DuplicateCheckRequest,
    PostUploadOutcome,
    PostUploadRequest,
    PreUploadDecision,
    PreUploadRequest,
    TokenReplaceRequest,
    UploadReporter,
)
from src.utils.secret_redaction import scrub_secrets


class ProcessBackEnd:
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
            if tracker_sel is TrackerSelection.TORRENT_LEECH:
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
            elif tracker_sel is TrackerSelection.HDB:
                tasks.append(
                    self._dupe_hdb(
                        tracker_sel=tracker_sel,
                        file_input=search_input,
                        media_input_payload=media_input_payload,
                        media_search_payload=media_search_payload,
                    )
                )
            elif tracker_sel is TrackerSelection.BLUTOPIA:
                tasks.append(
                    self._dupe_blutopia(
                        tracker_sel=tracker_sel, file_input=search_input
                    )
                )
            elif tracker_sel is TrackerSelection.SEEDPOOL:
                tasks.append(
                    self._dupe_seedpool(
                        tracker_sel=tracker_sel, file_input=search_input
                    )
                )
            elif tracker_sel is TrackerSelection.UTOPIA:
                tasks.append(
                    self._dupe_utp(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.YU_SCENE:
                tasks.append(
                    self._dupe_yuscene(tracker_sel=tracker_sel, file_input=search_input)
                )
            elif tracker_sel is TrackerSelection.FEAR_NO_PEER:
                tasks.append(
                    self._dupe_fearnopeer(
                        tracker_sel=tracker_sel, file_input=search_input
                    )
                )

        async_results = await asyncio.gather(*tasks, return_exceptions=True)

        dupes: dict[
            TrackerSelection,
            tuple[TrackerSelection, bool, list[TrackerSearchResult] | str],
        ] = {}
        for tracker_sel, item in zip(processing_queue, async_results, strict=False):
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

        plugin_id = self.config.settings.plugins.duplicate_checker
        if self.config.settings.general.enable_plugins and plugin_id:
            mergeable = [
                tracker_sel
                for tracker_sel, (_, success, data) in dupes.items()
                if success and isinstance(data, list)
            ]
            if mergeable:
                extra_results = await asyncio.gather(
                    *(
                        self._run_duplicate_checker_plugin(
                            tracker_sel, media_input_payload, media_search_payload
                        )
                        for tracker_sel in mergeable
                    )
                )
                for tracker_sel, extra in zip(mergeable, extra_results, strict=True):
                    if not extra:
                        continue
                    _, success, data = dupes[tracker_sel]
                    if isinstance(data, list):
                        dupes[tracker_sel] = (tracker_sel, success, data + extra)

        return dupes

    async def _run_duplicate_checker_plugin(
        self,
        tracker_sel: TrackerSelection,
        media_input_payload: MediaInputPayload,
        media_search_payload: MediaSearchPayload,
    ) -> list[TrackerSearchResult]:
        """Run the configured duplicate-checker plugin for one tracker.

        Never raises: a broken or slow plugin must not affect the built-in
        dupe-check results already gathered for any tracker. Failures and
        timeouts are logged and treated as "nothing extra found".
        """
        plugin_id = self.config.settings.plugins.duplicate_checker
        if not plugin_id:
            return []
        record = self.config.plugin_manager.get(plugin_id)
        if not record or record.definition.duplicate_checker is None:
            return []
        timeout = self.config.settings.general.timeout
        try:
            result = await asyncio.to_thread(
                self.config.plugin_manager.run_duplicate_checker,
                plugin_id,
                DuplicateCheckRequest(
                    config=self.config,
                    tracker=tracker_sel,
                    media_input=media_input_payload,
                    media_search=media_search_payload,
                    timeout=timeout,
                ),
            )
        except PluginExecutionError as error:
            LOG.error(
                LOG.LOG_SOURCE.BE,
                f"Duplicate-checker plugin failed for {tracker_sel}: {error}",
            )
            return []
        return list(result)

    async def _unsupported_series_tracker_dupe(
        self, tracker_sel: TrackerSelection
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return tracker_sel, False, f"{tracker_sel} does not support series uploads yet"

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
                # a pack folder's whole name is the release name; `.stem` would
                # read its last dotted segment as an extension and drop it
                file_name=file_input.name,
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

    async def _dupe_blutopia(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            BlutopiaSearch,
            {"api_key": self.config.settings.trackers.blutopia.api_key},
        )

    async def _dupe_seedpool(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            SeedPoolSearch,
            {"api_key": self.config.settings.trackers.seedpool.api_key},
        )

    async def _dupe_utp(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            UTPSearch,
            {"api_key": self.config.settings.trackers.utp.api_key},
        )

    async def _dupe_yuscene(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            YuSceneSearch,
            {"api_key": self.config.settings.trackers.yuscene.api_key},
        )

    async def _dupe_fearnopeer(
        self, tracker_sel: TrackerSelection, file_input: Path
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        return await self._aither_dupe_check(
            tracker_sel,
            file_input,
            FearNoPeerSearch,
            {"api_key": self.config.settings.trackers.fearnopeer.api_key},
        )

    async def _dupe_hdb(
        self,
        tracker_sel: TrackerSelection,
        file_input: Path,
        media_input_payload: MediaInputPayload,
        media_search_payload: MediaSearchPayload,
    ) -> tuple[TrackerSelection, bool, list[TrackerSearchResult] | str]:
        username = self.config.settings.trackers.hdb.username
        passkey = self.config.settings.trackers.hdb.passkey
        if not username or not passkey:
            return (
                tracker_sel,
                False,
                "HDB username or passkey missing",
            )
        try:
            first_file = media_input_payload.require_first_file()
            mediainfo_obj = media_input_payload.require_mediainfo(first_file)
            media_type = media_input_payload.require_media_type()
            hdb_search = HDBSearch(
                username=username,
                passkey=passkey,
                timeout=self.config.settings.general.timeout,
            ).search(
                input_path=file_input,
                media_type=media_type,
                mediainfo_obj=mediainfo_obj,
                imdb_id=media_search_payload.imdb_id,
                tvdb_id=media_search_payload.tvdb_id,
                genre_names=media_search_payload.genre_names,
            )
            if hdb_search:
                return tracker_sel, True, hdb_search
            else:
                return tracker_sel, True, []
        except Exception as e:
            return tracker_sel, False, str(e)

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
        """Return whether retrying the upload request is safe enough to automate.

        Trackers annotate their own failures; an un-annotated error is treated
        as unsafe rather than guessed at from its message text.
        """
        if getattr(error, "server_accepted", False):
            # The POST may already have succeeded. Retrying the whole upload can
            # create a duplicate; only an explicit user decision may continue.
            return False

        retryable = getattr(error, "retryable", None)
        if retryable is not None:
            return bool(retryable)

        status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int):
            # 408/429 mean the request was rejected before it could be
            # processed. A 5xx means the tracker received and answered the
            # request -- it may have recorded the upload before failing, so
            # it must not be retried automatically.
            return status_code == 408 or status_code == 429

        return False

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
        record_outcome: Callable[[TrackerRunOutcome], None] | None = None,
    ) -> tuple[Path | bool | str | None, bool]:
        """Run one tracker upload with bounded automatic and user retries.

        `record_outcome` reports whether this tracker may be uploaded again.
        It is called on every exit path, including the cancel path -- a
        cancelled tracker whose upload provably never landed (an unreachable
        tracker, say) is the main thing worth deferring into a new job, so it
        must not be lumped in with "state unknown".
        """

        def report(outcome: TrackerRunOutcome) -> None:
            if record_outcome:
                record_outcome(outcome)

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
                    # `_upload_tracker_with_retry` already retries this call, so
                    # a nested budget here would multiply the wait before the
                    # user can intervene.
                    attempts=1,
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
                # It reports the attempt that just failed, so the attempt about
                # to start is one higher.
                failed_attempt = getattr(retry_state, "attempt_number", total_attempts)
                next_attempt = failed_attempt + 1
                tracker_health_cache.pop(tracker, None)
                queued_status_update(
                    str(tracker),
                    f"↻ Retrying upload ({next_attempt}/{RETRY_ATTEMPTS})",
                )
                queued_text_update(
                    f"<br /><span>Temporary upload failure for <b>{tracker}</b>; "
                    f"retrying ({next_attempt}/{RETRY_ATTEMPTS})</span>"
                )

            try:
                retrying = Retrying(
                    retry=retry_if_exception(self._is_automatic_upload_retryable),
                    stop=stop_after_attempt(RETRY_ATTEMPTS),
                    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
                    before_sleep=before_sleep,
                    reraise=True,
                )
                result = retrying(upload_once), False
                report(TrackerRunOutcome.UPLOADED)
                return result
            except ProcessCancelled:
                raise
            except Exception as error:
                retryable = self._is_automatic_upload_retryable(error)
                safe_message = scrub_secrets(str(error))
                failure = UploadFailure(
                    tracker=tracker,
                    phase=self._upload_error_phase(error),
                    message=safe_message,
                    attempt=total_attempts,
                    automatic_attempts=RETRY_ATTEMPTS,
                    retryable=retryable,
                    server_accepted=bool(getattr(error, "server_accepted", False)),
                    torrent_path=torrent_path,
                )
                queued_status_update(str(tracker), "⚠️ Failed - awaiting action")
                queued_text_update(
                    f'<br /><span style="font-weight: bold; color: red;">'
                    f"Upload failed for {tracker}: {safe_message}</span>"
                )
                caught_error.emit(
                    f"Upload Error: {scrub_secrets(traceback.format_exc())}"
                )

                # An upload that may have reached the tracker can never be
                # retried automatically later; only a provable pre-send
                # failure is safe to carry into a deferred job.
                failed_outcome = (
                    TrackerRunOutcome.MAY_HAVE_UPLOADED
                    if failure.server_accepted
                    else TrackerRunOutcome.UPLOAD_FAILED
                )

                if upload_retry_cb is None:
                    report(failed_outcome)
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
                    report(failed_outcome)
                    raise ProcessCancelled from error
                if failure.phase is UploadFailurePhase.DOWNLOAD:
                    # The upload POST already succeeded; only fetching the
                    # tracker's copy of the torrent failed, and the user
                    # chose to keep the release as-is. Report this
                    # distinctly from a genuine skip so nobody reads this as
                    # "never uploaded" and re-uploads by hand.
                    queued_status_update(
                        str(tracker), "⚠️ Uploaded - tracker torrent not downloaded"
                    )
                    queued_text_update(
                        f"<br /><span>Upload succeeded for <b>{tracker}</b>; kept "
                        "after the tracker's torrent copy could not be "
                        "downloaded</span>"
                    )
                    report(TrackerRunOutcome.UPLOADED)
                else:
                    queued_status_update(str(tracker), "⏭ Skipped")
                    queued_text_update(
                        "<br /><span>Skipped upload after user decision</span>"
                    )
                    report(
                        TrackerRunOutcome.SKIPPED
                        if failed_outcome is TrackerRunOutcome.UPLOAD_FAILED
                        else failed_outcome
                    )
                return None, True

    def _inject_with_user_retry(
        self,
        *,
        tracker: TrackerSelection,
        tracker_name: str,
        torrent_path: Path,
        file_input: Path,
        queued_text_update: Callable[[str], None],
        queued_status_update: Callable[[str, str], None],
        caught_error: SignalInstance,
        upload_retry_cb: Callable[[UploadFailure], UploadRetryAction] | None,
        qbittorrent_save_path: str | None = None,
    ) -> tuple[bool, str | None]:
        """Inject a torrent, letting the user retry on failure.

        The torrent is already on the tracker at this point, so retrying an
        injection cannot create a duplicate upload.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                self._handle_injection(
                    queued_text_update=queued_text_update,
                    tracker_name=tracker_name,
                    torrent_path=torrent_path,
                    file_input=file_input,
                    qbittorrent_save_path=qbittorrent_save_path,
                )
                return True, None
            except Exception as error:
                caught_error.emit(
                    f"Injection Error: {scrub_secrets(traceback.format_exc())}"
                )
                # rTorrent embeds credentials as userinfo in its host URI, and
                # `RTorrentClient.inject_torrent` has no exception handling of
                # its own, so an `xmlrpc.client.ProtocolError` carrying the
                # full netloc can reach here; scrub once and reuse everywhere
                # below instead of interpolating the raw error.
                safe_message = scrub_secrets(str(error))
                if upload_retry_cb is None:
                    queued_status_update(
                        tracker_name, f"❌ Failed to inject torrent ({safe_message})"
                    )
                    return False, safe_message

                failure = UploadFailure(
                    tracker=tracker,
                    phase=UploadFailurePhase.INJECTION,
                    message=safe_message,
                    attempt=attempt,
                    automatic_attempts=0,
                    retryable=True,
                    server_accepted=False,
                    torrent_path=torrent_path,
                )
                queued_status_update(
                    tracker_name, "⚠️ Injection failed - awaiting action"
                )
                action = upload_retry_cb(failure)
                if action is UploadRetryAction.RETRY:
                    queued_status_update(
                        tracker_name, f"↻ Retrying injection (attempt {attempt + 1})"
                    )
                    continue
                if action is UploadRetryAction.CANCEL:
                    queued_status_update(tracker_name, "⏹ Cancelled")
                    raise ProcessCancelled from error
                queued_status_update(
                    tracker_name, f"❌ Failed to inject torrent ({safe_message})"
                )
                return False, safe_message

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
        run_outcome_cb: Callable[[TrackerSelection, TrackerRunOutcome], None]
        | None = None,
        phase: RunPhase = RunPhase.FULL,
    ) -> None:
        # make sure we have all the latest templates in case changes was made during the wizard
        self.template_selector_be.load_templates()

        def record_outcome(
            tracker: TrackerSelection, outcome: TrackerRunOutcome
        ) -> None:
            """Report a tracker's fate structurally, not just as status text.

            The per-tracker status this method already emits is display-only
            and never read back, so it cannot answer "may this be uploaded
            again?" -- which is what deciding whether a tracker can be carried
            into a deferred job depends on.
            """
            if run_outcome_cb:
                run_outcome_cb(tracker, outcome)

        qbittorrent_save_path = None
        if self.config.settings.torrent_clients.qbittorrent.enabled:
            qbittorrent_save_path = resolve_qbittorrent_save_path(
                self.config.settings,
                context,
            )

        # handle image uploading
        images = self.handle_images_for_trackers(
            context, process_dict, queued_text_update, progress_bar_cb
        )

        self.progress_bar_cb = progress_bar_cb
        # A resumed job can carry a torrent it already hashed; the caller has
        # verified the media is unchanged before offering it, so cloning from
        # it is safe and skips the run's most expensive step entirely.
        base_torrent_file: Path | None = None
        carried_torrent = context.shared_data.base_torrent
        if carried_torrent and carried_torrent.is_file():
            base_torrent_file = carried_torrent
            queued_text_update(
                "<br /><span>Reusing the torrent saved with this job "
                "(no re-hash needed)</span>"
            )
        tracker_health_cache: dict[TrackerSelection, bool] = {}

        # get media input - use context instead of config
        media_input = context.media_input.require_input_path()
        release_info = build_series_release_info(context.media_input)

        # process
        queued_text_update(
            '<br /><h3 style="margin-bottom: 0; padding-bottom: 0;">🌐 Trackers:'
        )

        # A prepared job already carries finished titles and NFOs, so none of
        # the generation below runs and neither prompt fires -- that silence is
        # what lets such a job be uploaded unattended, by a queue or otherwise.
        already_prepared = context.shared_data.is_prepared()
        if already_prepared:
            queued_text_update(
                "<br /><span>Using the titles and NFOs saved with this job</span>"
            )

        # base user tokens, this will be filled with prompt tokens as well if needed
        base_usr_tokens: dict[str, str] = dict(context.shared_data.prompt_token_answers)

        # find all prompt tokens
        if token_prompt_cb and not already_prepared:
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
        tracker_release_data: dict[TrackerSelection, dict[str, str | None]] = dict(
            context.shared_data.tracker_release_data
        )
        if not already_prepared:
            queued_text_update("<br /><span>Generating tracker titles and NFOs</span>")
        trackers_to_generate = () if already_prepared else tuple(process_dict.keys())
        for tracker_name in trackers_to_generate:
            cur_tracker = TrackerSelection(tracker_name)
            tracker_info = self.config.settings.trackers.by_selection()[cur_tracker]

            # generate tracker title first
            tracker_title = None
            if cur_tracker not in NO_RELEASE_NAME_FIELD:
                generated_tracker_title = self.generate_tracker_title(
                    tracker=cur_tracker,
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
                    record = self.config.plugin_manager.get(token_replacer_plugin)
                    if record and record.definition.token_replacer is not None:
                        LOG.info(
                            LOG.LOG_SOURCE.BE,
                            f"Running token replacer plugin for tracker: {tracker_name}",
                        )
                        nfo = self.config.plugin_manager.replace_tokens(
                            token_replacer_plugin,
                            TokenReplaceRequest(
                                config=self.config,
                                context=context,
                                text=nfo,
                                trackers=(cur_tracker,),
                                tracker_images=(
                                    tracker_images if cur_tracker in images else None
                                ),
                                formatted_screens=formatted_screens,
                                preview=False,
                            ),
                        )

            tracker_release_data[cur_tracker] = {"title": tracker_title, "nfo": nfo}

        # update nfos with user updates from front end if enabled
        if (
            self.config.settings.general.enable_prompt_overview
            and overview_cb
            and not already_prepared
        ):
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

        # Record the finished titles/NFOs (including any overview edits) and the
        # prompt answers onto the context, so saving after this point produces a
        # prepared job rather than one that would regenerate and re-ask.
        context.shared_data.tracker_release_data.clear()
        context.shared_data.tracker_release_data.update(tracker_release_data)
        context.shared_data.prompt_token_answers.clear()
        context.shared_data.prompt_token_answers.update(base_usr_tokens)
        if not already_prepared:
            self._record_template_fingerprints(process_dict, context)

        # Hash once, here, before any tracker is touched. This runs after the
        # overview prompt so the user is never left waiting on a dialog partway
        # through hashing, and only when there is at least one tracker to stamp
        # for -- with none, there is nothing to hash for.
        if process_dict:
            base_torrent_file = self._prepare_base_torrent(
                working_dir=context.media_input.require_working_dir(),
                media_input=media_input,
                carried_torrent=base_torrent_file,
                queued_text_update=queued_text_update,
            )

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

            # Torrent file: every tracker gets a stamped clone of the neutral
            # base, the first one included. No tracker's artifact is ever
            # another tracker's clone source, so a UNIT3D upload replacing this
            # file with the server's rewritten copy (see
            # Unit3dBaseUploader._download_uploaded_torrent) cannot leak that
            # tracker's announce, source, comment or "created by" into anyone
            # else's torrent.
            queued_text_update("<br /><span>Cloning torrent</span>")
            if not base_torrent_file:
                raise FileNotFoundError(
                    "Failed to determine base torrent file to clone"
                )
            clone = clone_torrent(
                tracker_info=tracker_info,
                torrent_path=torrent_path,
                base_torrent_file=base_torrent_file,
                tracker_name=tracker_name,
            )
            _ = write_torrent(torrent_instance=clone, torrent_path=torrent_path)

            nfo = cur_tracker_release_data.get("nfo") or ""
            if nfo:
                with open(
                    torrent_path.with_suffix(".nfo"), "w", encoding="utf-8"
                ) as log_out:
                    log_out.write(nfo)

            if phase is RunPhase.PREPARE:
                # everything this tracker needs now exists; publishing is what a
                # later run (or the queue) does with it
                queued_status_update(tracker_name, "📦 Prepared")
                queued_text_update(
                    "<br /><span>Prepared torrent and NFO; not uploading</span>"
                )
                continue

            # pre upload plugin
            pre_upload_decision, pre_upload_error = self._run_pre_upload_plugin(
                cur_tracker=cur_tracker,
                context=context,
                torrent_path=torrent_path,
                queued_text_update=queued_text_update,
                queued_text_update_replace_last_line=(
                    queued_text_update_replace_last_line
                ),
            )
            if pre_upload_error:
                # One tracker's plugin failure must not cancel the rest of the
                # queue, so this continues rather than propagating.
                LOG.error(
                    LOG.LOG_SOURCE.BE,
                    f"Pre-upload plugin failed for {cur_tracker}: {pre_upload_error}",
                )
                queued_status_update(tracker_name, "❌ Failed")
                # failed before any upload request was built, so this tracker
                # is safe to carry into a deferred job
                record_outcome(cur_tracker, TrackerRunOutcome.UPLOAD_FAILED)
                continue

            # upload
            if (
                tracker_info.upload_enabled
                and pre_upload_decision is not PreUploadDecision.SKIP
            ):
                execute_upload = None
                skipped_upload = False
                try:
                    queued_text_update(
                        "<br /><span>Checking tracker availability and uploading "
                        "release</span>"
                    )
                    execute_upload, skipped_upload = self._upload_tracker_with_retry(
                        tracker=cur_tracker,
                        torrent_path=torrent_path,
                        tracker_health_cache=tracker_health_cache,
                        upload_request=lambda cur_tracker=cur_tracker, torrent_path=torrent_path, nfo=nfo, cur_tracker_title=cur_tracker_title, context=context, release_info=release_info: (
                            self.upload(
                                tracker=cur_tracker,
                                torrent_file=torrent_path,
                                nfo=nfo,
                                tracker_title=cur_tracker_title,
                                context=context,
                                release_info=release_info,
                            )
                        ),
                        queued_status_update=queued_status_update,
                        queued_text_update=queued_text_update,
                        caught_error=caught_error,
                        upload_retry_cb=upload_retry_cb,
                        record_outcome=lambda outcome, tracker=cur_tracker: (
                            record_outcome(tracker, outcome)
                        ),
                    )

                    if execute_upload:
                        queued_text_update(
                            "<br /><span>Successfully uploaded release</span>"
                        )
                        # handle injection
                        injection_succeeded, injection_error = (
                            self._inject_with_user_retry(
                                tracker=cur_tracker,
                                tracker_name=tracker_name,
                                torrent_path=torrent_path,
                                file_input=media_input,
                                queued_text_update=queued_text_update,
                                queued_status_update=queued_status_update,
                                caught_error=caught_error,
                                upload_retry_cb=upload_retry_cb,
                                qbittorrent_save_path=qbittorrent_save_path,
                            )
                        )
                        if injection_succeeded:
                            queued_status_update(tracker_name, "✅ Complete")
                            self._run_post_upload_plugin(
                                cur_tracker=cur_tracker,
                                context=context,
                                torrent_path=torrent_path,
                                outcome=PostUploadOutcome.SUCCESS,
                                queued_text_update=queued_text_update,
                                queued_text_update_replace_last_line=(
                                    queued_text_update_replace_last_line
                                ),
                            )
                        else:
                            # the release is already on the tracker, so this
                            # must never be offered for a deferred re-upload
                            record_outcome(
                                cur_tracker, TrackerRunOutcome.INJECTION_FAILED
                            )
                            self._run_post_upload_plugin(
                                cur_tracker=cur_tracker,
                                context=context,
                                torrent_path=torrent_path,
                                outcome=PostUploadOutcome.INJECTION_FAILED,
                                queued_text_update=queued_text_update,
                                queued_text_update_replace_last_line=(
                                    queued_text_update_replace_last_line
                                ),
                                error=injection_error,
                            )
                    else:
                        # `_upload_tracker_with_retry` already reported the
                        # skip (with phase-appropriate status/text) when it
                        # returned; nothing further to say here. A mid-retry
                        # user skip is deliberately not a post-upload
                        # `SKIPPED` outcome -- that value is reserved for a
                        # pre_upload plugin's decision, below.
                        if not skipped_upload:
                            queued_text_update(
                                '<br /><span style="font-weight: bold; color: red;">Failed to upload release, '
                                "check logs for information</span>"
                            )
                            queued_status_update(tracker_name, "❌ Failed")
                            self._run_post_upload_plugin(
                                cur_tracker=cur_tracker,
                                context=context,
                                torrent_path=torrent_path,
                                outcome=PostUploadOutcome.UPLOAD_FAILED,
                                queued_text_update=queued_text_update,
                                queued_text_update_replace_last_line=(
                                    queued_text_update_replace_last_line
                                ),
                                error="Failed to upload release; check logs for information",
                            )
                except ProcessCancelled:
                    for remaining_tracker in list(process_dict)[idx:]:
                        queued_status_update(remaining_tracker, "⏹ Cancelled")
                    # the tracker at `idx` already reported its own outcome
                    # before raising; everything after it was never touched
                    for remaining_tracker in list(process_dict)[idx + 1 :]:
                        record_outcome(
                            TrackerSelection(remaining_tracker),
                            TrackerRunOutcome.NOT_ATTEMPTED,
                        )
                    self.disconnect_from_clients()
                    raise
                except Exception as upload_error:
                    queued_text_update(
                        '<br /><br /><p style="font-weight: bold; color: red;">Failed to upload '
                        f"release, check logs for information ({upload_error})</p>",
                    )
                    caught_error.emit(
                        f"Upload Error: {scrub_secrets(traceback.format_exc())}"
                    )
                    queued_status_update(tracker_name, "❌ Failed")
                    # an unexpected error anywhere in this block leaves the
                    # upload's fate genuinely unknown, so refuse to offer it
                    # for a deferred re-upload
                    record_outcome(cur_tracker, TrackerRunOutcome.MAY_HAVE_UPLOADED)
                    self._run_post_upload_plugin(
                        cur_tracker=cur_tracker,
                        context=context,
                        torrent_path=torrent_path,
                        outcome=PostUploadOutcome.UPLOAD_FAILED,
                        queued_text_update=queued_text_update,
                        queued_text_update_replace_last_line=(
                            queued_text_update_replace_last_line
                        ),
                        error=scrub_secrets(str(upload_error)),
                    )
            elif not tracker_info.upload_enabled and pre_upload_decision is None:
                queued_text_update(
                    "<br /><span>Skipping upload & injection, upload is disabled</span>"
                )
                queued_status_update(tracker_name, "✅ Complete")
                record_outcome(cur_tracker, TrackerRunOutcome.UPLOAD_DISABLED)
            elif (
                tracker_info.upload_enabled
                and pre_upload_decision is PreUploadDecision.SKIP
            ):
                queued_text_update(
                    "<br /><span>Skipping upload & injection, upload is disabled via plugin</span>"
                )
                queued_status_update(tracker_name, "✅ Complete")
                record_outcome(cur_tracker, TrackerRunOutcome.UPLOAD_DISABLED)
                self._run_post_upload_plugin(
                    cur_tracker=cur_tracker,
                    context=context,
                    torrent_path=torrent_path,
                    outcome=PostUploadOutcome.SKIPPED,
                    queued_text_update=queued_text_update,
                    queued_text_update_replace_last_line=(
                        queued_text_update_replace_last_line
                    ),
                )

            nfo_generated_str = "NFO & " if nfo else ""
            queued_text_update(
                f"<br /><span>Generated {nfo_generated_str}torrent output directory:\n{torrent_path.parent}</span><br />",
            )

        # disconnect from clients and reset related variables after use
        self.disconnect_from_clients()

    def _run_pre_upload_plugin(
        self,
        cur_tracker: TrackerSelection,
        context: ProcessingContext,
        torrent_path: Path,
        queued_text_update: Callable[[str], None],
        queued_text_update_replace_last_line: Callable[[str], None],
    ) -> tuple[PreUploadDecision | None, str | None]:
        """Run the configured pre-upload plugin for one tracker.

        Returns ``(decision, None)`` on success or when no plugin applies, and
        ``(None, message)`` when the plugin failed. Returning the failure
        rather than raising is what keeps one tracker's plugin from cancelling
        the rest of the queue, and it is what makes that property testable.
        """
        if not self.config.settings.general.enable_plugins:
            return None, None

        pre_upload_plugin = self.config.settings.plugins.pre_upload
        if not pre_upload_plugin:
            return None, None

        record = self.config.plugin_manager.get(pre_upload_plugin)
        if not record or record.definition.pre_upload is None:
            return None, None

        try:
            decision = self.config.plugin_manager.run_pre_upload(
                pre_upload_plugin,
                PreUploadRequest(
                    config=self.config,
                    context=context,
                    tracker=cur_tracker,
                    torrent_file=torrent_path,
                    reporter=UploadReporter(
                        append_text=queued_text_update,
                        replace_last_line=queued_text_update_replace_last_line,
                        set_progress=self.progress_bar_cb or (lambda _value: None),
                    ),
                ),
            )
        except PluginExecutionError as error:
            return None, str(error)
        return decision, None

    def _run_post_upload_plugin(
        self,
        cur_tracker: TrackerSelection,
        context: ProcessingContext,
        torrent_path: Path,
        outcome: PostUploadOutcome,
        queued_text_update: Callable[[str], None],
        queued_text_update_replace_last_line: Callable[[str], None],
        error: str | None = None,
    ) -> None:
        """Run the configured post-upload plugin for one tracker, if any.

        Never raises and never changes tracker status: the tracker's work is
        already finished by the time this runs, so a broken notifier plugin
        must not retroactively flip an already-reported outcome. Failures
        are logged only.
        """
        if not self.config.settings.general.enable_plugins:
            return

        post_upload_plugin = self.config.settings.plugins.post_upload
        if not post_upload_plugin:
            return

        record = self.config.plugin_manager.get(post_upload_plugin)
        if not record or record.definition.post_upload is None:
            return

        try:
            self.config.plugin_manager.run_post_upload(
                post_upload_plugin,
                PostUploadRequest(
                    config=self.config,
                    context=context,
                    tracker=cur_tracker,
                    torrent_file=torrent_path,
                    reporter=UploadReporter(
                        append_text=queued_text_update,
                        replace_last_line=queued_text_update_replace_last_line,
                        set_progress=self.progress_bar_cb or (lambda _value: None),
                    ),
                    outcome=outcome,
                    error=error,
                ),
            )
        except PluginExecutionError as plugin_error:
            LOG.error(
                LOG.LOG_SOURCE.BE,
                f"Post-upload plugin failed for {cur_tracker}: {plugin_error}",
            )

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
                cur_tracker = TrackerSelection(tracker_name)

                # a resumed job may already hold this tracker's uploaded URLs;
                # reuse them rather than putting the same images on the host a
                # second time, but only while the destination still matches
                reusable = self._reusable_uploaded_images(context, cur_tracker, img_to)
                if reusable is not None:
                    url_data[cur_tracker] = reusable
                    tracker_to_host_map[cur_tracker] = img_to
                    queued_text_update(
                        f"<br /><span>Reusing {len(reusable)} already-uploaded "
                        f"image(s) for <b>{tracker_name}</b></span>"
                    )
                    continue

                # track the image host to be used for each tracker
                if isinstance(img_to, ImageHost) and img_to is not ImageHost.DISABLED:
                    to_image_hosts.add(img_to)
                elif not to_url and img_to is ImageSource.URLS:
                    to_url = True

                tracker_to_host_map[cur_tracker] = img_to
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
                        tracker_results = upload_results[img_host]
                        assert_all_images_uploaded(str(tracker), tracker_results)
                        url_data[tracker] = tracker_results
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
                    tracker_url_data = {
                        i: img_data
                        for i, img_data in enumerate(context.shared_data.url_data)
                    }
                    assert_all_images_uploaded(str(tracker), tracker_url_data)
                    url_data[tracker] = tracker_url_data
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

        # Record what ended up where, so a job saved after this point can reuse
        # these URLs instead of putting the same screenshots on the host again.
        for tracker, images in url_data.items():
            host = tracker_to_host_map.get(tracker)
            if host is None or not images:
                continue
            context.shared_data.uploaded_images[tracker] = dict(images)
            context.shared_data.uploaded_image_hosts[tracker] = host

        return url_data

    def _record_template_fingerprints(
        self, process_dict: dict[str, Any], context: ProcessingContext
    ) -> None:
        """Note each NFO template's contents at the moment it was rendered.

        A prepared job's frozen NFO deliberately beats a template edited
        afterwards; this is only so the load path can say *which* template moved
        rather than letting the difference go unnoticed.
        """
        context.shared_data.template_fingerprints.clear()
        for tracker_name in process_dict:
            tracker_info = self.config.settings.trackers.by_selection()[
                TrackerSelection(tracker_name)
            ]
            name = tracker_info.nfo_template
            if not name:
                continue
            template = self.template_selector_be.read_template(name=name)
            if template:
                context.shared_data.template_fingerprints[name] = template_fingerprint(
                    template
                )

    @staticmethod
    def needs_local_images(
        context: ProcessingContext,
        tracker: TrackerSelection,
        destination: ImageHost | ImageSource,
    ) -> bool:
        """Whether this tracker still needs screenshot files on disk.

        Defined in terms of `_reusable_uploaded_images` rather than
        re-deriving the rule, so "will this upload?" and "does this need the
        files?" cannot drift apart. Two cases need no files: a destination that
        uploads nothing (a URL passthrough, or `DISABLED`), and one whose
        images already went to that same host.
        """
        if not isinstance(destination, ImageHost) or destination is ImageHost.DISABLED:
            return False
        return (
            ProcessBackEnd._reusable_uploaded_images(context, tracker, destination)
            is None
        )

    @staticmethod
    def _reusable_uploaded_images(
        context: ProcessingContext,
        tracker: TrackerSelection,
        destination: ImageHost | ImageSource,
    ) -> dict[int, ImageUploadData] | None:
        """Previously uploaded images for `tracker`, when still valid.

        Only a real image host is worth reusing: a URL passthrough uploads
        nothing, and `DISABLED` has nothing to reuse. Reuse also requires the
        destination to be unchanged -- otherwise the stored URLs point at a
        host the user has since moved this tracker away from.
        """
        if not isinstance(destination, ImageHost) or destination is ImageHost.DISABLED:
            return None
        if context.shared_data.uploaded_image_hosts.get(tracker) is not destination:
            return None
        images = context.shared_data.uploaded_images.get(tracker)
        return dict(images) if images else None

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
        except Exception:
            # clean up extra images if failed
            shutil.rmtree(img_opt_output_dir, ignore_errors=True)
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
        elif img_host is ImageHost.ONLY_IMAGE:
            return self._create_onlyimage_uploader()
        elif img_host is ImageHost.PIXHOST:
            return PixhostUploader()
        elif img_host is ImageHost.LENSDUMP:
            return self._create_lensdump_uploader()
        elif img_host is ImageHost.PLUGIN:
            return self._get_plugin_image_host_uploader()
        else:
            raise ImageHostError(f"Unsupported image host: {img_host}")

    def _get_plugin_image_host_uploader(self) -> BaseImageHostUploader:
        """Retrieve the plugin configured as the image host uploader.

        Raises:
            ImageHostError: If plugins are disabled, none is configured, or the
                configured plugin is not currently loaded.
        """
        if not self.config.settings.general.enable_plugins:
            raise ImageHostError("External plugins are disabled")

        plugin_id = self.config.settings.plugins.image_host_uploader
        if not plugin_id:
            raise ImageHostError("No plugin configured for image host uploads")

        record = self.config.plugin_manager.get(plugin_id)
        if not record or record.definition.image_host_uploader is None:
            raise ImageHostError(
                f"Configured image host plugin '{plugin_id}' is not available"
            )
        return record.definition.image_host_uploader

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

    def _create_onlyimage_uploader(self) -> OnlyImageUploader:
        """
        Creates an uploader instance for OnlyImage.

        Returns:
            OnlyImageUploader: The uploader instance.

        Raises:
            ImageHostError: If required credentials are missing.
        """
        only_image_payload = self.config.settings.image_hosts.only_image
        if not only_image_payload.api_key:
            raise ImageHostError("Missing 'API Key' for OnlyImage.")
        return OnlyImageUploader(api_key=only_image_payload.api_key)

    def _create_lensdump_uploader(self) -> LensdumpUploader:
        """
        Creates an uploader instance for Lensdump.

        Returns:
            LensdumpUploader: The uploader instance.

        Raises:
            ImageHostError: If required credentials are missing.
        """
        lensdump_payload = self.config.settings.image_hosts.lensdump
        if not lensdump_payload.api_key:
            raise ImageHostError("Missing 'API Key' for Lensdump.")
        return LensdumpUploader(api_key=lensdump_payload.api_key)

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

    def _prepare_base_torrent(
        self,
        working_dir: Path,
        media_input: Path,
        carried_torrent: Path | None,
        queued_text_update: Callable[[str], None],
    ) -> Path:
        """Put a neutral base torrent in place for every tracker to clone.

        The base lives at the run folder's root rather than in a tracker's
        directory, both because it belongs to no tracker and because tracker
        artifacts sit one level down (see `tracker_run_data.tracker_output_dir`)
        -- keeping it out of the `*/<stem>.torrent` glob that a saved job uses
        to find its clone source.

        A carried base is copied in and neutralized rather than used where it
        lies, so this path is the single answer to "where is the base": a
        resumed job that gets re-saved keeps one, and the job's own stored file
        is never mutated.
        """
        base_path = working_dir / f"{release_stem(media_input)}{BASE_TORRENT_SUFFIX}"

        if carried_torrent:
            try:
                return neutralize_base(carried_torrent, base_path)
            except Exception as neutralize_error:
                # Better to spend the hash than to stamp from a base we could
                # not confirm is free of another tracker's identity.
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Could not reuse the torrent saved with this job "
                    f"({neutralize_error}); re-hashing instead",
                )
                queued_text_update(
                    '<br /><span style="color: red;">Could not reuse the saved '
                    f"torrent: {neutralize_error} (re-hashing)</span>"
                )

        exponent = piece_exponent(content_size(media_input))
        queued_text_update(
            f"<br /><span>Piece size: {1 << exponent} bytes (2^{exponent})</span>"
        )

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
                mkbrr_generate_torrent(
                    mkbrr_path=self.config.settings.dependencies.mkbrr,
                    path=media_input,
                    output_path=base_path,
                    piece_exponent=exponent,
                    cb=self.mkbrr_torrent_gen_cb,
                )
                return base_path
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
            # Same explicit exponent as mkbrr would have used, so the fallback
            # produces an identically shaped torrent rather than a differently
            # shaped one.
            torrent = generate_torrent(
                path=media_input,
                piece_exponent=exponent,
                cb=self.torrent_gen_cb,
            )
            return write_torrent(torrent, base_path)

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
        # backstop for paths that skip the Series Match wizard page (the sandbox
        # wizard, restored jobs): UNIT3D rejects a TV upload outright when
        # season_number/episode_number are absent, so fail here with the same
        # explanation rather than letting the payload go out incomplete.
        if media_type is MediaType.SERIES and tracker in UNIT3D_TRACKERS:
            missing_message = describe_missing_upload_fields(release_info)
            if missing_message:
                raise TrackerError(f"{tracker}: {missing_message}")
        input_path = first_file
        if media_type is not MediaType.SERIES:
            input_path = context.media_input.require_input_path()

        if tracker is TrackerSelection.TORRENT_LEECH:
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
                    "PassThePopcorn requires API user, API key, username, password, and announce URL"
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
                nfo=nfo,
                internal=bool(huno_payload.internal),
                anonymous=bool(huno_payload.anonymous),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                episode_number_end=release_info.episode_end,
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
                personal_release=bool(dp_payload.personal_release),
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
        elif tracker is TrackerSelection.HDB:
            hdb_payload = self.config.settings.trackers.hdb
            if not hdb_payload.username or not hdb_payload.passkey:
                raise TrackerError("Missing username or passkey for HDBits")
            if not hdb_payload.session_cookie:
                raise TrackerError(
                    "Missing HDBits session cookie. Paste your logged-in "
                    "session cookie in HDBits tracker settings."
                )
            return hdb_uploader(
                username=hdb_payload.username,
                passkey=hdb_payload.passkey,
                session_cookie=hdb_payload.session_cookie,
                torrent_file=torrent_file,
                input_path=input_path,
                media_type=media_type,
                mediainfo_obj=mediainfo_obj,
                tracker_title=tracker_title,
                nfo=nfo,
                imdb_id=media_search_obj.imdb_id,
                tvdb_id=media_search_obj.tvdb_id,
                genre_names=media_search_obj.genre_names,
                internal=bool(hdb_payload.internal),
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
                timeout=self.config.settings.general.timeout,
            )
        elif tracker is TrackerSelection.BLUTOPIA:
            blutopia_payload = self.config.settings.trackers.blutopia
            if not blutopia_payload.api_key:
                raise TrackerError("Missing API key for Blutopia")
            return blu_uploader(
                media_type=media_type,
                api_key=blutopia_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(blutopia_payload.internal),
                anonymous=bool(blutopia_payload.anonymous),
                personal_release=bool(blutopia_payload.personal_release),
                opt_in_to_mod_queue=bool(blutopia_payload.opt_in_to_mod_queue),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.SEEDPOOL:
            seedpool_payload = self.config.settings.trackers.seedpool
            if not seedpool_payload.api_key:
                raise TrackerError("Missing API key for SeedPool")
            return sp_uploader(
                media_type=media_type,
                api_key=seedpool_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(seedpool_payload.internal),
                anonymous=bool(seedpool_payload.anonymous),
                personal_release=bool(seedpool_payload.personal_release),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.UTOPIA:
            utp_payload = self.config.settings.trackers.utp
            if not utp_payload.api_key:
                raise TrackerError("Missing API key for UTP")
            return utp_uploader(
                media_type=media_type,
                api_key=utp_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(utp_payload.internal),
                anonymous=bool(utp_payload.anonymous),
                personal_release=bool(utp_payload.personal_release),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.YU_SCENE:
            yuscene_payload = self.config.settings.trackers.yuscene
            if not yuscene_payload.api_key:
                raise TrackerError("Missing API key for Yu-scene")
            return yus_uploader(
                media_type=media_type,
                api_key=yuscene_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(yuscene_payload.internal),
                anonymous=bool(yuscene_payload.anonymous),
                personal_release=bool(yuscene_payload.personal_release),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )
        elif tracker is TrackerSelection.FEAR_NO_PEER:
            fearnopeer_payload = self.config.settings.trackers.fearnopeer
            if not fearnopeer_payload.api_key:
                raise TrackerError("Missing API key for FearNoPeer")
            return fnp_uploader(
                media_type=media_type,
                api_key=fearnopeer_payload.api_key,
                torrent_file=torrent_file,
                input_path=input_path,
                tracker_title=tracker_title,
                nfo=nfo,
                internal=bool(fearnopeer_payload.internal),
                anonymous=bool(fearnopeer_payload.anonymous),
                personal_release=bool(fearnopeer_payload.personal_release),
                mediainfo_obj=mediainfo_obj,
                media_search_payload=media_search_obj,
                timeout=self.config.settings.general.timeout,
                season_number=release_info.season,
                episode_number=release_info.episode_start,
                season_pack=release_info.is_pack,
            )

    def generate_tracker_title(
        self,
        tracker: TrackerSelection,
        tracker_info: TrackerInfo,
        context: ProcessingContext,
        release_info: SeriesReleaseInfo,
    ) -> str | None:
        # The user's own override governs, for every tracker. Some were once
        # locked to the packaged default here instead; that was dropped,
        # because a locked template cannot differ between profiles (an encode
        # profile and a disc profile want different titles) and what a tracker
        # actually demands is applied in code at upload regardless -- see
        # `tracker_title_formatting`.
        override_source: TrackerInfo | None = tracker_info

        if release_info.is_series:
            default_title = get_tvr_title_token(
                self.config.settings.series,
                release_info.episode_format,
            )
            series_override = (
                override_source.tvr_title_overrides.get(release_info.episode_format)
                if override_source is not None
                else None
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
                override_source.mvr_title_token_override
                if (
                    override_source is not None
                    and override_source.mvr_title_token_override
                    and override_source.mvr_title_override_enabled
                )
                else self.config.settings.movie.title_token
            )
            colon_replace = (
                override_source.mvr_title_colon_replace
                if (
                    override_source is not None
                    and override_source.mvr_title_colon_replace
                    and override_source.mvr_title_override_enabled
                )
                else self.config.settings.movie.title_colon_replace
            )
            override_title_rules = (
                override_source.mvr_title_replace_map
                if (
                    override_source is not None
                    and override_source.mvr_title_replace_map
                    and override_source.mvr_title_override_enabled
                )
                else None
            )
        user_tokens = {
            k: v
            for k, (v, t) in self.config.settings.user_tokens.tokens.items()
            if TokenSelection(t) is TokenSelection.FILE_TOKEN
        }
        # The same setting the rename pages pass. Without it {remux}, {hybrid}
        # and {re_release} cannot resolve at all here, so a tracker title
        # silently dropped REPACK/REMUX even when the release name carried it
        # and the rename page displayed it -- and every REQUIRED tracker's
        # packaged token already asks for {re_release}.
        parse_filename_attributes = (
            self.config.settings.series.parse_filename_attributes
            if release_info.is_series
            else self.config.settings.movie.parse_filename_attributes
        )
        format_str = TokenReplacer(
            media_input_obj=context.media_input,
            token_string=token_string,
            colon_replace=colon_replace,
            media_search_obj=context.media_search,
            flatten=True,
            file_name_mode=False,
            token_type=FileToken,
            parse_filename_attributes=parse_filename_attributes,
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
            flat_filters=context.flat_filters,
            custom_edition_info=context.custom_edition_info,
            custom_cut_names=context.custom_cut_names,
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
        if tracker is TrackerSelection.TORRENT_LEECH:
            return TLUploader.generate_release_title(title)
        elif tracker is TrackerSelection.BEYOND_HD:
            return BHDUploader.generate_release_title(title)
        elif tracker is TrackerSelection.HDB:
            return HDBUploader.generate_release_title(title)
        # SeedPool is UNIT3D but names uploads after the release, so it wants
        # the dotted form the rest of the family strips
        elif tracker is TrackerSelection.SEEDPOOL:
            return SeedPoolUploader.generate_release_title(title)
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
            TrackerSelection.BLUTOPIA,
            TrackerSelection.UTOPIA,
            TrackerSelection.YU_SCENE,
            TrackerSelection.FEAR_NO_PEER,
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
        qbittorrent_save_path: str | None = None,
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
                    if qbittorrent_save_path:
                        queued_text_update(
                            "<br />qBittorrent save location: "
                            f"{escape(qbittorrent_save_path)}"
                        )
                    inj_success, inj_msg = self.qbittorrent_inject(
                        torrent_path,
                        qbittorrent_save_path,
                    )
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

    def qbittorrent_inject(
        self,
        torrent_path: Path,
        save_path: str | None = None,
    ) -> tuple[bool, str]:
        if not self.qbit_client:
            self.qbit_client = QBittorrentClient(
                self.config.settings.torrent_clients.qbittorrent,
                self.config.settings.general.timeout,
            )
            login_success, login_message = self.qbit_client.login()
            if not login_success:
                return False, login_message
        return self.qbit_client.inject_torrent(torrent_path, save_path)

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
