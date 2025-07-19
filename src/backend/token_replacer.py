from collections.abc import Iterable
from pathlib import Path
import re
from typing import Any, Type

from auto_qpf import ChapterGenerator
from auto_qpf.enums import ChapterType
from babelfish.language import Language as BabelLanguage
from guessit import guessit
from iso639 import Lang
from iso639.exceptions import InvalidLanguageValue
from pymediainfo import MediaInfo, Track
import unidecode

from src.backend.tokens import FileToken, NfoToken, TokenData, TokenType, Tokens
from src.backend.utils.audio_channels import ParseAudioChannels
from src.backend.utils.audio_codecs import AudioCodecs
from src.backend.utils.language import (
    get_full_language_str,
    get_language_mi,
    get_language_str,
)
from src.backend.utils.media_info_utils import (
    MinimalMediaInfo,
    calculate_avg_video_bit_rate,
)
from src.backend.utils.rename_normalizations import EDITION_INFO
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.backend.utils.video_codecs import VideoCodecs
from src.backend.utils.working_dir import RUNTIME_DIR
from src.enums.token_replacer import ColonReplace, SharedWithType, UnfilledTokenRemoval
from src.exceptions import GuessitParsingError, InvalidTokenError
from src.nf_jinja2 import Jinja2TemplateEngine
from src.payloads.media_search import MediaSearchPayload
from src.version import __version__, program_name, program_url


class TokenReplacer:
    FILENAME_ATTRIBUTES = ("remux", "hybrid", "re_release")

    __slots__ = (
        "media_input",
        "token_string",
        "source_file",
        "jinja_engine",
        "colon_replace",
        "guess_name",
        "guess_source_name",
        "guessit_language",
        "media_search_obj",
        "media_info_obj",
        "source_file_mi_obj",
        "flatten",
        "file_name_mode",
        "token_type",
        "unfilled_token_mode",
        "releasers_name",
        "screen_shots",
        "release_notes",
        "dummy_screen_shots",
        "parse_filename_attributes",
        "override_tokens",
        "user_tokens",
        "edition_override",
        "frame_size_override",
        "movie_clean_title_rules",
        "override_title_rules",
        "mi_video_dynamic_range",
        "token_data",
    )

    def __init__(
        self,
        media_input: Path,
        token_string: str,
        source_file: Path | None = None,
        jinja_engine: Jinja2TemplateEngine | None = None,
        colon_replace: ColonReplace = ColonReplace.REPLACE_WITH_DASH,
        media_search_obj: MediaSearchPayload | None = None,
        media_info_obj: MediaInfo | None = None,
        source_file_mi_obj: MediaInfo | None = None,
        flatten: bool | None = False,
        file_name_mode: bool = True,
        token_type: Iterable[TokenType] | Type[TokenType] | None = None,
        unfilled_token_mode: UnfilledTokenRemoval = UnfilledTokenRemoval.KEEP,
        releasers_name: str | None = "",
        override_tokens: dict[str, str] | None = None,
        user_tokens: dict[str, str] | None = None,
        edition_override: str | None = None,
        frame_size_override: str | None = None,
        movie_clean_title_rules: list[tuple[str, str]] | None = None,
        override_title_rules: list[tuple[str, str]] | None = None,
        mi_video_dynamic_range: dict[str, Any] | None = None,
        screen_shots: str | None = "",
        release_notes: str | None = "",
        dummy_screen_shots: bool = False,
        parse_filename_attributes: bool = False,
    ):
        """
        Takes an input string with tokens and outputs a new string with formatted data based
        on the tokens used.

        Args:
            media_input (Path): File path.
            token_string (str): Token string.
            source_file (Optional[Path]): File path for 'source' file.
            jinja_engine (Optional[Jinja2TemplateEngine]): JinjaEngine class.
            colon_replace (ColonReplace): What to do with colons.
            media_search_obj (Optional[MediaSearchPayload], optional): Payload.
            media_info_obj (Optional[MediaInfo.parse], optional): MediaInfo object.
            source_file_mi_obj (Optional[MediaInfo.parse], optional): MediaInfo object.
            flatten (Optional[bool]): Rather or not to flatten the data to a single string
            file_name_mode: bool: Returned string will be in 'x.x.ext' format (ignored if not using flatten).
              with no newlines or extra white space (used for filenames). `colon_replace` is ignored
              when this is used.
            token_type (Optional[Iterable[TokenType]]): Specific `TokenType`'s to use, or None for all.
            unfilled_token_mode (UnfilledTokenRemoval): What to do with unused tokens.
            eg. (TokenType, TokenType).
            releasers_name (Optional[str]): Releasers name.
            override_tokens (Optional[dict[str, str]]): Override tokens with a supplied value regardless of logic.
            user_tokens (Optional[dict[str, str]]): User tokens (must be prefixed with usr_).
            edition_override (Optional[str]): Edition override.
            frame_size_override (Optional[str]): Frame size override.
            movie_clean_title_rules: (Optional[list[tuple[str, str]]]: Rules to iterate and replace for 'movie_clean_title' token.
            override_title_rules: (Optional[list[tuple[str, str]]]: Rules to iterate and replace for final title output.
            mi_video_dynamic_range: (Optional[dict[str, Any]]: Rules to control formatting of video dynamic range.
            screen_shots (Optional[str]): Screenshots.
            release_notes (Optional[str]): Release notes.
            dummy_screen_shots (Optional[bool]): If set to True will generate some dummy screenshot data for the
              screenshot token (This overrides screen_shots if used, so only use when you have screenshot data).
            parse_filename_attributes (Optional[bool]): If set to True attributes REMUX, HYBRID, PROPER, and REPACK will be
              detected from the filename.
        """
        self.media_input = Path(media_input)
        self.jinja_engine = jinja_engine
        self.source_file = Path(source_file) if source_file else None
        self.guess_name = guessit(self.media_input.name)
        self.guess_source_name: dict[str, Any] | None = None
        if self.source_file:
            self.guess_source_name = guessit(self.source_file.name)
        self.guessit_language = self._guessit_language()
        self.token_string = token_string
        self.colon_replace = ColonReplace(colon_replace)
        self.media_search_obj = (
            media_search_obj if media_search_obj else MediaSearchPayload()
        )
        self.media_info_obj = media_info_obj
        self.source_file_mi_obj = source_file_mi_obj
        self.flatten = flatten
        self.file_name_mode = file_name_mode
        self.token_type = token_type
        self.unfilled_token_mode = UnfilledTokenRemoval(unfilled_token_mode)
        self.releasers_name = releasers_name
        self.edition_override = edition_override
        self.frame_size_override = frame_size_override
        self.movie_clean_title_rules = movie_clean_title_rules
        self.override_title_rules = override_title_rules
        self.mi_video_dynamic_range = mi_video_dynamic_range
        self.screen_shots = screen_shots
        self.release_notes = release_notes
        self.dummy_screen_shots = dummy_screen_shots
        self.parse_filename_attributes = parse_filename_attributes
        self.override_tokens = override_tokens
        self.user_tokens = user_tokens
        self.token_data = Tokens.generate_token_dataclass(token_type)

        if not self.flatten and not self.jinja_engine:
            raise AttributeError(
                "You must pass in 'jinja_engine' if you are not flattening your output string"
            )

    def get_output(self) -> str | None:
        """
        if flatten:
            str: Formatted str (filename).
        else:
            str: Formatted str (multi-line template).

        Returns:
            Optional[str]: Formatted string.
        """
        if self.flatten:
            tokens = self._parse_user_input()
            filled_tokens = {
                token.token: self._get_token_value(token) for token in tokens
            }
            self._update_token_data(filled_tokens)
            return self._format_token_string(filled_tokens)
        else:
            filled_tokens = {
                token.token: self._get_token_value(token)
                for token in self.generate_all_tokens()
            }
            self._update_token_data(filled_tokens)
            if not self.jinja_engine:
                raise AttributeError("Could not detect 'jinja_engine'")
            jinja_output = self.jinja_engine.render_from_str(
                self.token_string,
                filled_tokens | self.user_tokens if self.user_tokens else filled_tokens,
            )
            return jinja_output

    def _update_token_data(self, filled_tokens: dict):
        for key, value in filled_tokens.items():
            setattr(self.token_data, key, value)

    def _parse_user_input(self):
        """Extract valid tokens from user input string, ignoring unknown tokens."""
        valid_tokens = Tokens.get_tokens()

        matches = re.finditer(
            r"{(?::opt=(.*?):)?(.*?)(?::opt=(.*?):)?}", self.token_string
        )
        parsed_tokens: set[TokenData] = set()
        for match in matches:
            pre = match.group(1) if match.group(1) else ""
            token_str = match.group(2)
            post = match.group(3) if match.group(3) else ""
            # accept built-in or user tokens only
            if token_str in valid_tokens or (
                token_str.startswith("usr_")
                and self.user_tokens
                and token_str in self.user_tokens
            ):
                string_token_data = TokenData(
                    pre, token_str, f"{{{token_str}}}", post, match.group()
                )
                parsed_tokens.add(string_token_data)

        return parsed_tokens

    def generate_all_tokens(self) -> set[TokenData]:
        valid_tokens = Tokens.get_tokens()
        all_tokens = set()

        for token in valid_tokens:
            token_data = TokenData(
                pre_token="",
                token=token,
                bracket_token=f"{{{token}}}",
                post_token="",
                full_match=f"{{{token}}}",
            )
            all_tokens.add(token_data)

        return all_tokens

    def _get_token_value(self, token_data: TokenData) -> str:
        # handle user tokens
        if (
            self.user_tokens
            and token_data.token
            and token_data.token.startswith("usr_")
        ):
            return self._optional_user_input(
                self.user_tokens.get(token_data.token, ""), token_data
            )

        # handle over ride tokens
        if self.override_tokens and token_data.token in self.override_tokens:
            return self._optional_user_input(
                self.override_tokens[token_data.token], token_data
            )

        # default token handling
        if not self.token_type:
            get_media_token = self._media_tokens(token_data)
            if get_media_token:
                return get_media_token
            get_nfo_token = self._nfo_tokens(token_data)
            if get_nfo_token:
                return get_nfo_token
        else:
            token_types = (
                self.token_type
                if isinstance(self.token_type, (list, set, tuple))
                else [self.token_type]
            )
            for token_type in token_types:
                if token_type == FileToken:
                    if (
                        not self.parse_filename_attributes
                        and token_data.token in self.FILENAME_ATTRIBUTES
                    ):
                        continue
                    get_token = self._media_tokens(token_data)
                    if get_token:
                        return get_token
                elif token_type == NfoToken:
                    get_token = self._nfo_tokens(token_data)
                    if get_token:
                        return get_token
        return ""

    def _media_tokens(self, token_data: TokenData) -> str:
        if token_data.bracket_token == Tokens.EDITION.token:
            return self._edition(token_data)

        if token_data.bracket_token == Tokens.FRAME_SIZE.token:
            return self._frame_size(token_data)

        if token_data.bracket_token == Tokens.HYBRID.token:
            return self._hybrid(token_data)

        if token_data.bracket_token == Tokens.LOCALIZATION.token:
            return self._localization(token_data)

        if token_data.bracket_token == Tokens.MI_AUDIO_BITRATE.token:
            return self._mi_audio_bitrate(token_data, False)

        if token_data.bracket_token == Tokens.MI_AUDIO_BITRATE_FORMATTED.token:
            return self._mi_audio_bitrate(token_data, True)

        elif token_data.bracket_token == Tokens.MI_AUDIO_CHANNEL_S.token:
            return self._mi_audio_channel_s(token_data, True)

        elif token_data.bracket_token == Tokens.MI_AUDIO_CHANNEL_S_I.token:
            return self._mi_audio_channel_s(token_data, False)

        elif token_data.bracket_token == Tokens.MI_AUDIO_CHANNEL_S_LAYOUT.token:
            return self._mi_audio_channel_s_layout(token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_CODEC.token:
            return self._mi_audio_codec(token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_COMMERCIAL_NAME.token:
            return self._mi_audio_commercial_name(token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_COMPRESSION.token:
            return self._mi_audio_compression(token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_FORMAT_INFO.token:
            return self._mi_audio_format_info(token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_LANGUAGE_1_FULL.token:
            return self._mi_audio_language_1_full(token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_LANGUAGE_1_ISO_639_1.token:
            return self._mi_audio_language_1_iso_639_x(1, token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_LANGUAGE_1_ISO_639_2.token:
            return self._mi_audio_language_1_iso_639_x(2, token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_LANGUAGE_2_ISO_639_1.token:
            return self._mi_audio_language_2_all_iso_639_x(1, False, token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_LANGUAGE_2_ISO_639_2.token:
            return self._mi_audio_language_2_all_iso_639_x(2, False, token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_LANGUAGE_ALL_ISO_639_1.token:
            return self._mi_audio_language_2_all_iso_639_x(1, True, token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_LANGUAGE_ALL_ISO_639_2.token:
            return self._mi_audio_language_2_all_iso_639_x(2, True, token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_LANGUAGE_DUAL.token:
            return self._mi_audio_language_dual(token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_LANGUAGE_MULTI.token:
            return self._mi_audio_language_multi(token_data)

        elif token_data.bracket_token == Tokens.MI_AUDIO_SAMPLE_RATE.token:
            return self._mi_audio_sample_rate(token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_3D.token:
            return self._3d(token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_BIT_DEPTH_SPACE.token:
            return self._mi_video_bit_depth_x(False, token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_BIT_DEPTH_DASH.token:
            return self._mi_video_bit_depth_x(True, token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_CODEC.token:
            return self._mi_video_codec(token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_DYNAMIC_RANGE.token:
            return self._mi_video_dynamic_range(token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_DYNAMIC_RANGE_TYPE.token:
            return self._mi_video_dynamic_range_type(token_data)

        elif (
            token_data.bracket_token == Tokens.MI_VIDEO_DYNAMIC_RANGE_TYPE_INC_SDR.token
        ):
            return self._mi_video_dynamic_range_type(token_data, include_sdr=True)

        elif (
            token_data.bracket_token
            == Tokens.MI_VIDEO_DYNAMIC_RANGE_TYPE_INC_SDR_OVER_1080.token
        ):
            return self._mi_video_dynamic_range_type(
                token_data, include_sdr=True, uhd_only=True
            )

        elif token_data.bracket_token == Tokens.MI_VIDEO_HEIGHT.token:
            return self._mi_video_height(token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_LANGUAGE_FULL.token:
            return self._mi_video_language_full(token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_LANGUAGE_ISO_639_1.token:
            return self._mi_video_language_iso_639_x(1, token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_LANGUAGE_ISO_639_2.token:
            return self._mi_video_language_iso_639_x(2, token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_WIDTH.token:
            return self._mi_video_width(token_data)

        elif token_data.bracket_token == Tokens.MOVIE_TITLE.token:
            return self._movie_title(token_data)

        elif token_data.bracket_token == Tokens.MOVIE_CLEAN_TITLE.token:
            return self._movie_clean_title(token_data)

        elif token_data.bracket_token == Tokens.MOVIE_EXACT_TITLE.token:
            return self._movie_exact_title(token_data)

        elif token_data.bracket_token == Tokens.MOVIE_IMDB_ID.token:
            return self._movie_imdb_id(token_data)

        elif token_data.bracket_token == Tokens.MOVIE_TMDB_ID.token:
            return self._movie_tmdb_id(token_data)

        elif token_data.bracket_token == Tokens.MOVIE_TVDB_ID.token:
            return self._movie_tvdb_id(token_data)

        elif token_data.bracket_token == Tokens.MOVIE_MAL_ID.token:
            return self._movie_mal_id(token_data)

        elif token_data.bracket_token == Tokens.ORIGINAL_FILENAME.token:
            return self._original_filename(token_data)

        elif token_data.bracket_token == Tokens.RELEASE_GROUP.token:
            return self._release_group(token_data)

        elif token_data.bracket_token == Tokens.RELEASERS_NAME.token:
            return self._releasers_name(token_data)

        elif token_data.bracket_token == Tokens.RELEASE_YEAR.token:
            return self._release_year(token_data)

        elif token_data.bracket_token == Tokens.RELEASE_YEAR_PARENTHESES.token:
            return self._release_year_parentheses(token_data)

        elif token_data.bracket_token == Tokens.RESOLUTION.token:
            return self._resolution(token_data)

        elif token_data.bracket_token == Tokens.REMUX.token:
            return self._remux(token_data)

        elif token_data.bracket_token == Tokens.RE_RELEASE.token:
            return self._re_release(token_data)

        elif token_data.bracket_token == Tokens.SOURCE.token:
            return self._source(token_data)

        return ""

    def _nfo_tokens(self, token_data: TokenData) -> str:
        if token_data.bracket_token == Tokens.CHAPTER_TYPE.token:
            return self._chapter_type(token_data)

        elif token_data.bracket_token == Tokens.FORMAT_PROFILE.token:
            return self._format_profile(token_data)

        elif token_data.bracket_token == Tokens.MEDIA_FILE.token:
            return self._media_file(token_data)

        elif token_data.bracket_token == Tokens.MEDIA_FILE_NO_EXT.token:
            return self._media_file_no_ext(token_data)

        elif token_data.bracket_token == Tokens.MOVIE_FULL_TITLE.token:
            return self._movie_full_title(token_data)

        elif token_data.bracket_token == Tokens.SOURCE_FILE.token:
            return self._source_file(token_data)

        elif token_data.bracket_token == Tokens.SOURCE_FILE_NO_EXT.token:
            return self._source_file_no_ext(token_data)

        elif token_data.bracket_token == Tokens.MEDIA_INFO.token:
            return self._media_info(token_data)

        elif token_data.bracket_token == Tokens.MEDIA_INFO_SHORT.token:
            return self._media_info_short(token_data)

        elif token_data.bracket_token == Tokens.MI_VIDEO_BIT_RATE.token:
            return self._mi_video_bit_rate(token_data, False)

        elif token_data.bracket_token == Tokens.MI_VIDEO_BIT_RATE_NUM_ONLY.token:
            return self._mi_video_bit_rate(token_data, True)

        elif token_data.bracket_token == Tokens.REPACK.token:
            return self._repack(token_data)

        elif token_data.bracket_token == Tokens.REPACK_N.token:
            return self._repack_n(token_data)

        elif token_data.bracket_token == Tokens.REPACK_REASON.token:
            return self._repack_reason(token_data)

        elif token_data.bracket_token == Tokens.SCREEN_SHOTS.token:
            return self._screen_shots(token_data)

        elif token_data.bracket_token == Tokens.RELEASE_NOTES.token:
            return self._release_notes(token_data)

        elif token_data.bracket_token == Tokens.FILE_SIZE_BYTES.token:
            return self._file_size_bytes(token_data)

        elif token_data.bracket_token == Tokens.FILE_SIZE.token:
            return self._file_size(token_data)

        elif token_data.bracket_token == Tokens.DURATION_MILLISECONDS.token:
            return self._duration_milliseconds(token_data)

        elif token_data.bracket_token == Tokens.DURATION_SHORT.token:
            return self._duration_other(token_data, 0)

        elif token_data.bracket_token == Tokens.DURATION_LONG.token:
            return self._duration_other(token_data, 1)

        elif token_data.bracket_token == Tokens.DURATION_DETAILED.token:
            return self._duration_other(token_data, 3)

        elif token_data.bracket_token == Tokens.VIDEO_WIDTH.token:
            return self._video_width(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_HEIGHT.token:
            return self._video_height(token_data)

        elif token_data.bracket_token == Tokens.ASPECT_RATIO.token:
            return self._aspect_ratio(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_FRAME_RATE.token:
            return self._video_frame_rate(token_data)

        elif token_data.bracket_token == Tokens.SUBTITLE_S.token:
            return self._subtitle_s(token_data)

        elif token_data.bracket_token == Tokens.PROPER.token:
            return self._proper(token_data)

        elif token_data.bracket_token == Tokens.PROPER_N.token:
            return self._proper_n(token_data)

        elif token_data.bracket_token == Tokens.PROPER_REASON.token:
            return self._proper_reason(token_data)

        elif token_data.bracket_token == Tokens.PROGRAM_INFO.token:
            return self._program_info(token_data)

        elif token_data.bracket_token == Tokens.SHARED_WITH.token:
            return self._shared_with(token_data, SharedWithType.BASIC)

        elif token_data.bracket_token == Tokens.SHARED_WITH_BBCODE.token:
            return self._shared_with(token_data, SharedWithType.BBCODE)

        elif token_data.bracket_token == Tokens.SHARED_WITH_HTML.token:
            return self._shared_with(token_data, SharedWithType.HTML)

        return ""

    def _format_token_string(self, filled_tokens) -> str | None:
        try:
            formatted_title = self.token_string
            for key, value in filled_tokens.items():
                if key != "movie_clean_title":
                    formatted_title = formatted_title.replace(f"{{{key}}}", value)
                    formatted_title = self._colon_replace(
                        self.colon_replace, formatted_title
                    )

            # apply specific formatting for 'movie_clean_title'
            if "movie_clean_title" in formatted_title and filled_tokens:
                formatted_title = formatted_title.replace(
                    "{movie_clean_title}", filled_tokens["movie_clean_title"]
                )

            # remove unfilled tokens if needed
            formatted_title = self._remove_unfilled_tokens(formatted_title)

            # apply final formatting
            # if filename mode
            if self.file_name_mode:
                formatted_file_name = re.sub(r"\s{1,}", ".", formatted_title)
                formatted_file_name = re.sub(r"\.{2,}", ".", formatted_file_name)
                formatted_file_name = re.sub(r":\.", ".", formatted_file_name)
                formatted_file_name = re.sub(r"\.-\.|\.-|-\.", "-", formatted_file_name)
                return formatted_file_name + self.media_input.suffix
            # if title mode
            else:
                formatted_title = re.sub(r"\s{1,}", " ", formatted_title)
                formatted_title = re.sub(r"\.{2,}", ".", formatted_title)
                if self.override_title_rules:
                    for replace, replace_with in self.override_title_rules:
                        if replace_with == "[unidecode]":
                            formatted_title = unidecode.unidecode(formatted_title)
                        else:
                            replace_with = replace_with.replace("[remove]", "").replace(
                                "[space]", " "
                            )
                            formatted_title = re.sub(
                                rf"{replace}", rf"{replace_with}", formatted_title
                            )
                return formatted_title
        except (ValueError, KeyError, IndexError):
            return None

    def _remove_unfilled_tokens(self, formatted_title: str) -> str:
        if self.unfilled_token_mode == UnfilledTokenRemoval.KEEP:
            return formatted_title
        elif self.unfilled_token_mode == UnfilledTokenRemoval.TOKEN_ONLY:
            return re.sub(r"{[^{}]*}", "", formatted_title, flags=re.MULTILINE)
        elif self.unfilled_token_mode == UnfilledTokenRemoval.ENTIRE_LINE:
            return re.sub(r"(\b.*?{.+}*?\n)", "", formatted_title, flags=re.MULTILINE)
        else:
            raise InvalidTokenError("Invalid 'unfilled_token_mode'")

    def _edition(self, token_data: TokenData) -> str:
        if self.edition_override:
            return self._optional_user_input(self.edition_override, token_data)

        def collect_editions(source, key):
            """Helper function to collect edition data from a source."""
            values = source.get(key, [])
            return values if isinstance(values, list) else [values]

        # ensure we have unique editions
        normalized_edition_set = set()

        # search the entire filename for edition patterns
        filename = self.media_input.stem.lower()
        for rename_normalize in EDITION_INFO:
            for regex_str in rename_normalize.re_gex:
                if re.search(regex_str, filename, flags=re.I):
                    normalized_edition_set.add(rename_normalize.normalized)
                    break  # only add once per edition type

        # also process any editions from guess_name['edition']
        edition_set = set(collect_editions(self.guess_name, "edition"))
        for item in edition_set:
            item_lowered = str(item).lower()
            if "imax" in item_lowered:
                continue
            matched = False
            for rename_normalize in EDITION_INFO:
                for regex_str in rename_normalize.re_gex:
                    if re.search(regex_str, item_lowered, flags=re.I):
                        normalized_edition_set.add(rename_normalize.normalized)
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                normalized_edition_set.add(item)

        return self._optional_user_input(" ".join(normalized_edition_set), token_data)

    def _frame_size(self, token_data: TokenData) -> str:
        if self.frame_size_override:
            return self._optional_user_input(self.frame_size_override, token_data)

        def collect_editions(source, key):
            """Helper function to collect edition data from a source."""
            values = source.get(key, [])
            return values if isinstance(values, list) else [values]

        # ensure we have unique editions
        edition_set = set()

        # collect editions from `guess_name`
        edition_set.update(collect_editions(self.guess_name, "edition"))

        # collect editions from `guess_source_name` if it exists
        if self.guess_source_name:
            edition_set.update(collect_editions(self.guess_source_name, "edition"))

        # check for "Open Matte" in `other` fields of `guess_name` and `guess_source_name`
        for source in [self.guess_name, self.guess_source_name]:
            if source:
                other = source.get("other", [])
                items = other if isinstance(other, list) else [other]
                if "Open Matte" in items:
                    edition_set.add("Open Matte")
                    break

        # normalize some editions
        if edition_set:
            normalized_edition_set = set()
            for item in edition_set:
                item_lowered = str(item).lower()
                if "imax" in item_lowered:
                    normalized_edition_set.add("IMAX")
                    break
            edition_set = normalized_edition_set

        # convert the set back to a string, joining with spaces
        return self._optional_user_input(" ".join(edition_set), token_data)

    def _hybrid(self, token_data: TokenData) -> str:
        return self._optional_user_input(
            "HYBRID" if "hybrid" in self.media_input.stem.lower() else "", token_data
        )

    def _localization(self, token_data: TokenData) -> str:
        localization = ""
        lowered_input = self.media_input.stem.lower()
        if "subbed" in lowered_input:
            localization = "Subbed"
        elif "Dubbed" in lowered_input:
            localization = "Dubbed"
        return self._optional_user_input(localization, token_data)

    def _mi_audio_bitrate(self, token_data: TokenData, formatted: bool) -> str:
        bitrate = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            a_track = self.media_info_obj.audio_tracks[0]
            if a_track and not formatted:
                bitrate = str(a_track.bit_rate) if a_track.bit_rate else ""
            elif a_track and formatted:
                bitrate = a_track.other_bit_rate[0] if a_track.other_bit_rate else ""

        return self._optional_user_input(bitrate, token_data)

    def _mi_audio_channel_s(
        self, token_data: TokenData, convert_to_layout: bool
    ) -> str:
        # TODO: might need to handle multiple audio tracks instead of just 0
        audio_channel_s = self.guess_name.get("audio_channels", "")
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_audio_channels = self.media_info_obj.audio_tracks[0].channel_s
            if mi_audio_channels:
                if convert_to_layout:
                    audio_channel_s = ParseAudioChannels.get_channel_layout(
                        self.media_info_obj.audio_tracks[0]
                    )
                else:
                    audio_channel_s = str(mi_audio_channels)

        return self._optional_user_input(audio_channel_s, token_data)

    def _mi_audio_channel_s_layout(self, token_data: TokenData) -> str:
        layout = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_channel_layout = self.media_info_obj.audio_tracks[0].channel_layout
            if mi_channel_layout:
                layout = mi_channel_layout

        return self._optional_user_input(layout, token_data)

    def _mi_audio_codec(self, token_data: TokenData) -> str:
        audio_codec = self.guess_name.get("audio_codec", "")
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            audio_codecs = AudioCodecs()
            # TODO: remove hard coded json path later?
            audio_convention_path = Path(
                RUNTIME_DIR / "config" / "audio_conventions" / "default.json"
            )
            audio_codec = audio_codecs.get_codec(
                self.media_info_obj.audio_tracks[0],
                audio_convention_path,
            )

        return self._optional_user_input(audio_codec, token_data)

    def _mi_audio_commercial_name(self, token_data: TokenData) -> str:
        commercial_name = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_commercial_name = self.media_info_obj.audio_tracks[0].commercial_name
            if mi_commercial_name:
                commercial_name = mi_commercial_name

        return self._optional_user_input(commercial_name, token_data)

    def _mi_audio_compression(self, token_data: TokenData) -> str:
        compression = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_compression = self.media_info_obj.audio_tracks[0].compression_mode
            if mi_compression:
                compression = mi_compression

        return self._optional_user_input(compression, token_data)

    def _mi_audio_format_info(self, token_data: TokenData) -> str:
        format_info = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_format_info = self.media_info_obj.audio_tracks[0].channel_s
            if mi_format_info:
                format_info = mi_format_info

        return self._optional_user_input(format_info, token_data)

    def _mi_audio_language_1_full(self, token_data: TokenData) -> str:
        language = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            detect_language_code = get_language_mi(self.media_info_obj.audio_tracks[0])
            if detect_language_code:
                detect_language = get_full_language_str(detect_language_code)
                if detect_language:
                    language = detect_language

        return self._optional_user_input(language, token_data)

    def _mi_audio_language_1_iso_639_x(
        self, char_code: int, token_data: TokenData
    ) -> str:
        language = self.guessit_language
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            detect_language = get_language_mi(
                self.media_info_obj.audio_tracks[0], char_code
            )
            if detect_language:
                language = detect_language

        return self._optional_user_input(language, token_data)

    def _mi_audio_language_2_all_iso_639_x(
        self, char_code: int, all_languages: bool, token_data: TokenData
    ) -> str:
        language = ""
        guess_lang = self.guessit_language
        if isinstance(guess_lang, list):
            language_s = {
                lang for x in guess_lang if (lang := get_language_str(x, char_code))
            }
            if language_s:
                if len(language_s) == 1:
                    language = next(iter(language_s))
                elif len(language_s) >= 2:
                    if not all_languages:
                        language = "+".join(list(language_s)[:2])
                    else:
                        language = "+".join(language_s)
        else:
            language = get_language_str(guess_lang, char_code)

        if self.media_info_obj and self.media_info_obj.audio_tracks:
            language_list = {
                lang
                for track in self.media_info_obj.audio_tracks
                if (lang := get_language_mi(track, char_code))
            }

            if language_list:
                if len(language_list) == 1:
                    language = next(iter(language_list))
                else:
                    if not all_languages:
                        language = "+".join(list(language_list)[:2])
                    else:
                        language = "+".join(language_list)

        return self._optional_user_input(language, token_data)

    def _mi_audio_language_dual(self, token_data: TokenData) -> str:
        dual = ""
        other_attributes = self.guess_name.get("other")

        if other_attributes and "Dual Audio" in other_attributes:
            dual = "Dual Audio"

        if self.media_info_obj and self.media_info_obj.audio_tracks:
            language_set = {
                get_language_mi(track)
                for track in self.media_info_obj.audio_tracks
                if get_language_mi(track)
            }

            if len(language_set) >= 2:
                dual = "Dual Audio"

        return self._optional_user_input(dual, token_data)

    def _mi_audio_language_multi(self, token_data: TokenData) -> str:
        multi = ""
        language = self.guessit_language
        if isinstance(language, list):
            for lang in language:
                if lang == "mul":
                    multi = "Multi"
                    break
        else:
            if language == "mul":
                multi = "Multi"

        if self.media_info_obj and self.media_info_obj.audio_tracks:
            language_set = {
                get_language_mi(track)
                for track in self.media_info_obj.audio_tracks
                if get_language_mi(track)
            }
            if len(language_set) >= 3:
                multi = "Multi"

        return self._optional_user_input(multi, token_data)

    def _mi_audio_sample_rate(self, token_data: TokenData) -> str:
        sample_rate = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_sample_rate = self.media_info_obj.audio_tracks[0].other_sampling_rate
            if mi_sample_rate:
                sample_rate = mi_sample_rate[0]

        return self._optional_user_input(sample_rate, token_data)

    def _3d(self, token_data: TokenData) -> str:
        three_dimension = (
            "3D"
            if re.match(
                r"(?<=\b[12]\d{3}\b).*\b(3d|sbs|half[ .-]ou|half[ .-]sbs)\b|\b(BluRay3D)\b|\b(BD3D)\b",
                self.media_input.name,
            )
            else ""
        )

        if not three_dimension:
            if self.media_info_obj and self.media_info_obj.video_tracks:
                try:
                    if "Stereo" in self.media_info_obj.video_tracks[0].format_profile:
                        three_dimension = "3D"
                    elif int(self.media_info_obj.video_tracks[0].multiview_count) >= 2:
                        three_dimension = "3D"
                except (AttributeError, ValueError, TypeError):
                    three_dimension = ""

        return self._optional_user_input(three_dimension, token_data)

    def _mi_video_bit_depth_x(self, dash: bool, token_data: TokenData) -> str:
        color_depth = self.guess_name.get("color_depth", "")

        if self.media_info_obj and self.media_info_obj.video_tracks:
            mi_depth = self.media_info_obj.video_tracks[0].bit_depth
            if mi_depth:
                color_depth = f"{mi_depth}-Bit"

        if dash:
            color_depth = color_depth.replace("b", "B")
        else:
            color_depth = color_depth.replace("-", " ").title()

        return self._optional_user_input(color_depth, token_data)

    def _mi_video_codec(self, token_data: TokenData) -> str:
        codec = VideoCodecs().get_codec(self.media_info_obj, self.guess_name)
        return self._optional_user_input(codec, token_data)

    def _mi_video_dynamic_range(self, token_data: TokenData) -> str:
        hdr_string = ""

        if (
            self.mi_video_dynamic_range
            and self.media_info_obj
            and self.media_info_obj.video_tracks
        ):

            def normalize(s: str) -> str:
                return s.replace(" ", "").lower()

            fallback_names = {
                "SDR": "SDR",
                "PQ": "PQ",
                "HLG": "HLG",
                "HDR10": "HDR10",
                "HDR10+": "HDR10+",
                "DV": "DV",
                "DV HDR10": "DV HDR10",
                "DV HDR10+": "DV HDR10+",
            }

            # resolution
            resolution = int(self._detect_resolution(self.media_info_obj, True))
            res_map = {720: "720p", 1080: "1080p", 2160: "2160p"}
            res_key = next(
                (v for k, v in res_map.items() if abs(resolution - k) < 100), None
            )

            if not res_key or not self.mi_video_dynamic_range["resolutions"].get(
                res_key, False
            ):
                return self._optional_user_input("", token_data)

            # get data from dict
            enabled_hdr_types = [
                k for k, v in self.mi_video_dynamic_range["hdr_types"].items() if v
            ]
            custom_strings = self.mi_video_dynamic_range.get("custom_strings", {})
            enabled_hdr_types_sorted = sorted(enabled_hdr_types, key=len, reverse=True)
            norm_enabled_types = {normalize(k): k for k in enabled_hdr_types_sorted}

            # extract HDR format and transfer characteristics
            hdr_format = ""
            transfer_characteristics = ""
            try:
                hdr_format = self.media_info_obj.video_tracks[0].other_hdr_format[0]
            except (AttributeError, IndexError, TypeError):
                pass
            try:
                transfer_characteristics = self.media_info_obj.video_tracks[
                    0
                ].transfer_characteristics
            except (AttributeError, IndexError, TypeError):
                pass

            # detect mi candidates
            mi_candidates = []
            if hdr_format:
                if "Dolby Vision" in hdr_format and "HDR10+" in hdr_format:
                    mi_candidates.append("DV HDR10+")
                if (
                    "Dolby Vision" in hdr_format
                    and "HDR10" in hdr_format
                    and "HDR10+" not in hdr_format
                ):
                    mi_candidates.append("DV HDR10")
                if (
                    "Dolby Vision" in hdr_format
                    and "HDR10" not in hdr_format
                    and "HDR10+" not in hdr_format
                ):
                    mi_candidates.append("DV")
                if "HDR10+" in hdr_format:
                    mi_candidates.append("HDR10+")
                if "HDR10" in hdr_format and "HDR10+" not in hdr_format:
                    mi_candidates.append("HDR10")

            # PQ/HLG from transfer characteristics
            for t in ("PQ", "HLG"):
                if transfer_characteristics == t:
                    mi_candidates.append(t)

            # try to match the most specific enabled HDR type
            for candidate in mi_candidates:
                norm_candidate = normalize(candidate)
                if norm_candidate in norm_enabled_types:
                    hdr_type = norm_enabled_types[norm_candidate]
                    custom = custom_strings.get(hdr_type, "").strip()
                    hdr_string = custom or fallback_names.get(hdr_type, hdr_type)
                    break

            # fallback: if nothing matched, check if SDR is enabled and present in candidates
            if (
                not hdr_string
                and "SDR" in enabled_hdr_types
                and (
                    any(normalize(c) == "sdr" for c in mi_candidates)
                    or not mi_candidates
                )
            ):
                custom = custom_strings.get("SDR", "").strip()
                hdr_string = custom or fallback_names.get("SDR", "SDR")

            # append PQ/HLG if enabled, matches transfer_characteristics, and not already present
            for t in ("PQ", "HLG"):
                if (
                    transfer_characteristics == t
                    and t in enabled_hdr_types
                    and normalize(t) not in normalize(str(hdr_string))
                ):
                    custom = custom_strings.get(t, "").strip()
                    to_add = custom or fallback_names.get(t, t)
                    if hdr_string:
                        hdr_string += f" {to_add}"
                    else:
                        hdr_string = to_add

        return self._optional_user_input(hdr_string, token_data)

    def _mi_video_dynamic_range_type(
        self, token_data: TokenData, include_sdr: bool = False, uhd_only: bool = False
    ) -> str:
        if uhd_only:
            if int(self._detect_resolution(self.media_info_obj, True)) <= 1080:
                return ""

        dv = "DV" if "Dolby Vision" in self.guess_name.get("other", "") else ""
        hdr10 = "HDR" if "HDR10" in self.guess_name.get("other", "") else ""
        hdr10_plus = "HDR10Plus" if "HDR10+" in self.guess_name.get("other", "") else ""
        hlg = ""
        pq = ""

        if self.media_info_obj and self.media_info_obj.video_tracks:
            try:
                hdr_format = self.media_info_obj.video_tracks[0].other_hdr_format[0]
                if hdr_format:
                    dv = "DV" if "Dolby Vision" in hdr_format else ""
                    if dv and "dvhe.05" not in hdr_format:
                        dv = f"{dv} HDR"
                    hdr10_plus = "HD10Plus" if "HDR10+" in hdr_format else ""
                    hdr10 = "HDR" if "HDR10" in hdr_format else ""
            except (AttributeError, IndexError, TypeError):
                dv = hdr10 = hdr10_plus = ""

            transfer_characteristics = self.media_info_obj.video_tracks[
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
            else:
                if include_sdr:
                    dynamic_range_type = "SDR"
                else:
                    dynamic_range_type = ""

        return self._optional_user_input(dynamic_range_type, token_data)

    def _mi_video_height(self, token_data: TokenData) -> str:
        height = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            track = self.media_info_obj.video_tracks[0]
            height = str(track.height) if track.height else ""

        return self._optional_user_input(height, token_data)

    def _mi_video_language_full(self, token_data: TokenData) -> str:
        language = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            detect_language_code = get_language_mi(self.media_info_obj.video_tracks[0])
            if detect_language_code:
                detect_language = get_full_language_str(detect_language_code)
                if detect_language:
                    language = detect_language

        return self._optional_user_input(language, token_data)

    def _mi_video_language_iso_639_x(
        self, char_code: int, token_data: TokenData
    ) -> str:
        detect_language = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            track = self.media_info_obj.video_tracks[0]
            detect_language = get_language_mi(track, char_code)

        return self._optional_user_input(detect_language, token_data)

    def _mi_video_width(self, token_data: TokenData) -> str:
        width = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            track = self.media_info_obj.video_tracks[0]
            width = str(track.width) if track.width else ""

        return self._optional_user_input(width, token_data)

    def _movie_title(self, token_data: TokenData) -> str:
        title = (
            self.media_search_obj.title
            if self.media_search_obj.title
            else self.guess_name.get("title", "")
        )
        if title:
            title = unidecode.unidecode(title)
            title = re.sub(r'[:\\/<>\?*"|]', " ", title)
            title = re.sub(r"\s{2,}", " ", title)
        return self._optional_user_input(title, token_data)

    def _movie_clean_title(self, token_data: TokenData) -> str:
        title = (
            self.media_search_obj.title
            if self.media_search_obj.title
            else self.guess_name.get("title", "")
        )
        if title and self.movie_clean_title_rules:
            for replace, replace_with in self.movie_clean_title_rules:
                if replace_with == "[unidecode]":
                    title = unidecode.unidecode(title)
                else:
                    replace_with = replace_with.replace("[remove]", "").replace(
                        "[space]", " "
                    )
                    title = re.sub(rf"{replace}", rf"{replace_with}", title)
        return self._optional_user_input(title, token_data)

    def _movie_exact_title(self, token_data: TokenData) -> str:
        title = (
            self.media_search_obj.title
            if self.media_search_obj.title
            else self.guess_name.get("title", "")
        )
        return self._optional_user_input(title, token_data)

    def _movie_imdb_id(self, token_data: TokenData) -> str:
        imdb_id = self.media_search_obj.imdb_id if self.media_search_obj.imdb_id else ""
        return self._optional_user_input(imdb_id, token_data)

    def _movie_tmdb_id(self, token_data: TokenData) -> str:
        tmdb_id = self.media_search_obj.tmdb_id if self.media_search_obj.tmdb_id else ""
        return self._optional_user_input(tmdb_id, token_data)

    def _movie_tvdb_id(self, token_data: TokenData) -> str:
        tvdb_id = self.media_search_obj.tvdb_id if self.media_search_obj.tvdb_id else ""
        return self._optional_user_input(tvdb_id, token_data)

    def _movie_mal_id(self, token_data: TokenData) -> str:
        mal_id = self.media_search_obj.mal_id if self.media_search_obj.mal_id else ""
        return self._optional_user_input(mal_id, token_data)

    def _original_filename(self, token_data: TokenData) -> str:
        return self._optional_user_input(self.media_input.stem, token_data)

    def _release_group(self, token_data: TokenData) -> str:
        release_group = self.guess_name.get("release_group", "")
        return self._optional_user_input(release_group, token_data)

    def _releasers_name(self, token_data: TokenData) -> str:
        releasers_name = "Anonymous"
        if self.releasers_name:
            releasers_name = self.releasers_name
        return self._optional_user_input(releasers_name, token_data)

    def _release_year(self, token_data: TokenData) -> str:
        year = (
            str(self.media_search_obj.year)
            if self.media_search_obj.year
            else self.guess_name.get("year", "")
        )
        return self._optional_user_input(year, token_data)

    def _release_year_parentheses(self, token_data: TokenData) -> str:
        year_value = (
            self.media_search_obj.year
            if self.media_search_obj.year
            else self.guess_name.get("year", "")
        )
        if year_value:
            year_value = f"({year_value})"
        return self._optional_user_input(str(year_value), token_data)

    def _resolution(self, token_data: TokenData) -> str:
        return self._optional_user_input(
            self._detect_resolution(self.media_info_obj, False), token_data
        )

    def _remux(self, token_data: TokenData) -> str:
        return self._optional_user_input(
            "REMUX" if "remux" in self.media_input.stem.lower() else "", token_data
        )

    def _re_release(self, token_data: TokenData) -> str:
        search_re_release = re.findall(
            r"\b(PROPER\d*|REPACK\d*)\b", self.media_input.name, flags=re.IGNORECASE
        )
        re_release_str = " ".join((str(x).upper() for x in search_re_release))

        return self._optional_user_input(re_release_str, token_data)

    def _source(self, token_data: TokenData) -> str:
        source = self.guess_name.get("source", "")

        # if we have access to the source file let's instead parse that
        if self.guess_source_name:
            check_source_file = self.guess_source_name.get("source", "")
            if check_source_file:
                source = check_source_file

        if "Ultra Blu-ray" in source:
            source = "UHD BluRay"
        elif "Blu-ray" in source:
            source = "BluRay"
        elif "DVD" in source:
            source = "DVD"
        elif "HDTV" in source:
            source = "HDTV"
        elif "Web" in source:
            source = "Web"

        if not source or source == "BluRay":
            track = None
            resolution_value = 0
            if self.source_file_mi_obj and self.source_file_mi_obj.video_tracks:
                track = self.source_file_mi_obj.video_tracks[0]
                resolution_value = int(
                    self._detect_resolution(self.source_file_mi_obj, True)
                )
            elif not track and self.media_info_obj and self.media_info_obj.video_tracks:
                track = self.media_info_obj.video_tracks[0]
                resolution_value = int(
                    self._detect_resolution(self.media_info_obj, True)
                )

            if track and resolution_value:
                video_format = track.format
                dynamic_range = (
                    track.other_hdr_format[0] if track.other_hdr_format else ""
                )
                if resolution_value <= 1080:
                    if video_format == "AVC" or (
                        video_format == "HEVC" and "HDR" not in dynamic_range
                    ):
                        source = "BluRay"
                    elif video_format == "HEVC" and "HDR" in dynamic_range:
                        source = "UHD BluRay"
                elif resolution_value > 1080 and video_format == "HEVC":
                    source = "UHD BluRay"

        # TODO: this will need some work potentially, we'll need to attempt
        # to detect some specific things if possible to fine tune this result
        # or maybe take input from the front end
        return self._optional_user_input(source, token_data)

    def _chapter_type(self, token_data: TokenData) -> str:
        chapter_type = ""
        if self.media_info_obj and self.media_info_obj.menu_tracks:
            chapter_info = ChapterGenerator()
            chapter_dict = chapter_info._get_media_info_obj_chapters(
                self.media_info_obj
            )
            if chapter_dict:
                chapter_tuple = chapter_info._determine_chapter_type(chapter_dict)
                if ChapterType(chapter_tuple[0]) == ChapterType.NAMED:
                    chapter_type = "Named"
                elif ChapterType(chapter_tuple[0]) == ChapterType.NUMBERED:
                    if len(chapter_tuple) >= 4:
                        # Convert to int to remove leading 0's
                        chapter_type = f"Numbered ({int(chapter_tuple[2])} - {int(chapter_tuple[3])})"
                elif ChapterType(chapter_tuple[0]) == ChapterType.TAGGED:
                    chapter_type = "Tagged"
        return self._optional_user_input(chapter_type, token_data)

    def _format_profile(self, token_data: TokenData) -> str:
        detected_profile = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            mi_profile = self.media_info_obj.video_tracks[0].format_profile
            if mi_profile:
                detected_profile = mi_profile
        return self._optional_user_input(detected_profile, token_data)

    def _media_file(self, token_data: TokenData) -> str:
        return self._optional_user_input(self.media_input.name, token_data)

    def _media_file_no_ext(self, token_data: TokenData) -> str:
        return self._optional_user_input(self.media_input.stem, token_data)

    def _movie_full_title(self, token_data: TokenData) -> str:
        title = (
            self.media_search_obj.title
            if self.media_search_obj.title
            else self.guess_name.get("title", "")
        )
        if title:
            title = re.sub(r"\s{2,}", " ", title)
        return self._optional_user_input(title, token_data)

    def _source_file(self, token_data: TokenData) -> str:
        return self._optional_user_input(
            self.source_file.name if self.source_file else "", token_data
        )

    def _source_file_no_ext(self, token_data: TokenData) -> str:
        return self._optional_user_input(
            self.source_file.stem if self.source_file else "", token_data
        )

    def _media_info(self, token_data: TokenData) -> str:
        media_info_str = ""
        if self.media_input:
            media_info_str = MinimalMediaInfo(self.media_input).get_full_mi_str(True)
        return self._optional_user_input(media_info_str, token_data)

    def _media_info_short(self, token_data: TokenData) -> str:
        media_info_str = ""
        if self.media_input:
            media_info_str = MinimalMediaInfo(self.media_input).get_minimal_mi_str()
        return self._optional_user_input(media_info_str, token_data)

    def _mi_video_bit_rate(self, token_data: TokenData, num_only: bool) -> str:
        mi_bit_rate = calculate_avg_video_bit_rate(self.media_info_obj)
        if mi_bit_rate:
            if num_only:
                mi_bit_rate = str(mi_bit_rate)
            else:
                mi_bit_rate = f"{mi_bit_rate} kbps"
        return self._optional_user_input(str(mi_bit_rate), token_data)

    def _repack(self, token_data: TokenData) -> str:
        repack = ""
        if "repack" in self.media_input.stem.lower():
            repack = "REPACK"
        elif self.jinja_engine and self.jinja_engine.environment.globals.get(
            "repack_n"
        ):
            repack = "REPACK"
        return self._optional_user_input(repack, token_data)

    def _repack_n(self, token_data: TokenData) -> str:
        repack = ""
        detect_repack = re.search(
            r"(repack\d*)", self.media_input.stem, flags=re.IGNORECASE
        )
        if detect_repack:
            repack = detect_repack.group(1)

        if self.jinja_engine:
            detect_jinja_repack_n = self.jinja_engine.environment.globals.get(
                "repack_n", ""
            )
            if detect_jinja_repack_n:
                detect_repack = re.search(
                    r"(repack\d*)", detect_jinja_repack_n, flags=re.IGNORECASE
                )
                if detect_repack:
                    repack = detect_repack.group(1)

        return self._optional_user_input(repack.upper(), token_data)

    def _repack_reason(self, token_data: TokenData) -> str:
        repack_reason = ""
        if self.jinja_engine:
            repack_reason = self.jinja_engine.environment.globals.get(
                "repack_reason", ""
            )
        return self._optional_user_input(repack_reason, token_data)

    def _screen_shots(self, token_data: TokenData) -> str:
        if self.dummy_screen_shots:
            return (
                "#### DUMMY SCREENSHOTS #### \n"
                "(Real screenshots will be generated on the process page in the appropriate format for the tracker)"
                "\nScreen1 Screen2\nScreen3 Screen4\n#### DUMMY SCREENSHOTS ####"
            )
        return self._optional_user_input(self.screen_shots, token_data)

    def _release_notes(self, token_data: TokenData) -> str:
        return self._optional_user_input(
            self.release_notes if self.release_notes else "", token_data
        )

    def _file_size_bytes(self, token_data: TokenData) -> str:
        file_size = ""
        if self.media_info_obj:
            get_file_size = self.media_info_obj.general_tracks[0].file_size
            if get_file_size:
                file_size = str(get_file_size)
        return self._optional_user_input(file_size, token_data)

    def _file_size(self, token_data: TokenData) -> str:
        file_size = ""
        if self.media_info_obj:
            get_file_size = self.media_info_obj.general_tracks[0].other_file_size
            if get_file_size:
                file_size = get_file_size[0]
        return self._optional_user_input(file_size, token_data)

    def _duration_milliseconds(self, token_data: TokenData) -> str:
        duration_str = ""
        if self.media_info_obj:
            try:
                get_duration = self.media_info_obj.general_tracks[0].duration
                if get_duration:
                    duration_str = str(get_duration)
            except IndexError:
                pass
        return self._optional_user_input(duration_str, token_data)

    def _duration_other(self, token_data: TokenData, idx: int) -> str:
        duration_str = ""
        if self.media_info_obj:
            try:
                get_duration = self.media_info_obj.general_tracks[0].other_duration
                if get_duration:
                    duration_str = get_duration[idx]
            except IndexError:
                pass
        return self._optional_user_input(duration_str, token_data)

    def _video_width(self, token_data: TokenData) -> str:
        width = ""
        try:
            if self.media_info_obj and self.media_info_obj.video_tracks:
                get_width = self.media_info_obj.video_tracks[0].width
                if get_width:
                    width = str(get_width)
        except IndexError:
            pass
        return self._optional_user_input(width, token_data)

    def _video_height(self, token_data: TokenData) -> str:
        height = ""
        try:
            if self.media_info_obj and self.media_info_obj.video_tracks:
                get_height = self.media_info_obj.video_tracks[0].height
                if get_height:
                    height = str(get_height)
        except IndexError:
            pass
        return self._optional_user_input(height, token_data)

    def _aspect_ratio(self, token_data: TokenData) -> str:
        aspect_ratio = ""
        try:
            if self.media_info_obj and self.media_info_obj.video_tracks:
                ar = self.media_info_obj.video_tracks[0].other_display_aspect_ratio[0]
                if ar:
                    aspect_ratio = str(ar)
        except IndexError:
            pass
        return self._optional_user_input(aspect_ratio, token_data)

    def _video_frame_rate(self, token_data: TokenData) -> str:
        fps = ""
        try:
            if self.media_info_obj and self.media_info_obj.video_tracks:
                get_fps = self.media_info_obj.video_tracks[0].frame_rate
                if get_fps:
                    fps = str(get_fps)
        except IndexError:
            pass
        return self._optional_user_input(fps, token_data)

    def _subtitle_s(self, token_data: TokenData) -> str:
        subtitles = ""
        try:
            if self.media_info_obj and self.media_info_obj.text_tracks:
                get_subtitles = self.nfo_subtitle_str(self.media_info_obj)
                if get_subtitles:
                    subtitles = get_subtitles
        except IndexError:
            pass
        return self._optional_user_input(subtitles, token_data)

    def _proper(self, token_data: TokenData) -> str:
        proper = ""
        if "proper" in self.media_input.stem.lower():
            proper = "PROPER"
        elif self.jinja_engine and self.jinja_engine.environment.globals.get(
            "proper_n"
        ):
            proper = "PROPER"
        return self._optional_user_input(proper, token_data)

    def _proper_n(self, token_data: TokenData) -> str:
        proper = ""
        detect_proper = re.search(
            r"(proper\d*)", self.media_input.stem, flags=re.IGNORECASE
        )
        if detect_proper:
            proper = detect_proper.group(1)

        if self.jinja_engine:
            detect_jinja_proper_n = self.jinja_engine.environment.globals.get(
                "proper_n", ""
            )
            if detect_jinja_proper_n:
                detect_proper = re.search(
                    r"(proper\d*)", detect_jinja_proper_n, flags=re.IGNORECASE
                )
                if detect_proper:
                    proper = detect_proper.group(1)

        return self._optional_user_input(proper.upper(), token_data)

    def _proper_reason(self, token_data: TokenData) -> str:
        proper_reason = ""
        if self.jinja_engine:
            proper_reason = self.jinja_engine.environment.globals.get(
                "proper_reason", ""
            )
        return self._optional_user_input(proper_reason, token_data)

    def _program_info(self, token_data: TokenData) -> str:
        return self._optional_user_input(f"{program_name} v{__version__}", token_data)

    def _shared_with(
        self, token_data: TokenData, shared_by_type: SharedWithType
    ) -> str:
        output = ""
        if shared_by_type is SharedWithType.BASIC:
            output = f"Shared with {program_name} v{__version__}"
        elif shared_by_type is SharedWithType.BBCODE:
            output = (
                f"Shared with [url={program_url}]{program_name} v{__version__}[/url]"
            )
        elif shared_by_type is SharedWithType.HTML:
            output = (
                f'Shared with <a href="{program_url}">{program_name} v{__version__}</a'
            )
        return self._optional_user_input(output, token_data)

    def _guessit_language(self) -> str:
        guess_lang = self.guess_name.get("language")
        if not guess_lang:
            return ""

        if (
            isinstance(guess_lang, list)
            and guess_lang
            and isinstance(guess_lang[0], BabelLanguage)
        ):
            babel_instance = guess_lang[0]
        elif isinstance(guess_lang, BabelLanguage):
            babel_instance = guess_lang
        elif isinstance(guess_lang, str):
            return guess_lang.upper()
        else:
            raise GuessitParsingError(
                f"Cannot accept an instance type of {type(guess_lang)}"
            )

        if hasattr(babel_instance, "alpha2"):
            return babel_instance.alpha2.upper()
        if hasattr(babel_instance, "alpha3"):
            return babel_instance.alpha3.upper()
        if hasattr(babel_instance, "name"):
            return str(babel_instance.name)

        raise GuessitParsingError(
            "Failed to determine language from BabelLanguage instance"
        )

    def _optional_user_input(self, token_str: str | None, token_data: TokenData) -> str:
        if token_str:
            pre = token_data.pre_token
            post = token_data.post_token
            token_str = f"{pre}{token_str}{post}"

        # strip optional strings from user token
        if token_data.full_match and token_data.bracket_token:
            self.token_string = self.token_string.replace(
                token_data.full_match, token_data.bracket_token
            )

        return token_str if token_str else ""

    def _detect_resolution(self, mi_obj: MediaInfo | None, remove_scan: bool) -> str:
        resolution = self.guess_name.get("screen_size", "")

        if mi_obj:
            detect_resolution = VideoResolutionAnalyzer(mi_obj).get_resolution(
                remove_scan
            )
            if detect_resolution:
                resolution = detect_resolution

        return resolution

    def get_language(self, media_track: Track) -> str | None:
        if media_track.language:
            try:
                return Lang(media_track.language).name
            except InvalidLanguageValue:
                if media_track.other_language:
                    for track in media_track.other_language:
                        try:
                            return Lang(track).name
                        except InvalidLanguageValue:
                            try:
                                return Lang(track.split(" ")[0]).name
                            except InvalidLanguageValue:
                                continue
        return None

    def nfo_subtitle_str(self, parsed_file: MediaInfo) -> str:
        subtitles = parsed_file.text_tracks
        forced_srt_sub = []
        included_srt_language_s = []
        included_image_based_sub_language_s = []

        for subtitle in subtitles:
            sub_format = subtitle.format
            if sub_format:
                sub_format_lowered = sub_format.lower()
                extract_language = self.get_language(subtitle)

                if sub_format_lowered == "utf-8":
                    title = subtitle.title
                    forced_flag = subtitle.forced
                    if title and forced_flag:
                        lowered_title = title.lower()
                        if "forced" in lowered_title or forced_flag == "Yes":
                            if extract_language:
                                forced_srt_sub.append(extract_language)
                        else:
                            if extract_language:
                                included_srt_language_s.append(extract_language)
                    elif not title and forced_flag:
                        if forced_flag == "Yes":
                            if extract_language:
                                forced_srt_sub.append(extract_language)
                        else:
                            if extract_language:
                                included_srt_language_s.append(extract_language)
                    else:
                        if extract_language:
                            forced_srt_sub.append(extract_language)

                elif sub_format_lowered in {"pgs", "vobsub"}:
                    if extract_language:
                        included_image_based_sub_language_s.append(extract_language)

        final_results = ", ".join(
            sorted(
                list(
                    set(
                        forced_srt_sub
                        + included_srt_language_s
                        + included_image_based_sub_language_s
                    )
                )
            )
        )

        return final_results if final_results else ""

    @staticmethod
    def _colon_replace(colon_replace: ColonReplace, media_str: str) -> str:
        if colon_replace == ColonReplace.KEEP:
            return media_str
        elif colon_replace == ColonReplace.DELETE:
            return media_str.replace(":", "")
        elif colon_replace == ColonReplace.REPLACE_WITH_DASH:
            return media_str.replace(":", "-")
        elif colon_replace == ColonReplace.REPLACE_WITH_SPACE_DASH:
            return media_str.replace(":", " -")
        elif colon_replace == ColonReplace.REPLACE_WITH_SPACE_DASH_SPACE:
            return media_str.replace(":", " - ")
