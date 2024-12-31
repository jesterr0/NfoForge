import re
import regex
import requests
import pickle
import pyotp
from guessit import guessit
from imdb.Movie import Movie
from pathlib import Path
from pymediainfo import MediaInfo

from src.logger.nfo_forge_logger import LOG
from src.enums.trackers import PTPResolution, PTPType, PTPCodec, PTPContainer, PTPSource
from src.exceptions import TrackerError
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.backend.trackers.utils import TRACKER_HEADERS
from src.payloads.tracker_search_result import TrackerSearchResult
from src.payloads.media_search import MediaSearchPayload


# TODO: we need to test actually uploading a file - DONE BUT:
# The images must be linked directly without any url BBCode tags.
# The screenshots must be after the MediaInfo log in the description box.
# Template requirements will have to be like:
# Full mediainfo
# at least 3 screenshots

# TODO: clean up code


def ptp_uploader(
    api_user: str,
    api_key: str,
    username: str,
    password: str,
    announce_url: str,
    torrent_file: Path,
    file_input: Path,
    nfo: str,
    mediainfo_obj: MediaInfo,
    media_search_payload: MediaSearchPayload,
    ptp_img_api_key: str,
    cookie_dir: Path,
    totp: str | None = None,
    timeout: int = 60,
) -> bool | None:
    torrent_file = Path(torrent_file)
    file_input = Path(file_input)
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

    upload = uploader.upload(
        auth_token=auth_token,
        media_search_payload=media_search_payload,
        torrent_file=torrent_file,
        file_input=file_input,
        nfo=nfo,
        ptp_img_api_key=ptp_img_api_key,
        group_id=group_id,
    )
    return upload


class PTPUploader:
    URL = "https://passthepopcorn.me/torrents.php"
    UPLOAD_URL = "https://passthepopcorn.me/upload.php"
    LOGIN_URL = "https://passthepopcorn.me/ajax.php?action=login"

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
        self.cookie_path = cookie_dir / "ptp_cookie.pkl"
        self.totp = totp
        self.timeout = timeout

        self._session = requests.Session()

    def upload(
        self,
        auth_token: str,
        media_search_payload: MediaSearchPayload,
        torrent_file: Path,
        file_input: Path,
        nfo: str,
        ptp_img_api_key: str,
        group_id: str | None = None,
    ) -> bool | None:
        if not media_search_payload.imdb_data:
            raise TrackerError("Missing IMDb data")
        if not media_search_payload.tmdb_data:
            raise TrackerError("Missing TMDB data")

        data = {
            "submit": "true",
            "remaster_year": "",
            "remaster_title": self._remaster_title(
                media_search_payload.imdb_data, file_input
            ),
            "type": self._get_type(media_search_payload.imdb_data),
            "codec": "Other",  # sending the codec as Other to fill with other_codec
            "other_codec": self._get_codec(file_input),
            "resolution": self._resolution(),
            "container": "Other",  # sending container as Other to fill with other_container
            "other_container": self._get_container(file_input),
            "source": "Other",  # sending the source as Other to fill with other_source
            "other_source": self._source(file_input),
            "release_desc": nfo,
            "nfo_text": nfo,
            # "nfo_text": "",
            "subtitles[]": self._subtitles(),
            # "trumpable[]": ptp_trumpable, # TODO: implement this eventually?
            "AntiCsrfToken": auth_token,
        }

        # determine url
        if group_id:
            url = f"https://passthepopcorn.me/upload.php?groupid={group_id}"
            data["groupid"] = group_id
        else:
            url = "https://passthepopcorn.me/upload.php"
            get_poster = media_search_payload.imdb_data.get("full-size cover url")
            if not get_poster:
                get_poster = (
                    f'https://image.tmdb.org/t/p/original{media_search_payload.tmdb_data.get("poster_path")}'
                    if media_search_payload.tmdb_data.get("poster_path")
                    else None
                )
            if not get_poster or not isinstance(get_poster, str):
                raise TrackerError(
                    "Couldn't automatically detect a poster for PassThePopcorn"
                )
            ptp_url = self._ptp_img_upload(get_poster, ptp_img_api_key)

            tags = ""
            get_tags = media_search_payload.imdb_data.get("genres")
            if get_tags:
                tags = ", ".join((str(x).lower() for x in get_tags))
            if not get_tags:
                tags = ", ".join(
                    str(x.name).lower() for x in media_search_payload.genres
                )

            new_group_data = {
                "title": media_search_payload.imdb_data.get(
                    "title", media_search_payload.tmdb_data.get("title", "")
                ),
                "year": media_search_payload.imdb_data.get(
                    "year", media_search_payload.tmdb_data.get("year", "")
                ),
                "image": ptp_url,
                "tags": tags,
                "album_desc": media_search_payload.imdb_data.get(
                    "plot outline", media_search_payload.tmdb_data.get("overview", "")
                ),
                # "trailer": "", # TODO: detect eventually?
            }
            data.update(new_group_data)

        LOG.debug(LOG.LOG_SOURCE.BE, f"PassThePopcorn payload: {data}")

        # upload the torrent
        with self._session as response:
            files = {}
            with open(torrent_file, "rb") as t_file:
                files = {
                    "file_input": (
                        "placeholder.torrent",
                        t_file.read(),
                        "application/x-bittorent",
                    )
                }
            upload = response.post(
                url=url, headers=TRACKER_HEADERS, data=data, files=files
            )

            # if the response contains our announce URL, then we are on the upload page and the upload wasn't successful.
            if upload.text.find(self.announce_url) != -1:
                error_message = ""
                match = re.search(
                    r"""<div class="alert alert--error.*?>(.+?)</div>""", upload.text
                )
                if match:
                    error_message = f" {match.group(1)} "
                raise TrackerError(
                    f"Upload to PTP failed:{error_message}({upload.status_code})"
                )

            # URL format in case of successful upload: https://passthepopcorn.me/torrents.php?id=9329&torrentid=91868
            check_for_success = re.match(
                r".*?passthepopcorn\.me/torrents\.php\?id=(\d+)&torrentid=(\d+)",
                upload.url,
            )
            if not check_for_success:
                raise TrackerError(
                    f"Upload to PTP failed: result URL {upload.url} ({upload.status_code}) is not the expected one."
                )
            else:
                return True

    def _ptp_img_upload(self, image_url: str, ptp_img_api_key: str) -> str:
        payload = {
            "format": "json",
            "api_key": ptp_img_api_key,
            "link-upload": image_url,
        }
        headers = {"referer": "https://ptpimg.me/index.php"}
        url = "https://ptpimg.me/upload.php"

        response = requests.post(url, headers=headers, data=payload)
        try:
            response = response.json()
            ptpimg_code = response[0]["code"]
            ptpimg_ext = response[0]["ext"]
            img_url = f"https://ptpimg.me/{ptpimg_code}.{ptpimg_ext}"
            return img_url
        except Exception as e:
            raise TrackerError(f"Failed to re host image to ptpimg host: {e}")

    def _remaster_title(self, imdb_data: Movie, file_input: Path) -> str:
        remaster_title = set()
        title_lowered = file_input.stem.lower()

        # collections
        # Masters of Cinema, The Criterion Collection, Warner Archive Collection
        try:
            distributors = {str(x).upper() for x in imdb_data["distributors"]}
            if {"WARNER ARCHIVE", "WARNER ARCHIVE COLLECTION", "WAC"} & distributors:
                remaster_title.add("Warner Archive Collection")
            elif {"CRITERION", "CRITERION COLLECTION", "CC"} & distributors:
                remaster_title.add("The Criterion Collection")
            elif {"MASTERS OF CINEMA", "MOC"} & distributors:
                remaster_title.add("Masters of Cinema")
        except IndexError:
            pass

        # editions
        def collect_editions(source, key: str) -> list:
            """Helper function to collect edition data from a source."""
            values = source.get(key, [])
            return values if isinstance(values, list) else [values]

        # ensure we have unique editions
        edition_set = set()
        guess_name = guessit(file_input.name)

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

    def _get_type(self, imdb_data: Movie) -> str:
        ptp_type = PTPType.FEATURE_FILM
        imdb_type = imdb_data.get("kind")
        if imdb_type:
            if imdb_type in ("movie", "tv movie"):
                duration = int(self.mediainfo_obj.general_tracks[0].duration) // 60000
                if duration >= 45 or duration == 0:
                    ptp_type = PTPType.FEATURE_FILM
                else:
                    ptp_type = PTPType.SHORT_FILM
            elif imdb_type == "short":
                ptp_type = PTPType.SHORT_FILM
            elif imdb_type == "tv mini series":
                ptp_type = PTPType.MINI_SERIES
            elif imdb_type == "comedy":
                ptp_type = PTPType.STAND_UP_COMEDY
            elif imdb_type == "concert":
                ptp_type = PTPType.LIVE_PERFORMANCE
        return ptp_type.value

    def _get_codec(self, file_input: Path) -> str:
        title_lowered = str(file_input.stem).lower()
        title_lowered_strip_periods = title_lowered.replace(".", "")

        # disc
        if regex.search(
            (
                r"^(?!.*\b((?<!HD[._ -]|HD)DVD|BDRip|720p|MKV|XviD"
                r"|WMV|d3g|(BD)?REMUX|^(?=.*1080p)(?=.*HEVC)|[xh][-_. ]"
                r"?26[45]|German.*[DM]L|((?<=\d{4}).*German.*([DM]L)?)"
                r"(?=.*\b(AVC|HEVC|VC[-_. ]?1|MVC|MPEG[-_. ]?2)\b))\b)(((?=.*\b(Blu[-_. ]?ray"
                r"|BD|HD[-_. ]?DVD)\b)(?=.*\b(AVC|HEVC|VC[-_. ]?1|MVC|"
                r"MPEG[-_. ]?2|BDMV|ISO)\b))|^((?=.*\b(((?=.*\b((.*_)?COMPLETE.*"
                r"|Dis[ck])\b)(?=.*(Blu[-_. ]?ray|HD[-_. ]?DVD)))|3D[-_. ]?BD|"
                r"BR[-_. ]?DISK|Full[-_. ]?Blu[-_. ]?ray|^((?=.*((BD|UHD)[-_. ]?(25"
                r"|50|66|100|ISO)))))))).*"
            ),
            title_lowered,
        ):
            input_file_size = file_input.stat().st_size
            if input_file_size <= 26_843_545_600:
                return PTPCodec.BD25.value
            elif input_file_size <= 53_687_091_200:
                if "1080i" in title_lowered or "1080p" in title_lowered:
                    return PTPCodec.BD50.value
                elif "2160p" in title_lowered:
                    return PTPCodec.BD50.value
            elif input_file_size <= 70_866_960_384:
                return PTPCodec.BD66.value
            elif input_file_size <= 107_374_182_400:
                return PTPCodec.BD100.value

        # dvd5/dvd9
        elif "dvd5" in title_lowered_strip_periods:
            return PTPCodec.DVD5.value
        elif "dvd9" in title_lowered_strip_periods:
            return PTPCodec.DVD9.value

        # encodes
        elif self.mediainfo_obj.video_tracks[0].format == "AVC":
            return PTPCodec.H264.value
        elif self.mediainfo_obj.video_tracks[0].format == "HEVC":
            return PTPCodec.H265.value

        return PTPCodec.AUTO_DETECT.value

    def _resolution(self) -> str:
        try:
            resolution = PTPResolution(
                VideoResolutionAnalyzer(self.mediainfo_obj).get_resolution()
            ).value
        except ValueError:
            resolution = PTPResolution.OTHER.value
        return resolution

    def _get_container(self, file_input: Path) -> str:
        extension = file_input.suffix
        if extension == ".mkv":
            return PTPContainer.MKV.value
        elif extension == ".mp4":
            return PTPContainer.MP4.value
        elif extension in (".mpeg", ".mpg"):
            return PTPContainer.MPG.value
        return PTPContainer.AUTO_DETECT.value

    def _source(self, file_input: Path) -> str:
        title_lowered = str(file_input.stem).lower()
        title_lowered = re.sub(r"\W", ".", title_lowered)
        title_lowered = re.sub(r"\.{2,}", ".", title_lowered)
        if "bluray" in title_lowered:
            return PTPSource.BLU_RAY.value
        elif "hddvd" in title_lowered:
            return PTPSource.HD_DVD.value
        elif "dvd" in title_lowered:
            return PTPSource.DVD.value
        elif "hdtv" in title_lowered:
            return PTPSource.HDTV.value
        elif "web" in title_lowered:
            return PTPSource.WEB.value
        return PTPSource.OTHER.value

    def _subtitles(self):
        subs = set()
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
            cookie_token = self._validate_session()
            if cookie_token:
                LOG.debug(
                    LOG.LOG_SOURCE.BE, "PassThePopcorn cookies valid, skipping login"
                )
                return cookie_token

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
                self.LOGIN_URL, data=data, headers=TRACKER_HEADERS
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
                        tofa_response = self._handle_2fa(data, self.totp)
                        response_json = tofa_response.json()
                        token = response_json.get("AntiCsrfToken")
                    if token:
                        self._save_cookies()
                        return token
        except requests.RequestException as e:
            raise TrackerError(f"Server error: {e}")
        except Exception as unhandled_exception:
            raise TrackerError(f"Unhandled exception: {unhandled_exception}")

    def _validate_session(self) -> str | None:
        """Perform a lightweight request to validate the session, if valid the required token is returned."""
        try:
            with self._session.get(self.UPLOAD_URL) as response:
                if response.text.find("""<a href="login.php?act=recover">""") != -1:
                    raise TrackerError(
                        "Looks like you are not logged in to PTP. Probably due to the bad user name, password, or expired session"
                    )
                elif (
                    "Your popcorn quota has been reached, come back later!"
                    in response.text
                ):
                    raise TrackerError(
                        "Your PTP request/popcorn quota has been reached, try again later"
                    )
                find_token = re.search(
                    r'data-AntiCsrfToken="(.+)"', response.text, flags=re.MULTILINE
                )
                if find_token:
                    return find_token.group(1)
        except requests.RequestException:
            return None

    def _save_cookies(self) -> None:
        with open(self.cookie_path, "wb") as file:
            pickle.dump(self._session.cookies, file)
        LOG.debug(
            LOG.LOG_SOURCE.BE, f"PassThePopcorn cookies saved: {self.cookie_path}"
        )

    def _load_cookies(self) -> bool:
        if self.cookie_path.exists():
            with open(self.cookie_path, "rb") as file:
                cookies = pickle.load(file)
                self._session.cookies.update(cookies)
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                f"PassThePopcorn cookies loaded from {self.cookie_path}",
            )
            return True
        LOG.debug(LOG.LOG_SOURCE.BE, "PassThePopcorn cookies not found")
        return False

    def _handle_2fa(self, data: dict[str, str], totp: str) -> requests.Response:
        data["TfaCode"] = pyotp.TOTP(totp).now()
        data["TfaType"] = "normal"
        headers = {
            "User-Agent": TRACKER_HEADERS["User-Agent"],
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = self._session.post(
            self.LOGIN_URL,
            data=data,
            headers=headers,
        )
        if response.status_code != 200:
            raise TrackerError(
                f"2FA failed: {response.reason} ({response.status_code})"
            )
        return response


class PTPSearch:
    """Search PassThePopcorn"""

    URL = "https://passthepopcorn.me/torrents.php"

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
    ) -> list[TrackerSearchResult | None]:
        results = []

        headers = {
            "ApiUser": self.api_user,
            "ApiKey": self.api_key,
            "User-Agent": TRACKER_HEADERS["User-Agent"],
        }
        params = {
            "searchstr": movie_title,
            "year": movie_year,
            "noredirect": 1,
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
            response = requests.get(
                self.URL, headers=headers, params=params, timeout=self.timeout
            )
            if response.ok and response.status_code == 200:
                response_json = response.json()
                movies: list[dict] = response_json.get("Movies", [])
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
                                    imdb_id=f'tt{torrent.get("ImdbId")}'
                                    if torrent.get("ImdbId")
                                    else None,
                                )
                                results.append(result)

            return results
        except requests.exceptions.RequestException as error_message:
            raise TrackerError(error_message)

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
            response = requests.get(
                self.URL, headers=headers, params=params, timeout=self.timeout
            )
            if response.ok and response.status_code == 200:
                response_json = response.json()
                if response_json.get("Page", "") == "Details":
                    return response_json.get("GroupId")
        except requests.exceptions.RequestException as error_message:
            raise TrackerError(error_message)
