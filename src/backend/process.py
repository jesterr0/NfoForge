import asyncio
import shutil
import traceback
from collections.abc import Callable
from os import PathLike
from pathlib import Path
from pymediainfo import MediaInfo
from torf import Torrent

from PySide6.QtCore import SignalInstance

from src.config.config import Config
from src.enums.tracker_selection import TrackerSelection
from src.enums.torrent_client import TorrentClientSelection
from src.enums.media_mode import MediaMode
from src.backend.trackers import (
    MTVSearch,
    mtv_uploader,
    TLSearch,
    tl_upload,
    BHDSearch,
    bhd_uploader,
    ptp_uploader,
    PTPSearch,
)
from src.backend.template_selector import TemplateSelectorBackEnd
from src.backend.torrents import generate_torrent, write_torrent, clone_torrent
from src.backend.token_replacer import TokenReplacer, ColonReplace, UnfilledTokenRemoval
from src.backend.torrent_clients.qbittorrent import QBittorrentClient
from src.backend.torrent_clients.deluge import DelugeClient
from src.backend.torrent_clients.rtorrent import RTorrent
from src.backend.torrent_clients.transmission import Transmission
from src.payloads.media_search import MediaSearchPayload
from src.nf_jinja2 import Jinja2TemplateEngine


class ProcessBackEnd:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.template_selector_be = TemplateSelectorBackEnd()
        self.template_selector_be.load_templates()

        # callables for progress
        self.torrent_gen_progress: Callable[[float], None] = None

        # clients
        self.qbit_client: QBittorrentClient = None
        self.deluge_client: DelugeClient = None
        self.rtorrent_client: RTorrent = None
        self.transmission_client: Transmission = None
        self.watch_folder_counter = 0
        self.clients_can_logout = (self.qbit_client, self.deluge_client)

    async def dupe_checks(
        self,
        file_input: Path,
        process_dict: dict[str, Path],
        queued_text_update: Callable[[str], None],
        media_search_payload: MediaSearchPayload,
    ) -> dict[str, Path]:
        queued_text_update("Checking for dupes")

        tasks = []
        for tracker_name in process_dict.keys():
            if TrackerSelection(tracker_name) == TrackerSelection.MORE_THAN_TV:
                tasks.append(
                    self._dupe_mtv(
                        tracker_name=tracker_name,
                        file_input=file_input,
                        media_search_payload=media_search_payload,
                    )
                )
            elif TrackerSelection(tracker_name) == TrackerSelection.TORRENT_LEECH:
                tasks.append(
                    self._dupe_tl(tracker_name=tracker_name, file_input=file_input)
                )
            elif TrackerSelection(tracker_name) == TrackerSelection.BEYOND_HD:
                tasks.append(
                    self._dupe_bhd(tracker_name=tracker_name, file_input=file_input)
                )
            elif TrackerSelection(tracker_name) == TrackerSelection.PASS_THE_POPCORN:
                tasks.append(
                    self._dupe_ptp(tracker_name=tracker_name, file_input=file_input)
                )

        async_results = await asyncio.gather(*tasks)

        dupes = {}
        for item in async_results:
            if item:
                dupes[item[0]] = item[1]

        dupe_count = sum(len(item) for item in dupes.values())
        queued_text_update(
            f"Total potential dupes found: {dupe_count} (REVIEW BEFORE CONTINUING)"
        )

        return dupes

    async def _dupe_mtv(
        self,
        tracker_name: str,
        file_input: Path,
        media_search_payload: MediaSearchPayload,
    ) -> tuple[TrackerSelection, Path] | None:
        mtv_search = MTVSearch(
            self.config.cfg_payload.mtv_tracker.api_key,
            timeout=self.config.cfg_payload.timeout,
        ).search(
            title=file_input.stem,
            imdb_id=media_search_payload.imdb_id,
            tmdb_id=media_search_payload.tmdb_id,
        )
        if mtv_search:
            return TrackerSelection(tracker_name), mtv_search

    async def _dupe_tl(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, Path] | None:
        tl_search = TLSearch(
            username=self.config.cfg_payload.tl_tracker.username,
            password=self.config.cfg_payload.tl_tracker.password,
            alt_2_fa_token=self.config.cfg_payload.tl_tracker.alt_2_fa_token,
            timeout=self.config.cfg_payload.timeout,
        ).search(file_input)
        if tl_search:
            return TrackerSelection(tracker_name), tl_search

    async def _dupe_bhd(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, Path] | None:
        bhd_search = BHDSearch(
            api_key=self.config.cfg_payload.bhd_tracker.api_key,
            rss_key=self.config.cfg_payload.bhd_tracker.rss_key,
            timeout=self.config.cfg_payload.timeout,
        ).search(file_input.stem)
        if bhd_search:
            return TrackerSelection(tracker_name), bhd_search

    async def _dupe_ptp(
        self, tracker_name: str, file_input: Path
    ) -> tuple[TrackerSelection, Path] | None:
        ptp_search = PTPSearch(
            api_user=self.config.cfg_payload.ptp_tracker.api_user,
            api_key=self.config.cfg_payload.ptp_tracker.api_key,
            timeout=self.config.cfg_payload.timeout,
        ).search(
            movie_title=self.config.media_search_payload.title,
            movie_year=self.config.media_search_payload.year,
            file_name=file_input.stem,
            imdb_id=self.config.media_search_payload.imdb_id,
        )
        if ptp_search:
            return TrackerSelection(tracker_name), ptp_search

    def process_trackers(
        self,
        media_input: Path,
        jinja_engine: Jinja2TemplateEngine,
        source_file: Path | None,
        process_dict: dict[str, Path],
        queued_status_update: Callable[[str, str], None],
        queued_text_update: Callable[[str], None],
        queued_text_update_replace_last_line: Callable[[str], None],
        torrent_gen_progress: Callable[[float], None],
        caught_error: SignalInstance,
        mediainfo_obj: MediaInfo,
        source_file_mi_obj: MediaInfo | None,
        media_mode: MediaMode,
        media_search_payload: MediaSearchPayload,
        colon_replacement: ColonReplace,
        releasers_name: str,
        screen_shots: str | None,
    ) -> None:
        self.torrent_gen_progress = torrent_gen_progress
        base_torrent_file: Path | None = None

        # determine maximum piece size for the current tracker(s)
        max_piece_size = self.determine_max_piece_size(process_dict)
        if max_piece_size:
            queued_text_update(f"Detected maximum piece size: {max_piece_size} (bytes)")

        # process
        for idx, (tracker_name, torrent_path) in enumerate(process_dict.items()):
            queued_status_update(tracker_name, "Processing")
            queued_text_update(f"\nStarting work for '{tracker_name}':")

            tracker_info = self.config.tracker_map[TrackerSelection(tracker_name)]

            # torrent file
            if idx == 0:
                queued_text_update("Generating torrent")
                torrent = generate_torrent(
                    tracker_info=tracker_info,
                    input_file=media_input,
                    max_piece_size=max_piece_size,
                    cb=self.torrent_gen_cb,
                )
                write_to_disk = write_torrent(torrent, torrent_path)
                base_torrent_file = write_to_disk
            else:
                queued_text_update("Cloning torrent")
                clone = clone_torrent(
                    tracker_info=tracker_info,
                    torrent_path=torrent_path,
                    base_torrent_file=base_torrent_file,
                )
                _ = write_torrent(torrent_instance=clone, torrent_path=torrent_path)

            # generate nfo
            nfo = ""
            if tracker_info.nfo_template:
                nfo_template = self.template_selector_be.read_template(
                    name=tracker_info.nfo_template
                )
                if nfo_template:
                    nfo = TokenReplacer(
                        media_input=media_input,
                        jinja_engine=jinja_engine,
                        source_file=source_file,
                        token_string=nfo_template,
                        colon_replace=colon_replacement,
                        media_search_obj=media_search_payload,
                        source_file_mi_obj=source_file_mi_obj,
                        media_info_obj=mediainfo_obj,
                        unfilled_token_mode=UnfilledTokenRemoval.KEEP,
                        releasers_name=releasers_name,
                        screen_shots=screen_shots,
                        edition_override=self.config.shared_data.dynamic_data.get(
                            "edition_override"
                        ),
                        movie_clean_title_rules=self.config.cfg_payload.mvr_clean_title_rules,
                    ).get_output()
                    if not isinstance(nfo, str):
                        raise ValueError("NFO should be a string")

                token_replacer_plugin = self.config.cfg_payload.token_replacer
                if token_replacer_plugin:
                    nfo_plugin = self.config.loaded_plugins[
                        token_replacer_plugin
                    ].token_replacer
                    if nfo_plugin and callable(nfo_plugin):
                        replace_tokens = nfo_plugin(config=self.config, input_str=nfo)
                        nfo = replace_tokens if replace_tokens else nfo

            # write nfo to disk beside the torrent if the nfo exists
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
                        tracker=TrackerSelection(tracker_name),
                        torrent_file=torrent_path,
                        media_file=media_input,
                        mi_obj=mediainfo_obj,
                        upload_text_cb=queued_text_update,
                        upload_text_replace_last_line_cb=queued_text_update_replace_last_line,
                    )

            # upload
            if tracker_info.upload_enabled and pre_upload_processing is not False:
                queued_text_update("Uploading release")
                execute_upload = None
                try:
                    execute_upload = self.upload(
                        tracker=tracker_name,
                        torrent_file=torrent_path,
                        file_input=media_input,
                        mediainfo_obj=mediainfo_obj,
                        media_mode=media_mode,
                        media_search_payload=media_search_payload,
                        nfo=nfo,
                    )
                except Exception as upload_error:
                    queued_text_update(
                        f"Failed to upload release, check logs for information ({upload_error})"
                    )
                    caught_error.emit(f"Upload Error: {traceback.format_exc()}")
                    queued_status_update(tracker_name, "Failed")

                if execute_upload:
                    queued_text_update("Successfully uploaded release")
                    # handle injection
                    try:
                        self._handle_injection(
                            queued_text_update=queued_text_update,
                            tracker_name=tracker_name,
                            torrent_path=torrent_path,
                            file_input=media_input,
                        )
                        queued_status_update(tracker_name, "Complete")
                    except Exception as e:
                        queued_status_update(
                            tracker_name, f"Failed to inject torrent ({e})"
                        )
                        caught_error.emit(f"Injection Error: {traceback.format_exc()}")
                else:
                    queued_text_update(
                        "Failed to upload release, check logs for information"
                    )
                    queued_status_update(tracker_name, "Failed")
            elif not tracker_info.upload_enabled and pre_upload_processing is None:
                queued_text_update("Skipping upload & injection, upload is disabled")
            elif tracker_info.upload_enabled and pre_upload_processing is False:
                queued_text_update(
                    "Skipping upload & injection, upload is disabled via plugin"
                )

            nfo_generated_str = "NFO & " if nfo else ""
            queued_text_update(
                f"Generated {nfo_generated_str}torrent output directory:\n{torrent_path.parent}"
            )

        # disconnect from clients and reset related variables after use
        self.disconnect_from_clients()

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
        tracker: str,
        torrent_file: Path,
        file_input: Path,
        mediainfo_obj: MediaInfo,
        media_mode: MediaMode,
        media_search_payload: MediaSearchPayload,
        nfo: str,
    ) -> Path | None:
        tracker = TrackerSelection(tracker)
        if tracker == TrackerSelection.MORE_THAN_TV:
            tracker_payload = self.config.cfg_payload.mtv_tracker
            return mtv_uploader(
                username=tracker_payload.username,
                password=tracker_payload.password,
                totp=tracker_payload.totp,
                nfo=nfo,
                group_desc=tracker_payload.group_description,
                torrent_file=Path(torrent_file),
                file_input=Path(file_input),
                mediainfo_obj=mediainfo_obj,
                genre_ids=media_search_payload.genres,
                media_mode=media_mode,
                anonymous=bool(tracker_payload.anonymous),
                source_origin=tracker_payload.source_origin,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker == TrackerSelection.TORRENT_LEECH:
            return tl_upload(
                announce_key=self.config.cfg_payload.tl_tracker.torrent_passkey,
                nfo=nfo,
                torrent_file=torrent_file,
                mediainfo_obj=mediainfo_obj,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker == TrackerSelection.BEYOND_HD:
            tracker_payload = self.config.cfg_payload.bhd_tracker
            return bhd_uploader(
                api_key=tracker_payload.api_key,
                torrent_file=torrent_file,
                file_input=file_input,
                media_mode=media_mode,
                imdb_id=self.config.media_search_payload.imdb_id,
                tmdb_id=self.config.media_search_payload.tmdb_id,
                nfo=nfo,
                internal=bool(tracker_payload.internal),
                live_release=tracker_payload.live_release,
                anonymous=bool(tracker_payload.anonymous),
                promo=tracker_payload.promo,
                timeout=self.config.cfg_payload.timeout,
            )
        elif tracker == TrackerSelection.PASS_THE_POPCORN:
            tracker_payload = self.config.cfg_payload.ptp_tracker
            return ptp_uploader(
                api_user=tracker_payload.api_user,
                api_key=tracker_payload.api_key,
                username=tracker_payload.username,
                password=tracker_payload.password,
                announce_url=tracker_payload.announce_url,
                torrent_file=torrent_file,
                file_input=file_input,
                url_data=self.config.shared_data.url_data,
                nfo=nfo,
                re_upload_images_to_ptp=tracker_payload.reupload_images_to_ptp_img,
                mediainfo_obj=mediainfo_obj,
                media_search_payload=self.config.media_search_payload,
                ptp_img_api_key=tracker_payload.ptpimg_api_key,
                cookie_dir=self.config.TRACKER_COOKIE_PATH,
                totp=tracker_payload.totp,
                timeout=self.config.cfg_payload.timeout,
            )

    def torrent_gen_cb(
        self,
        _torrent: Torrent,
        _filepath: PathLike[str],
        pieces_done: int,
        pieces_total: int,
    ) -> None:
        if self.torrent_gen_progress:
            self.torrent_gen_progress(round(pieces_done / pieces_total * 100, 2))

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
                    f"Injecting torrent [Tracker: {tracker_name} | Client: {client}]"
                )
                if client == TorrentClientSelection.QBITTORRENT:
                    inj_success, inj_msg = self.qbittorrent_inject(torrent_path)
                elif client == TorrentClientSelection.DELUGE:
                    inj_success, inj_msg = self.deluge_inject(torrent_path)
                elif client == TorrentClientSelection.RTORRENT:
                    inj_success, inj_msg = self.rtorrent_inject(
                        torrent_path, file_input
                    )
                elif client == TorrentClientSelection.TRANSMISSION:
                    inj_success, inj_msg = self.transmission_inject(torrent_path)
                elif (
                    client == TorrentClientSelection.WATCH_FOLDER
                    and client_settings.path
                ):
                    inj_success, inj_msg = self.watch_folder_inject(
                        Path(torrent_path), tracker_name
                    )

                queued_text_update(
                    f"{'Completed' if inj_success else 'Failed'}, status: {inj_msg}"
                )

    def qbittorrent_inject(self, torrent_path: Path) -> tuple[bool, str]:
        if not self.qbit_client:
            self.qbit_client = QBittorrentClient(self.config)
            self.qbit_client.login()
        return self.qbit_client.inject_torrent(torrent_path)

    def deluge_inject(self, torrent_path: Path) -> tuple[bool, str]:
        if not self.deluge_client:
            self.deluge_client = DelugeClient(self.config)
            self.deluge_client.login()
        return self.deluge_client.inject_torrent(torrent_path)

    def rtorrent_inject(self, torrent_path: Path, file_path: Path) -> tuple[bool, str]:
        if not self.rtorrent_client:
            self.rtorrent_client = RTorrent(self.config)
        return self.rtorrent_client.inject_torrent(torrent_path, file_path, True)

    def transmission_inject(self, torrent_path: Path) -> tuple[bool, str]:
        if not self.transmission_client:
            self.transmission_client = Transmission(self.config)
        return self.transmission_client.inject_torrent(torrent_path)

    def watch_folder_inject(
        self, torrent_path: Path, tracker_name: str
    ) -> tuple[Path, str]:
        moved_file = Path(
            shutil.copy(
                torrent_path,
                Path(self.config.cfg_payload.watch_folder.path)
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
