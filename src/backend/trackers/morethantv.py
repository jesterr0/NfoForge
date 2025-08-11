from collections.abc import Sequence
from datetime import datetime
from os import PathLike
from pathlib import Path
import pickle
import re
from typing import Any
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup, Tag as bs4Tag
import guessit
import niquests
from pymediainfo import MediaInfo
import pyotp
from unidecode import unidecode

from src.backend.trackers.utils import TRACKER_HEADERS
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.enums.audio_formats import AudioFormats
from src.enums.media_mode import MediaMode
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.enums.trackers.morethantv import (
    MTVAudioTags,
    MTVCategories,
    MTVResolutionIDs,
    MTVSourceIDs,
    MTVSourceOrigin,
)
from src.exceptions import TrackerError
from src.frontend.utils import ask_thread_safe_prompt
from src.logger.nfo_forge_logger import LOG
from src.payloads.tracker_search_result import TrackerSearchResult


def mtv_uploader(
    username: str,
    password: str,
    totp: str | None,
    nfo: str,
    group_desc: str | None,
    torrent_file: Path | PathLike[str],
    file_input: Path | str,
    tracker_title: str | None,
    mediainfo_obj: MediaInfo,
    genre_ids: Sequence[TMDBGenreIDsMovies | TMDBGenreIDsSeries],
    media_mode: MediaMode,
    anonymous: bool,
    source_origin: MTVSourceOrigin,
    cookie_dir: Path,
    timeout: int,
):
    torrent_file = Path(torrent_file)
    file_input = Path(file_input)
    uploader = MTVUploader(
        torrent_input=torrent_file,
        mediainfo_obj=mediainfo_obj,
        cookie_dir=cookie_dir,
        timeout=timeout,
    )
    auth_token = uploader.login(username=username, password=password, totp=totp)
    if not auth_token:
        raise TrackerError("Failed to get auth token")

    upload = uploader.upload(
        auth_token=auth_token,
        torrent_file=torrent_file,
        file_input=file_input,
        tracker_title=tracker_title,
        nfo=nfo,
        group_desc=group_desc,
        genre_ids=genre_ids,
        media_mode=media_mode,
        anonymous=anonymous,
        source_origin=source_origin,
    )
    return upload


class MTVUploader:
    LOGIN_URL = "https://www.morethantv.me/login"
    LOGIN_URL_2FA = "https://www.morethantv.me/twofactor/login"
    UPLOAD_URL = "https://www.morethantv.me/upload.php"
    SEARCH_URL = "https://www.morethantv.me/api/torznab"

    def __init__(
        self,
        torrent_input: Path,
        mediainfo_obj: MediaInfo,
        cookie_dir: Path,
        timeout: int = 60,
    ) -> None:
        self.torrent_input = torrent_input
        self.mediainfo_obj = mediainfo_obj
        self.cookie_path = cookie_dir / "mtv_cookie.pkl"
        self.timeout = timeout

        self._session = niquests.Session()

    def login(self, username: str, password: str, totp: str | None) -> str | None:
        if self._load_cookies():
            try:
                cookie_token = self._validate_session()
                if cookie_token:
                    LOG.debug(
                        LOG.LOG_SOURCE.BE, "MoreThanTV cookies valid, skipping login"
                    )
                    return cookie_token
                else:
                    # cookie invalid/expired, delete and retry login
                    try:
                        self.cookie_path.unlink()
                        LOG.debug(
                            LOG.LOG_SOURCE.BE,
                            f"Deleted expired MoreThanTV cookie: {self.cookie_path}",
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
                        f"Deleted expired MoreThanTV cookie (exception): {self.cookie_path}",
                    )
                except Exception as ex:
                    LOG.warning(
                        LOG.LOG_SOURCE.BE, f"Failed to delete expired cookie: {ex}"
                    )
                LOG.info(
                    LOG.LOG_SOURCE.BE,
                    f"MTV cookie invalid: {e}. Retrying login with fresh session.",
                )

        # Initial GET to load the login page
        login_page = self._session.get(
            self.LOGIN_URL, headers=TRACKER_HEADERS, timeout=self.timeout
        )
        if login_page.status_code != 200:
            login_load_error_msg = (
                f"Failed to retrieve load login page: {login_page.status_code}"
            )
            LOG.error(
                LOG.LOG_SOURCE.BE,
                login_load_error_msg,
            )
            raise TrackerError(login_load_error_msg)

        # Extract the token from the login page
        token = self.get_token(login_page.text)
        if not token:
            token_code_error_msg = "Failed to retrieve login token"
            LOG.error(
                LOG.LOG_SOURCE.BE,
                token_code_error_msg,
            )
            raise TrackerError(token_code_error_msg)

        # Prepare the payload with the extracted token
        payload = {
            "token": token,
            "username": username,
            "password": password,
            "keeploggedin": 1,
            "cinfo": "1920|1080|24|0",
            "submit": "login",
            "iplocked": 1,
        }

        # Post the login form
        login_response = self._session.post(
            self.LOGIN_URL, data=payload, headers=TRACKER_HEADERS, timeout=self.timeout
        )
        if login_response.status_code != 200:
            status_code_error_msg = f"Login failed: {login_response.status_code}"
            LOG.error(
                LOG.LOG_SOURCE.BE,
                status_code_error_msg,
            )
            raise TrackerError(status_code_error_msg)

        # Handle 2FA if required
        final_response = self.handle_2fa(login_response, totp)
        if final_response.text and "authkey=" in final_response.text:
            LOG.info(
                LOG.LOG_SOURCE.BE,
                "Successfully logged into MoreThanTV",
            )
            auth_token = self.get_auth_key(final_response.text)
            if auth_token:
                self._save_cookies()
            return auth_token
        else:
            auth_key_failed_msg = "Failed to get authentication token (login failure)"
            LOG.error(
                LOG.LOG_SOURCE.BE,
                auth_key_failed_msg,
            )
            raise TrackerError(auth_key_failed_msg)

    def handle_2fa(
        self, login_response: niquests.Response, totp: str | None
    ) -> niquests.Response:
        if login_response.url and "twofactor/login" in login_response.url:
            code_to_try = None
            tried_totp = False
            while True:
                if not tried_totp and totp:
                    code_to_try = pyotp.TOTP(totp).now()
                    tried_totp = True
                else:
                    got_code, code = ask_thread_safe_prompt(
                        "2FA", "Enter your 2FA code:"
                    )
                    if not got_code or not code:
                        raise TrackerError("2FA cancelled or no code entered")
                    code_to_try = code

                two_factor_payload = {
                    "token": self.get_token(login_response.text),
                    "code": str(code_to_try),
                    "submit": "login",
                }
                two_factor_response = self._session.post(
                    self.LOGIN_URL_2FA,
                    data=two_factor_payload,
                    headers=TRACKER_HEADERS,
                    timeout=self.timeout,
                )
                if two_factor_response.status_code == 200:
                    return two_factor_response
                else:
                    LOG.error(
                        LOG.LOG_SOURCE.BE,
                        f"2FA failed: {two_factor_response.reason} ({two_factor_response.status_code})",
                    )

        return login_response

    def _validate_session(self) -> str | None:
        """Perform a lightweight request to validate the session, if valid the required token is returned."""
        try:
            with self._session.get(self.UPLOAD_URL) as response:
                return self.get_auth_key(response.text)
        except niquests.RequestException:
            return None

    def _save_cookies(self) -> None:
        with open(self.cookie_path, "wb") as file:
            pickle.dump(self._session.cookies, file)
        LOG.debug(LOG.LOG_SOURCE.BE, f"MoreThanTV cookies saved: {self.cookie_path}")

    def _load_cookies(self) -> bool:
        if self.cookie_path.exists():
            with open(self.cookie_path, "rb") as file:
                cookies = pickle.load(file)
                self._session.cookies = cookies
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                f"MoreThanTV cookies loaded from {self.cookie_path}",
            )
            return True
        LOG.debug(LOG.LOG_SOURCE.BE, "MoreThanTV cookies not found")
        return False

    def upload(
        self,
        auth_token: str,
        torrent_file: Path,
        file_input: Path,
        tracker_title: str | None,
        nfo: str,
        group_desc: str | None,
        genre_ids: Sequence[TMDBGenreIDsMovies | TMDBGenreIDsSeries],
        media_mode: MediaMode,
        anonymous: bool,
        source_origin: MTVSourceOrigin,
    ) -> Path:
        data = {
            # "image": "",
            "title": self.generate_release_title(tracker_title)
            if tracker_title
            else self.generate_release_title(file_input.stem),
            "category": self._get_cat_id(torrent_file.name),
            "source": self._get_source_id(file_input),
            "desc": nfo,
            "groupDesc": group_desc,
            "ignoredupes": "1",
            "genre_tags": "---",
            "autocomplete_toggle": "on",
            "fontfont": "-1",
            "fontsize": "-1",
            "auth": auth_token,
            "anonymous": str(int(anonymous)),
            "submit": "true",
        }

        # update resolution
        get_resolution = VideoResolutionAnalyzer(self.mediainfo_obj).get_resolution()
        try:
            resolution = MTVResolutionIDs(get_resolution[:-1]).value
        except ValueError:
            resolution = MTVResolutionIDs.DEFAULT.value
        data["Resolution"] = resolution

        # update all tags
        tags = self.collect_tags(
            resolution=get_resolution,
            file_input=file_input,
            genre_ids=genre_ids,
            media_mode=media_mode,
        )
        if tags:
            data["taglist"] = " ".join(tags)

        # update source origin and update tags with source origin id
        get_source_origin = self._get_source_origin_id(source_origin)
        if get_source_origin:
            data["origin"] = get_source_origin[0]
            data["taglist"] = f"{data['taglist']} {get_source_origin[1]}"

        # open file in binary
        files = {}
        with open(torrent_file, "rb") as f:
            files["file_input"] = (torrent_file.name, f.read())

        # auto_fill = self._auto_fill(auth_token)
        # TODO: do some checks to see if things was auto filled correctly?

        LOG.debug(
            LOG.LOG_SOURCE.BE,
            f"\n#### UPLOAD PAYLOAD ####\n{data}\n#### UPLOAD PAYLOAD ####\n",
        )

        upload_page = self._session.post(
            self.UPLOAD_URL,
            data=data,
            files=files,
            headers=TRACKER_HEADERS,
            timeout=self.timeout,
        )

        LOG.debug(
            LOG.LOG_SOURCE.BE,
            f"\n#### DEBUG HTML OUTPUT ####\n{upload_page.text}\n#### DEBUG HTML OUTPUT ####\n",
        )

        # dupe detected
        if upload_page.text and re.search(
            "The torrent contained one or more possible dupes. Please check carefully!",
            upload_page.text,
        ):
            dupe_error_msg = "Duplicate torrent detected"
            LOG.error(LOG.LOG_SOURCE.BE, dupe_error_msg)
            raise TrackerError(dupe_error_msg)

        # success
        if (
            upload_page.url
            and re.search(r"torrents\.php\?id=", upload_page.url)
            or re.search(
                "Your torrent has been uploaded however", str(upload_page.text)
            )
        ):
            LOG.info(LOG.LOG_SOURCE.BE, "Successfully uploaded to MoreThanTV")
            return torrent_file

        # error :(
        else:
            # try to get error
            failure_str = None
            get_failure = (
                re.search(
                    r'(?s)<div id="messagebar.*?".+?<pre>(.+?)</pre>|<div id="messagebar.*?>.(.+?)</div>',
                    upload_page.text,
                    flags=re.MULTILINE,
                )
                if upload_page.text
                else None
            )
            if get_failure:
                failure_str = next(
                    (group for group in get_failure.groups() if group is not None), None
                )

            failed_error_msg = f"Failed to upload torrent: {failure_str if failure_str else upload_page.reason} ({upload_page.status_code})"
            LOG.error(LOG.LOG_SOURCE.BE, failed_error_msg)
            raise TrackerError(failed_error_msg)

    @staticmethod
    def generate_release_title(release_title: str) -> str:
        """Force release title to be in a format that MTV requires"""
        if " " in release_title:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                "Spaces found in MTV release title, automatically correcting.",
            )
            incoming_title = release_title
            release_title = re.sub(r"\s", ".", release_title)
            release_title = re.sub(r"\.{2,}", ".", release_title)
            LOG.info(
                LOG.LOG_SOURCE.BE,
                f"Spaces corrected in MTV release title ({incoming_title} -> {release_title}).",
            )
        return release_title

    @staticmethod
    def _get_cat_id(release_title: str) -> str:
        """
        default: 0,
        HD Episode: 3,
        HD Movies: 1,
        HD Season: 5,
        SD Episode: 4,
        SD Movies: 2,
        SD Season: 6,
        """
        category = MTVCategories.DEFAULT.value
        # normal
        if re.search(
            r"( |\.)(S[0-9]+)?E[0-9]+(-?E[0-9]+){0,2}?( |\.)",
            release_title,
            re.IGNORECASE,
        ):
            if re.search("7[0-9]{2}p|[1-2][0-9]{3}[pi]", release_title):
                category = MTVCategories.HD_EPISODE.value
            else:
                category = MTVCategories.SD_EPISODE.value
        # daily
        elif re.search(
            r"( |\.)(([0-9]{4}.[0-9]{2}.[0-9]{2})|([0-9]{2}.[0-9]{2}.[0-9]{4}))( |\.)",
            release_title,
            re.IGNORECASE,
        ):
            if re.search(r"7[0-9]{2}p|[1-2][0-9]{3}[pi]", release_title):
                category = MTVCategories.HD_EPISODE.value
            else:
                category = MTVCategories.SD_EPISODE.value
        # season
        elif re.search(r"( |\.)S[0-9]+( |\.)", release_title, re.IGNORECASE):
            if re.search(r"7[0-9]{2}p|[1-2][0-9]{3}[pi]", release_title):
                category = MTVCategories.HD_SEASON.value
            else:
                category = MTVCategories.SD_SEASON.value
        # movies
        else:
            if re.search(r"7[0-9]{2}p|[1-2][0-9]{3}[pi]", release_title):
                category = MTVCategories.HD_MOVIES.value
            else:
                category = MTVCategories.SD_MOVIES.value
        return str(category)

    @staticmethod
    def _get_source_id(file_input: Path) -> str:
        file_input_lowered = re.sub(r"\W", "", file_input.stem).lower()

        source_mapping = {
            "hdtv": MTVSourceIDs.HDTV,
            "sdtv": MTVSourceIDs.SDTV,
            "tvrip": MTVSourceIDs.TV_RIP,
            "dvdrip": MTVSourceIDs.DVD_RIP,
            "dvd": MTVSourceIDs.DVD,
            "vhs": MTVSourceIDs.VHS,
            "bluray": MTVSourceIDs.BLURAY,
            "bdrip": MTVSourceIDs.BDRIP,
            "webdl": MTVSourceIDs.WEBDL,
            "webrip": MTVSourceIDs.WEBRIP,
            "mixed": MTVSourceIDs.MIXED,
        }

        for key, value in source_mapping.items():
            if key in file_input_lowered:
                return str(value.value)

        return ""

    @staticmethod
    def _get_source_origin_id(source_origin: MTVSourceOrigin) -> tuple[str, str] | None:
        id_map = {
            MTVSourceOrigin.UNDEFINED: None,
            MTVSourceOrigin.INTERNAL: ("1", "internal"),
            MTVSourceOrigin.SCENE: ("2", "scene"),
            MTVSourceOrigin.P2P: ("3", "p2p"),
            MTVSourceOrigin.USER: ("4", "user"),
            MTVSourceOrigin.MIXED: ("5", "mixed"),
            MTVSourceOrigin.OTHER: ("6", "other"),
        }
        return id_map[MTVSourceOrigin(source_origin)]

    def collect_tags(
        self,
        resolution: str,
        file_input: Path,
        genre_ids: Sequence[TMDBGenreIDsMovies | TMDBGenreIDsSeries],
        media_mode: MediaMode,
    ) -> set:
        tags = self.find_audio_tags(self.mediainfo_obj)
        tags.update(self.find_genre_tags(genre_ids))
        tags.update(self.find_resolution_tags(resolution))
        tags.update(self.find_type_source_tags(file_input))
        tags.update(self.find_type_tags(media_mode, resolution))
        tags.update(self.find_video_codec_tags(self.mediainfo_obj))
        tags.update(self.find_release_group_tags(file_input))
        tags.update(self.has_subtitles_tags(self.mediainfo_obj))

        return tags

    @staticmethod
    def find_audio_tags(mediainfo_obj: MediaInfo) -> set:
        format_to_tag = {
            AudioFormats.AAC.value: MTVAudioTags.AAC.value,
            AudioFormats.AC3.value: MTVAudioTags.DD.value,
            AudioFormats.EAC3.value: MTVAudioTags.DDP.value,
            AudioFormats.FLAC.value: MTVAudioTags.FLAC.value,
            AudioFormats.PCM.value: MTVAudioTags.LPCM.value,
            AudioFormats.OPUS.value: MTVAudioTags.OPUS.value,
            AudioFormats.DTS.value: MTVAudioTags.DTS.value,
            AudioFormats.DTS_XLL.value: MTVAudioTags.DTS_HD.value,
            AudioFormats.DTS_XLL_X.value: MTVAudioTags.DTS_X.value,
            AudioFormats.TRUEHD.value: MTVAudioTags.TRUEHD.value,
        }

        audio_tags = set()

        for track in mediainfo_obj.audio_tracks:
            audio_format = track.format or ""
            audio_object = track.format_profile or ""

            # add tag based on the format
            if audio_format in format_to_tag:
                audio_tags.add(format_to_tag[audio_format])

            # mpeg layers
            if audio_format == AudioFormats.MPEG_AUDIO.value:
                if "Layer 2" in audio_object:
                    audio_tags.add(MTVAudioTags.MP2.value)
                elif "Layer 3" in audio_object:
                    audio_tags.add(MTVAudioTags.MP3.value)

            # check for Atmos in the audio object
            if "Atmos" in audio_object:
                audio_tags.add(MTVAudioTags.ATMOS.value)

        return audio_tags

    @staticmethod
    def find_genre_tags(
        genre_ids: Sequence[TMDBGenreIDsMovies | TMDBGenreIDsSeries],
    ) -> set:
        genres = set()
        for item in genre_ids:
            if item not in (TMDBGenreIDsMovies.UNDEFINED, TMDBGenreIDsSeries.UNDEFINED):
                name = str(item.name).replace("_", ".").lower()
                genres.add(name)
        return genres

    @staticmethod
    def find_resolution_tags(resolution: str) -> set:
        res_set = set()
        res_set.add(resolution)
        if resolution in ("2160p", "4320p"):
            res_set.add("uhd")
        elif resolution in ("720p", "1080p"):
            res_set.add("hd")
        return res_set

    @staticmethod
    def find_type_source_tags(file_input: Path) -> set:
        type_source = set()
        stem_lowered = file_input.stem.lower()
        for item in ("remux", "webdl", "webrip", "hdtv", "bluray", "dvd", "hddvd"):
            if item in stem_lowered:
                type_source.add(item)
        return type_source

    @staticmethod
    def find_type_tags(media_mode: MediaMode, resolution: str) -> set:
        if media_mode == MediaMode.MOVIES:
            return MTVUploader.find_movies_tags(resolution)
        elif media_mode == MediaMode.SERIES:
            return MTVUploader.find_movies_tags(resolution)

    @staticmethod
    def find_movies_tags(resolution: str) -> set:
        movies = set()
        if resolution in ("720p", "1080p", "2160p", "4320p"):
            movies.add("hd.movie")
        return movies

    @staticmethod
    def find_series_tags(resolution: str) -> set:
        # TODO: add a check for episodes vs seasons
        # # Episodes
        # if meta['sd'] == 1:
        #     tags.extend(['episode.release', 'sd.episode'])
        # else:
        #     tags.extend(['episode.release', 'hd.episode'])

        # # Seasons
        # if meta['sd'] == 1:
        #     tags.append('sd.season')
        # else:
        #     tags.append('hd.season')
        series = set()
        # if resolution in ("2160p", "4320p"):
        #     series.add("uhd.movie")
        # elif resolution in ("720p", "1080p"):
        #     series.add("hd.movie")
        return series

    @staticmethod
    def find_video_codec_tags(mediainfo_obj: MediaInfo) -> set:
        v_codecs = set()
        for track in mediainfo_obj.video_tracks:
            codec = track.format
            if codec:
                if codec == "AVC":
                    codec = "h264"
                elif codec == "HEVC":
                    codec = "h265"
                v_codecs.add(str(codec).lower())
        return v_codecs

    @staticmethod
    def find_release_group_tags(file_input: Path) -> set:
        # TODO: add different logic for movies vs series
        release_group_set = set()
        release_group = guessit.guessit(file_input).get("release_group", "")
        if release_group:
            release_group_set.add(f"{release_group.lower()}.release")
        return release_group_set

    @staticmethod
    def has_subtitles_tags(mediainfo_obj: MediaInfo) -> set:
        has_subtitles = set()
        try:
            gen_track = mediainfo_obj.general_tracks[0].count_of_text_streams
            if gen_track and int(gen_track) > 0:
                has_subtitles.add("subtitles")
        except (IndexError, ValueError):
            return has_subtitles
        return has_subtitles

    @staticmethod
    def get_token(html: str | None) -> str | None:
        if html:
            soup = BeautifulSoup(html, features="lxml")
            input_token = soup.find("input", {"name": "token"})
            if isinstance(input_token, bs4Tag):
                value = input_token.get("value")
                return value if isinstance(value, str) else None
        return None

    @staticmethod
    def get_auth_key(html: str | None) -> str | None:
        auth_key = re.search(r"var authkey = \"([0-9a-z]+)", html if html else "")
        return auth_key.group().split('"')[1] if auth_key else None


class MTVSearch:
    def __init__(
        self,
        api_key: str,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search(
        self,
        title: str,
        imdb_id: str | None = None,
        tmdb_id: str | None = None,
        tvdb_id: str | None = None,
        clean_title: bool | None = None,
    ) -> list[TrackerSearchResult]:
        params = {"t": "search", "apikey": self.api_key, "q": title}
        if imdb_id:
            params["imdbid"] = imdb_id
        if tmdb_id:
            params["tmdbid"] = tmdb_id
        if tvdb_id:
            params["tvdbid"] = tvdb_id

        if clean_title:
            cleaned_title = unidecode(title)
            cleaned_title = (
                cleaned_title.replace("'", "").replace("&", "and").replace("’", "")
            )
            cleaned_title = re.sub(r"\W", ".", cleaned_title)
            cleaned_title = re.sub(r"\.{2,}", ".", cleaned_title)
            params["q"] = cleaned_title

        LOG.info(LOG.LOG_SOURCE.BE, f"Searching MoreThanTV for title: {params['q']}")

        try:
            response = niquests.get(
                MTVUploader.SEARCH_URL,
                params=params,
                headers=TRACKER_HEADERS,
                timeout=self.timeout,
            )
            if response.ok and response.status_code == 200:
                results = self.handle_xml(response.text)
                LOG.info(LOG.LOG_SOURCE.BE, f"Total results found: {len(results)}")
                LOG.debug(LOG.LOG_SOURCE.BE, f"Total results found: {results}")
                return results
            else:
                raise TrackerError(
                    f"Failed to reach server ({response.reason} - {response.status_code})"
                )
        except niquests.RequestException as e:
            raise TrackerError(f"Failed to reach server: {e}")
        except Exception as unhandled_error:
            raise TrackerError(f"Failed to parse XML: {unhandled_error}")

    def handle_xml(self, xml_str: str | None) -> list[TrackerSearchResult]:
        results = []
        if not xml_str:
            return results
        tree = ET.ElementTree(ET.fromstring(xml_str))
        root = tree.getroot()

        nso_namespaces = {"ns0": "http://torznab.com/schemas/2015/feed"}

        if root:
            channel = root.find("channel")
            if channel:
                for item in channel.findall("item"):
                    tracker_result = TrackerSearchResult(
                        name=self._get_value(item, "title"),
                        url=self._get_value(item, "guid"),
                        download_link=self._get_value(item, "link"),
                        release_size=self.int_cast_fb(self._get_value(item, "size")),
                        created_at=self._get_date(item, "pubDate"),
                    )

                    for attr in item.findall("ns0:attr", namespaces=nso_namespaces):
                        name = attr.get("name")
                        value = attr.get("value")
                        if name and value:
                            if name == "seeders":
                                tracker_result.seeders = self.int_cast_fb(value)
                            elif name == "leechers":
                                tracker_result.leechers = self.int_cast_fb(value)
                            elif name == "grabs":
                                tracker_result.grabs = self.int_cast_fb(value)
                            elif name == "files":
                                tracker_result.files = self.int_cast_fb(value)
                            elif "imdb" in name:
                                tracker_result.imdb_id = f"tt{value}"
                            elif name == "poster":
                                tracker_result.uploader = value
                            elif name == "infohash":
                                tracker_result.info_hash = value

                    results.append(tracker_result)
        return results

    @staticmethod
    def _get_value(item: ET.Element, value: str) -> str | None:
        check = item.find(value)
        if check is not None:
            return check.text

    @staticmethod
    def int_cast_fb(i: Any) -> int | Any:
        if not i:
            return None
        try:
            return int(i)
        except ValueError:
            return i

    @staticmethod
    def _get_date(item: ET.Element, value: str) -> datetime | None:
        check = item.find(value)
        if check is not None and check.text:
            return datetime.strptime(check.text, "%a, %d %b %Y %H:%M:%S %z")
