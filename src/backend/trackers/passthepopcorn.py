import asyncio
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
from typing import Any

from guessit import guessit
import niquests
from niquests.typing import MultiPartFilesAltType
from pymediainfo import MediaInfo
import pyotp

from src.backend.image_host_uploading.base_image_host import ImageUploadRequest
from src.backend.image_host_uploading.img_box import ImageBoxUploader
from src.backend.trackers.cookie_storage import load_cookies, save_cookies
from src.backend.trackers.utils import DISC_TITLE_REGEX, TRACKER_HEADERS
from src.backend.upload_retry import classify_upload_post_error
from src.backend.utils.file_utilities import release_stem
from src.backend.utils.http_client import new_http_session
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.passthepopcorn import (
    PTPCodec,
    PTPContainer,
    PTPResolution,
    PTPSource,
    PTPType,
)
from src.exceptions import TrackerError
from src.frontend.utils import ask_thread_safe_prompt
from src.logger.nfo_forge_logger import LOG
from src.payloads.media_search import MediaSearchPayload
from src.payloads.tracker_search_result import TrackerSearchResult
from src.plugins.api import MetadataMediaKind
from src.utils.secret_redaction import scrub_secrets


def ptp_uploader(
    api_user: str,
    api_key: str,
    username: str,
    password: str,
    announce_url: str,
    torrent_file: Path,
    input_path: Path,
    nfo: str,
    mediainfo_obj: MediaInfo,
    media_search_payload: MediaSearchPayload,
    cookie_dir: Path,
    totp: str | None = None,
    timeout: int = 60,
    content_size: int | None = None,
) -> bool | None:
    """Upload to PassThePopcorn.

    The one uploader that takes no ``tracker_title``. PTP's form has no
    release-name field: it derives the release from structured values --
    ``resolution``, ``other_codec``, ``other_container``, ``other_source`` and
    ``remaster_title`` -- plus the name inside the .torrent itself. The only
    "title" it accepts is the *film's* name (with year, poster, tags and plot)
    when a new group has to be created, which comes from the metadata search
    rather than from a naming template.

    A title override configured for PTP therefore shapes what NfoForge shows
    and records for the upload, not what PTP receives.
    """
    torrent_file = Path(torrent_file)
    uploader = PTPUploader(
        username=username,
        password=password,
        mediainfo_obj=mediainfo_obj,
        announce_url=announce_url,
        cookie_dir=cookie_dir,
        totp=totp,
        timeout=timeout,
    )
    auth_token = uploader.login()
    if not auth_token:
        raise TrackerError("Failed to get auth token")

    if not media_search_payload.imdb_id:
        raise TrackerError("Missing IMDb ID")
    group_id = PTPSearch(
        api_user=api_user, api_key=api_key, timeout=timeout
    ).get_group_id(media_search_payload.imdb_id)
    LOG.debug(LOG.LOG_SOURCE.BE, f"Group ID: {group_id}")

    return uploader.upload(
        auth_token=auth_token,
        media_search_payload=media_search_payload,
        torrent_file=torrent_file,
        input_path=input_path,
        nfo=nfo,
        group_id=group_id,
        content_size=content_size,
    )


class PTPUploader:
    _MAX_2FA_ATTEMPTS = 3
    _2FA_BACKOFF_SECONDS = 0.5

    __slots__ = (
        "username",
        "password",
        "mediainfo_obj",
        "announce_url",
        "cookie_path",
        "totp",
        "timeout",
        "_session",
    )

    URL = f"{TrackerSelection.PASS_THE_POPCORN.get_root_url()}torrents.php"
    UPLOAD_URL = f"{TrackerSelection.PASS_THE_POPCORN.get_root_url()}upload.php"
    LOGIN_URL = (
        f"{TrackerSelection.PASS_THE_POPCORN.get_root_url()}ajax.php?action=login"
    )

    FLAT_SUB_LANGUAGE_MAP = {
        "Arabic": 22,
        "ara": 22,
        "ar": 22,
        "Brazilian Portuguese": 49,
        "Brazilian": 49,
        "Portuguese-BR": 49,
        "pt-br": 49,
        "Bulgarian": 29,
        "bul": 29,
        "bg": 29,
        "Chinese": 14,
        "chi": 14,
        "zh": 14,
        "Chinese (Simplified)": 14,
        "Chinese (Traditional)": 14,
        "Croatian": 23,
        "hrv": 23,
        "hr": 23,
        "scr": 23,
        "Czech": 30,
        "cze": 30,
        "cz": 30,
        "cs": 30,
        "Danish": 10,
        "dan": 10,
        "da": 10,
        "Dutch": 9,
        "dut": 9,
        "nl": 9,
        "English": 3,
        "eng": 3,
        "en": 3,
        "en-US": 3,
        "English (CC)": 3,
        "English - SDH": 3,
        "English - Forced": 50,
        "English (Forced)": 50,
        "en (Forced)": 50,
        "en-US (Forced)": 50,
        "English Intertitles": 51,
        "English (Intertitles)": 51,
        "English - Intertitles": 51,
        "en (Intertitles)": 51,
        "en-US (Intertitles)": 51,
        "Estonian": 38,
        "est": 38,
        "et": 38,
        "Finnish": 15,
        "fin": 15,
        "fi": 15,
        "French": 5,
        "fre": 5,
        "fr": 5,
        "German": 6,
        "ger": 6,
        "de": 6,
        "Greek": 26,
        "gre": 26,
        "el": 26,
        "Hebrew": 40,
        "heb": 40,
        "he": 40,
        "Hindi": 41,
        "hin": 41,
        "hi": 41,
        "Hungarian": 24,
        "hun": 24,
        "hu": 24,
        "Icelandic": 28,
        "ice": 28,
        "is": 28,
        "Indonesian": 47,
        "ind": 47,
        "id": 47,
        "Italian": 16,
        "ita": 16,
        "it": 16,
        "Japanese": 8,
        "jpn": 8,
        "ja": 8,
        "Korean": 19,
        "kor": 19,
        "ko": 19,
        "Latvian": 37,
        "lav": 37,
        "lv": 37,
        "Lithuanian": 39,
        "lit": 39,
        "lt": 39,
        "Norwegian": 12,
        "nor": 12,
        "no": 12,
        "Persian": 52,
        "fa": 52,
        "far": 52,
        "Polish": 17,
        "pol": 17,
        "pl": 17,
        "Portuguese": 21,
        "por": 21,
        "pt": 21,
        "Romanian": 13,
        "rum": 13,
        "ro": 13,
        "Russian": 7,
        "rus": 7,
        "ru": 7,
        "Serbian": 31,
        "srp": 31,
        "sr": 31,
        "scc": 31,
        "Slovak": 42,
        "slo": 42,
        "sk": 42,
        "Slovenian": 43,
        "slv": 43,
        "sl": 43,
        "Spanish": 4,
        "spa": 4,
        "es": 4,
        "Swedish": 11,
        "swe": 11,
        "sv": 11,
        "Thai": 20,
        "tha": 20,
        "th": 20,
        "Turkish": 18,
        "tur": 18,
        "tr": 18,
        "Ukrainian": 34,
        "ukr": 34,
        "uk": 34,
        "Vietnamese": 25,
        "vie": 25,
        "vi": 25,
    }

    def __init__(
        self,
        username: str,
        password: str,
        mediainfo_obj: MediaInfo,
        announce_url: str,
        cookie_dir: Path,
        totp: str | None = None,
        timeout: int = 60,
    ) -> None:
        self.username = username
        self.password = password
        self.mediainfo_obj = mediainfo_obj
        self.announce_url = announce_url
        self.cookie_path = cookie_dir / "ptp_cookie.json"
        self.totp = totp
        self.timeout = timeout

        self._session = new_http_session()

    def upload(
        self,
        auth_token: str,
        media_search_payload: MediaSearchPayload,
        torrent_file: Path,
        input_path: Path,
        nfo: str,
        group_id: str | None = None,
        content_size: int | None = None,
    ) -> bool | None:
        if not media_search_payload.tmdb_data:
            raise TrackerError("Missing TMDB data")
        data = {
            "submit": "true",
            "remaster_year": "",
            "remaster_title": self._remaster_title(input_path),
            "type": self._get_type(media_search_payload),
            "codec": "Other",  # sending the codec as Other to fill with other_codec
            "other_codec": self._get_codec(input_path, content_size),
            "resolution": self._resolution(),
            "container": "Other",  # sending container as Other to fill with other_container
            "other_container": self._get_container(input_path),
            "source": "Other",  # sending the source as Other to fill with other_source
            "other_source": self._source(input_path),
            "release_desc": nfo,
            "nfo_text": "",  # appears to do nothing at all
            "subtitles[]": self._subtitles(),
            # "trumpable[]": ptp_trumpable, # TODO: implement this eventually?
            "AntiCsrfToken": auth_token,
        }

        # determine url
        if group_id:
            url = f"{self.UPLOAD_URL}?groupid={group_id}"
            data["groupid"] = group_id
        else:
            url = self.UPLOAD_URL
            get_poster = media_search_payload.poster_url
            if not get_poster or not isinstance(get_poster, str):
                raise TrackerError(
                    "Couldn't automatically detect a poster for PassThePopcorn"
                )
            image_box_url = self._upload_poster_to_imgbox(get_poster)

            tags = ", ".join(
                genre.lower() for genre in media_search_payload.genre_names
            )
            if not tags:
                tags = ", ".join(
                    str(x.name).lower() for x in media_search_payload.genres
                )

            new_group_data = {
                "title": media_search_payload.title or "",
                "year": media_search_payload.year or "",
                "image": image_box_url,
                "tags": tags,
                "album_desc": media_search_payload.plot or "",
                # "trailer": "", # TODO: detect eventually?
            }
            data.update(new_group_data)

        # upload the torrent. `self._session` is reused across `login()` and
        # `upload()`, so it must not be closed here -- only its `post()`
        # response is used, and the session itself stays open for the
        # lifetime of the PTPUploader instance.
        files: MultiPartFilesAltType = {}
        with open(torrent_file, "rb") as t_file:
            files.update(
                {
                    "file_input": (
                        "placeholder.torrent",
                        t_file.read(),
                        "application/x-bittorent",
                    )
                }
            )
        try:
            upload = self._session.post(
                url=url,
                headers=TRACKER_HEADERS,
                data=data,
                files=files,
                timeout=self.timeout,
            )
        except niquests.exceptions.RequestException as error:
            upload_error_msg = f"Upload to PTP failed: {error}"
            LOG.error(LOG.LOG_SOURCE.BE, upload_error_msg)
            retryable, server_accepted = classify_upload_post_error(error)
            raise TrackerError(
                upload_error_msg,
                retryable=retryable,
                server_accepted=server_accepted,
            ) from error

        extracted_error = self._extract_upload_error(upload.text)
        LOG.debug(
            LOG.LOG_SOURCE.BE,
            "PassThePopcorn upload response: "
            f"status={upload.status_code}, "
            f"url={scrub_secrets(str(upload.url))}, "
            f"error={extracted_error or 'none'}",
        )

        # if the response contains our announce URL, then we are on the upload page and the upload wasn't successful.
        if upload.text and upload.text.find(self.announce_url) != -1:
            raise TrackerError(
                f"Upload to PTP failed: {extracted_error or 'unknown error'} "
                f"({upload.status_code})"
            )

        # URL format in case of successful upload: https://passthepopcorn.me/torrents.php?id=9329&torrentid=91868
        check_for_success = (
            re.match(
                r".*?passthepopcorn\.me/torrents\.php\?id=(\d+)&torrentid=(\d+)",
                upload.url,
            )
            if upload.url
            else None
        )
        if not check_for_success:
            raise TrackerError(
                f"Upload to PTP failed: result URL {upload.url} ({upload.status_code}) is not the expected one."
            )
        else:
            return True

    @staticmethod
    def _extract_upload_error(body: str | None) -> str | None:
        if not body:
            return None
        match = re.search(
            r"""<div class="alert alert--error.*?>(.+?)</div>""",
            body,
            flags=re.DOTALL,
        )
        if not match:
            return None
        error_text = re.sub(r"<[^>]+>", " ", match.group(1))
        error_text = re.sub(r"\s+", " ", error_text).strip()
        return scrub_secrets(error_text)[:500] or None

    def _upload_poster_to_imgbox(self, image_url: str) -> str:
        """Download a new-group poster and host it on ImageBox for PTP."""
        try:
            response = self._session.get(image_url, timeout=self.timeout)
            response.raise_for_status()
            poster_content = response.content
            if poster_content is None:
                raise TrackerError("Poster download returned no content")
            with TemporaryDirectory(prefix="nfoforge-ptp-") as directory:
                poster_path = Path(directory) / "poster.jpg"
                poster_path.write_bytes(poster_content)
                uploaded = asyncio.run(
                    ImageBoxUploader().upload(
                        ImageUploadRequest(filepaths=(poster_path,))
                    )
                )
        except Exception as error:
            raise TrackerError(
                f"Failed to host PassThePopcorn poster on ImageBox: {error}"
            ) from error

        image_data = uploaded.get(0)
        if not image_data or not image_data.url:
            raise TrackerError("ImageBox did not return a URL for the PTP poster")
        return image_data.url

    def _extract_image_urls(self, url_data: str) -> list[str]:
        get_raw_url_images = re.findall(r"\[url=(.+?)\]", url_data)
        if get_raw_url_images:
            return get_raw_url_images

        get_raw_img_images = re.findall(r"\[img\](.+?)\[/", url_data)
        if get_raw_img_images:
            return get_raw_img_images

        raise TrackerError("Cannot detect image URLs")

    def _remaster_title(self, input_path: Path) -> str:
        remaster_title = set()
        title_lowered = release_stem(input_path).lower()

        # editions
        def collect_editions(source: dict[str, Any], key: str) -> list[Any]:
            """Helper function to collect edition data from a source."""
            values = source.get(key, [])
            return values if isinstance(values, list) else [values]

        # ensure we have unique editions
        edition_set = set()
        guess_name = guessit(input_path.name)

        # collect editions from `guess_name`
        edition_set.update(collect_editions(guess_name, "edition"))

        # check for "Open Matte" in `other` fields of `guess_name`
        other = guess_name.get("other", [])
        items = other if isinstance(other, list) else [other]
        if "Open Matte" in items:
            edition_set.add("Open Matte")

        # normalize some editions
        if edition_set:
            normalized_edition_set = set()
            for item in edition_set:
                item_lowered = str(item).lower()
                if "director" in item_lowered:
                    normalized_edition_set.add("Directors Cut")
                elif "extended" in item_lowered:
                    normalized_edition_set.add("Extended Cut")
                elif "theatrical" in item_lowered:
                    normalized_edition_set.add("Theatrical Cut")
                else:
                    normalized_edition_set.add(item)
            edition_set = normalized_edition_set

        for item in edition_set:
            remaster_title.add(item)

        # features
        if "remux" in title_lowered:
            remaster_title.add("Remux")
        if "atmos" in title_lowered:
            remaster_title.add("Dolby Atmos")
        if "dual" in title_lowered:
            remaster_title.add("Dual Audio")
        if "dubbed" in title_lowered:
            remaster_title.add("English Dub")
        # if meta.get('has_commentary', False) is True:
        #     remaster_title.append('With Commentary')

        # HDR10, HDR10+, Dolby Vision, 10-bit,
        dv = "DV" if "Dolby Vision" in guess_name.get("other", "") else ""
        hdr10 = "HDR" if "HDR10" in guess_name.get("other", "") else ""
        hdr10_plus = "HDR10Plus" if "HDR10+" in guess_name.get("other", "") else ""
        hlg = ""
        pq = ""

        if self.mediainfo_obj and self.mediainfo_obj.video_tracks:
            try:
                hdr_format = self.mediainfo_obj.video_tracks[0].other_hdr_format[0]
                if hdr_format:
                    dv = "DV" if "Dolby Vision" in hdr_format else ""
                    if dv and "dvhe.05" not in hdr_format:
                        dv = f"{dv} HDR"
                    hdr10_plus = "HD10Plus" if "HDR10+" in hdr_format else ""
                    hdr10 = "HDR" if "HDR10" in hdr_format else ""
            except (AttributeError, IndexError, TypeError):
                dv = hdr10 = hdr10_plus = ""

            transfer_characteristics = self.mediainfo_obj.video_tracks[
                0
            ].transfer_characteristics
            if transfer_characteristics == "HLG":
                hlg = transfer_characteristics
            elif transfer_characteristics == "PQ":
                pq = transfer_characteristics

        dynamic_range_type = ""
        if dv and not hdr10_plus:
            dynamic_range_type = dv
        elif dv and hdr10_plus:
            dynamic_range_type = "DV HDR10Plus"
        elif not dv and hdr10_plus:
            dynamic_range_type = "HDR10Plus"
        elif not dv and not hdr10_plus and hdr10:
            dynamic_range_type = "HDR"
        else:
            if any([hlg, pq]):
                dynamic_range_type = hlg if hlg else pq

        if dynamic_range_type:
            remaster_title.add(dynamic_range_type)

        output = ""
        if remaster_title:
            output = " / ".join(sorted(remaster_title))
        return output

    def _get_type(self, media_search_payload: MediaSearchPayload) -> str:
        media_kind = media_search_payload.media_kind
        provider_type_map = {
            MetadataMediaKind.SHORT: PTPType.SHORT_FILM,
            MetadataMediaKind.MINI_SERIES: PTPType.MINI_SERIES,
            MetadataMediaKind.STAND_UP_COMEDY: PTPType.STAND_UP_COMEDY,
            MetadataMediaKind.LIVE_PERFORMANCE: PTPType.LIVE_PERFORMANCE,
        }
        if media_kind in provider_type_map:
            return str(provider_type_map[media_kind].value)

        if media_search_payload.media_type is MediaType.SERIES:
            return str(PTPType.MINI_SERIES.value)

        duration = 0
        try:
            duration = int(self.mediainfo_obj.general_tracks[0].duration) // 60000
        except (AttributeError, IndexError, TypeError, ValueError):
            pass
        ptp_type = PTPType.SHORT_FILM if 0 < duration < 45 else PTPType.FEATURE_FILM
        return str(ptp_type.value)

    def _get_codec(self, input_path: Path, content_size: int | None = None) -> str:
        title_lowered = release_stem(input_path).lower()
        title_lowered_strip_periods = title_lowered.replace(".", "")

        # disc
        if DISC_TITLE_REGEX.search(title_lowered):
            input_file_size = (
                content_size if content_size is not None else input_path.stat().st_size
            )
            if input_file_size <= 26_843_545_600:
                return str(PTPCodec.BD25.value)
            elif input_file_size <= 53_687_091_200:
                if "1080i" in title_lowered or "1080p" in title_lowered:
                    return str(PTPCodec.BD50.value)
                elif "2160p" in title_lowered:
                    return str(PTPCodec.BD50.value)
            elif input_file_size <= 70_866_960_384:
                return str(PTPCodec.BD66.value)
            elif input_file_size <= 107_374_182_400:
                return str(PTPCodec.BD100.value)

        # dvd5/dvd9
        elif "dvd5" in title_lowered_strip_periods:
            return str(PTPCodec.DVD5.value)
        elif "dvd9" in title_lowered_strip_periods:
            return str(PTPCodec.DVD9.value)

        # encodes
        elif self.mediainfo_obj.video_tracks[0].format == "AVC":
            return str(PTPCodec.H264.value)
        elif self.mediainfo_obj.video_tracks[0].format == "HEVC":
            return str(PTPCodec.H265.value)

        return str(PTPCodec.AUTO_DETECT.value)

    def _resolution(self) -> str:
        try:
            resolution = PTPResolution(
                VideoResolutionAnalyzer(self.mediainfo_obj).get_resolution()
            ).value
        except ValueError:
            resolution = PTPResolution.OTHER.value
        return str(resolution)

    def _get_container(self, input_path: Path) -> str:
        extension = input_path.suffix
        if extension == ".mkv":
            return str(PTPContainer.MKV.value)
        elif extension == ".mp4":
            return str(PTPContainer.MP4.value)
        elif extension in (".mpeg", ".mpg"):
            return str(PTPContainer.MPG.value)
        return str(PTPContainer.AUTO_DETECT.value)

    def _source(self, input_path: Path) -> str:
        title_lowered = release_stem(input_path).lower()
        title_lowered = re.sub(r"\W", ".", title_lowered)
        title_lowered = re.sub(r"\.{2,}", ".", title_lowered)
        if "bluray" in title_lowered:
            return str(PTPSource.BLU_RAY.value)
        elif "hddvd" in title_lowered:
            return str(PTPSource.HD_DVD.value)
        elif "dvd" in title_lowered:
            return str(PTPSource.DVD.value)
        elif "hdtv" in title_lowered:
            return str(PTPSource.HDTV.value)
        elif "web" in title_lowered:
            return str(PTPSource.WEB.value)
        return str(PTPSource.OTHER.value)

    def _subtitles(self) -> list[int]:
        subs: set[int] = set()
        for text_track in self.mediainfo_obj.text_tracks:
            language = text_track.language
            if text_track.forced == "Yes" and language == "en":
                subs.add(50)
            elif language in self.FLAT_SUB_LANGUAGE_MAP:
                subs.add(self.FLAT_SUB_LANGUAGE_MAP[language])
        if not subs:
            subs.add(44)
        return list(subs)

    def login(self) -> str | None:
        if self._load_cookies():
            try:
                cookie_token = self._validate_session()
                if cookie_token:
                    LOG.debug(
                        LOG.LOG_SOURCE.BE,
                        "PassThePopcorn cookies valid, skipping login",
                    )
                    return cookie_token
                else:
                    # cookie invalid/expired, delete and retry login
                    try:
                        self.cookie_path.unlink()
                        LOG.debug(
                            LOG.LOG_SOURCE.BE,
                            f"Deleted expired PassThePopcorn cookie: {self.cookie_path}",
                        )
                    except Exception as e:
                        LOG.warning(
                            LOG.LOG_SOURCE.BE, f"Failed to delete expired cookie: {e}"
                        )
            except TrackerError as e:
                # cookie invalid/expired, delete and retry login
                try:
                    self.cookie_path.unlink()
                    LOG.debug(
                        LOG.LOG_SOURCE.BE,
                        f"Deleted expired PassThePopcorn cookie (exception): {self.cookie_path}",
                    )
                except Exception as ex:
                    LOG.warning(
                        LOG.LOG_SOURCE.BE, f"Failed to delete expired cookie: {ex}"
                    )
                LOG.info(
                    LOG.LOG_SOURCE.BE,
                    f"PTP cookie invalid: {e}. Retrying login with fresh session.",
                )

        LOG.debug(LOG.LOG_SOURCE.BE, "Cookies are invalid or missing, performing login")
        pass_key = self.announce_url.split("/")[-2]
        data = {
            "username": self.username,
            "password": self.password,
            "passkey": pass_key,
            "keeplogged": "1",
        }
        try:
            with self._session.post(
                self.LOGIN_URL,
                data=data,
                headers=TRACKER_HEADERS,
                timeout=self.timeout,
            ) as response:
                if response.ok and response.status_code == 200:
                    token = None
                    response_json = response.json()
                    result = response_json.get("Result", "")
                    if result == "Ok":
                        token = response_json.get("AntiCsrfToken")
                    elif result == "TfaRequired":
                        if not self.totp:
                            raise TrackerError(
                                "Missing TOTP and you have TFA enabled, cannot continue"
                            )
                        tried_totp = False
                        for attempt in range(self._MAX_2FA_ATTEMPTS):
                            tofa_response, tried_totp = self._handle_2fa(
                                data, self.totp, tried_totp
                            )
                            response_json: dict[str, Any] = {}
                            if tofa_response.status_code == 200:
                                try:
                                    parsed_response = tofa_response.json()
                                except (TypeError, ValueError):
                                    parsed_response = None
                                if isinstance(parsed_response, dict):
                                    response_json = parsed_response
                            token = response_json.get("AntiCsrfToken")
                            if token:
                                break
                            LOG.error(
                                LOG.LOG_SOURCE.BE,
                                "2FA failed: Invalid code or token not received.",
                            )
                            if attempt < self._MAX_2FA_ATTEMPTS - 1:
                                time.sleep(self._2FA_BACKOFF_SECONDS * (2**attempt))
                        if not token:
                            raise TrackerError(
                                "PassThePopcorn 2FA failed after "
                                f"{self._MAX_2FA_ATTEMPTS} attempts"
                            )
                    if token:
                        self._save_cookies()
                        return str(token)
        except niquests.RequestException as e:
            raise TrackerError(f"Server error: {e}") from e
        except TrackerError:
            raise
        except Exception as unhandled_exception:
            raise TrackerError(
                f"Unhandled exception: {unhandled_exception}"
            ) from unhandled_exception
        return None

    def _validate_session(self) -> str | None:
        """Perform a lightweight request to validate the session, if valid the required token is returned."""
        try:
            with self._session.get(self.UPLOAD_URL, timeout=self.timeout) as response:
                if (
                    response.text
                    and response.text.find("""<a href="login.php?act=recover">""") != -1
                ):
                    raise TrackerError(
                        "Looks like you are not logged in to PTP. Probably due to the bad user name, password, or expired session"
                    )
                elif (
                    response.text
                    and "Your popcorn quota has been reached, come back later!"
                    in response.text
                ):
                    raise TrackerError(
                        "Your PTP request/popcorn quota has been reached, try again later"
                    )
                find_token = (
                    re.search(
                        r'data-AntiCsrfToken="(.+)"', response.text, flags=re.MULTILINE
                    )
                    if response.text
                    else None
                )
                if find_token:
                    return str(find_token.group(1))
        except niquests.RequestException:
            return None
        return None

    def _save_cookies(self) -> None:
        save_cookies(self._session.cookies, self.cookie_path)
        LOG.debug(
            LOG.LOG_SOURCE.BE, f"PassThePopcorn cookies saved: {self.cookie_path}"
        )

    def _load_cookies(self) -> bool:
        if load_cookies(self._session.cookies, self.cookie_path):
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                f"PassThePopcorn cookies loaded from {self.cookie_path}",
            )
            return True
        LOG.debug(LOG.LOG_SOURCE.BE, "PassThePopcorn cookies not found")
        return False

    def _handle_2fa(
        self, data: dict[str, str], totp: str, tried_totp: bool
    ) -> tuple[niquests.Response, bool]:
        if not tried_totp and totp:
            data["TfaCode"] = pyotp.TOTP(totp).now()
            tried_totp = True
        else:
            got_code, code = ask_thread_safe_prompt(
                "2FA", "Enter your 2FA code for PassThePopcorn:"
            )
            if not got_code or not code:
                raise TrackerError("2FA cancelled or no code entered")
            data["TfaCode"] = code
        data["TfaType"] = "normal"
        headers = {
            "User-Agent": TRACKER_HEADERS["User-Agent"],
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = self._session.post(
            self.LOGIN_URL,
            data=data,
            headers=headers,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            LOG.error(
                LOG.LOG_SOURCE.BE,
                f"2FA failed: {response.reason} ({response.status_code})",
            )
        return response, tried_totp


_PTP_SEARCH_SESSION = new_http_session()


class PTPSearch:
    """Search PassThePopcorn"""

    __slots__ = ("api_user", "api_key", "timeout")

    URL = f"{TrackerSelection.PASS_THE_POPCORN.get_root_url()}torrents.php"

    def __init__(self, api_user: str, api_key: str, timeout: int = 60) -> None:
        self.api_user = api_user
        self.api_key = api_key
        self.timeout = timeout

    def search(
        self,
        movie_title: str,
        movie_year: int,
        file_name: str,
        imdb_id: str | None = None,
    ) -> list[TrackerSearchResult]:
        results: list[TrackerSearchResult] = []

        headers = {
            "ApiUser": self.api_user,
            "ApiKey": self.api_key,
            "User-Agent": TRACKER_HEADERS["User-Agent"],
        }
        params: dict[str, str] = {
            "searchstr": movie_title,
            "year": str(movie_year),
            "noredirect": "1",
            "action": "advanced",
        }
        if imdb_id:
            params["searchstr"] = imdb_id
        if file_name:
            params["filelist"] = file_name

        LOG.info(
            LOG.LOG_SOURCE.BE,
            f"Searching PassThePopcorn for title: {movie_title} ({movie_year})",
        )
        try:
            response = _PTP_SEARCH_SESSION.get(
                self.URL, headers=headers, params=params, timeout=self.timeout
            )
            if response.status_code != 200:
                raise TrackerError(
                    "Error searching PassThePopcorn: "
                    f"HTTP {response.status_code} ({response.reason})"
                )
            response_json = response.json()
            movies = response_json.get("Movies", [])
            if not isinstance(movies, list):
                return results
            for torrent in movies:
                for movie_file in torrent.get("Torrents", []):
                    for item in movie_file.get("FileList", []):
                        path_name = item.get("Path", "")
                        if path_name == file_name:
                            group_id = torrent.get("GroupId")
                            movie_id = movie_file.get("Id")
                            link = (
                                f"{self.URL}?id={group_id}&torrentid={movie_id}"
                                if group_id and movie_id
                                else None
                            )
                            result = TrackerSearchResult(
                                name=path_name,
                                url=link,
                                release_size=item.get("Size"),
                                created_at=torrent.get("LastUploadTime"),
                                seeders=torrent.get("TotalSeeders"),
                                leechers=torrent.get("TotalLeechers"),
                                grabs=torrent.get("TotalSnatched"),
                                files=len(movie_file.get("FileList", [])),
                                imdb_id=f"tt{torrent.get('ImdbId')}"
                                if torrent.get("ImdbId")
                                else None,
                            )
                            results.append(result)

            return results
        except niquests.exceptions.RequestException as error_message:
            raise TrackerError(str(error_message)) from error_message

    def get_group_id(self, imdb_id: str) -> str | None:
        params = {
            "imdb": imdb_id,
        }
        headers = {
            "ApiUser": self.api_user,
            "ApiKey": self.api_key,
            "User-Agent": TRACKER_HEADERS["User-Agent"],
        }

        try:
            response = _PTP_SEARCH_SESSION.get(
                self.URL, headers=headers, params=params, timeout=self.timeout
            )
            if response.ok and response.status_code == 200:
                response_json = response.json()
                if response_json.get("Page", "") == "Details":
                    group_id = response_json.get("GroupId")
                    return str(group_id) if group_id is not None else None
        except niquests.exceptions.RequestException as error_message:
            raise TrackerError(str(error_message)) from error_message
        return None
