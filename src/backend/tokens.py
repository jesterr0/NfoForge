from collections.abc import Iterable
from dataclasses import field, make_dataclass, asdict
from typing import NamedTuple, Type, Any


MOVIE_CLEAN_TITLE_REPLACE_DEFAULTS = [
    (r"", r"[unidecode]"),
    (r"&", r"and"),
    (r"/", r"\\"),
    (r"'", r"[remove]"),
    # remove commas within numbers (50,000 -> 50000)
    (r"(?<=\d),(?=\d)", r"[remove]"),
    # replace commas after words with a period
    (r"(?<=\w),(?=\s\w)", r"[space]"),
    # replace space dash space with nothing
    (r"\s*-\s*", r"."),
    (
        r"(?<=\s|\w)(,|<|>|\/|\\|;|:|'|\"\"|\||`|~|!|\?|@|\$|%|\^|\*|-|_|=)(?=\s)|"
        r"('|:|\?|,)(?=(?:(?:s|m)\s)|\s|$)|"
        r"(\(|\)|\[|\]|\{|\})",
        r"[space]",
    ),
    (r"\s{2,}", r"[space]"),
]


class TokenData(NamedTuple):
    """Holds the data for tokens"""

    pre_token: str | None
    token: str | None
    bracket_token: str | None
    post_token: str | None
    full_match: str | None


class TokenType(NamedTuple):
    token: str
    description: str


class FileToken(TokenType):
    pass


class NfoToken(TokenType):
    pass


class Tokens:
    __slots__ = ()

    # File Tokens
    EDITION = FileToken("{edition}", "Edition")
    FRAME_SIZE = FileToken("{frame_size}", "Frame size (IMAX/Open Matte)")
    MI_AUDIO_BITRATE = FileToken("{mi_audio_bitrate}", "Audio bitrate (640000)")
    MI_AUDIO_BITRATE_FORMATTED = FileToken(
        "{mi_audio_bitrate_formatted}", "Audio bitrate formatted (640 kb/s)"
    )
    MI_AUDIO_CHANNEL_S = FileToken("{mi_audio_channel_s}", "Audio channels (5.1)")
    MI_AUDIO_CHANNEL_S_I = FileToken("{mi_audio_channel_s_i}", "Audio channels (6)")
    MI_AUDIO_CODEC = FileToken("{mi_audio_codec}", "Audio codec")
    MI_AUDIO_LANGUAGE_1_FULL = FileToken(
        "{mi_audio_language_1_full}", "Audio language (first track 'English')"
    )
    MI_AUDIO_LANGUAGE_1_ISO_639_1 = FileToken(
        "{mi_audio_language_1_iso_639_1}", "Audio language (first track 'EN')"
    )
    MI_AUDIO_LANGUAGE_1_ISO_639_2 = FileToken(
        "{mi_audio_language_1_iso_639_2}", "Audio language (first track 'ENG')"
    )
    MI_AUDIO_LANGUAGE_2_ISO_639_1 = FileToken(
        "{mi_audio_language_2_iso_639_1}", "Audio language (first two tracks EN+ES)"
    )
    MI_AUDIO_LANGUAGE_2_ISO_639_2 = FileToken(
        "{mi_audio_language_2_iso_639_2}", "Audio languages (first two tracks ENG+SPA)"
    )
    MI_AUDIO_LANGUAGE_ALL_ISO_639_1 = FileToken(
        "{mi_audio_language_all_iso_639_1}",
        "All audio languages (all tracks EN+ES+etc..)",
    )
    MI_AUDIO_LANGUAGE_ALL_ISO_639_2 = FileToken(
        "{mi_audio_language_all_iso_639_2}",
        "All audio languages (all tracks ENG+SPA+etc..)",
    )
    MI_AUDIO_LANGUAGE_DUAL = FileToken(
        "{mi_audio_language_dual}",
        "Audio language ('Dual Audio' will be returned if there are 2 or more tracks with unique languages)",
    )
    MI_AUDIO_LANGUAGE_MULTI = FileToken(
        "{mi_audio_language_multi}",
        "Audio languages ('Multi' will be returned if there are 3 or more tracks with unique languages)",
    )
    MI_AUDIO_SAMPLE_RATE = FileToken(
        "{mi_audio_sample_rate}", "Audio sample rate (48.0 kHz)"
    )
    MI_VIDEO_3D = FileToken("{mi_video_3d}", "Video 3D")
    MI_VIDEO_BIT_DEPTH_SPACE = FileToken(
        "{mi_video_bit_depth_space}", "Video bit depth (8 Bit)"
    )
    MI_VIDEO_BIT_DEPTH_DASH = FileToken(
        "{mi_video_bit_depth_dash}", "Video bit depth (8-Bit)"
    )
    MI_VIDEO_CODEC = FileToken("{mi_video_codec}", "Video codec")
    MI_VIDEO_DYNAMIC_RANGE = FileToken(
        "{mi_video_dynamic_range}", "Video dynamic range (HDR/SDR)"
    )
    MI_VIDEO_DYNAMIC_RANGE_TYPE = FileToken(
        "{mi_video_dynamic_range_type}",
        "Video dynamic range type (DV, DV HDR, HDR, HDR10Plus, HLG, PQ)",
    )
    MI_VIDEO_DYNAMIC_RANGE_TYPE_INC_SDR = FileToken(
        "{mi_video_dynamic_range_type_inc_sdr}",
        "Video dynamic range type (DV, DV HDR, HDR, HDR10Plus, HLG, PQ and SDR)",
    )
    MI_VIDEO_DYNAMIC_RANGE_TYPE_INC_SDR_OVER_1080 = FileToken(
        "{mi_video_dynamic_range_type_inc_sdr_over_1080}",
        "Video dynamic range type (DV, DV HDR, HDR, HDR10Plus, HLG, PQ and SDR) when video width >= 1080",
    )
    MI_VIDEO_HEIGHT = FileToken("{mi_video_height}", "Video height (1040)")
    MI_VIDEO_LANGUAGE_ISO_639_1 = FileToken(
        "{mi_video_language_iso_639_1}", "Video language (EN)"
    )
    MI_VIDEO_LANGUAGE_ISO_639_2 = FileToken(
        "{mi_video_language_iso_639_2}", "Video language (ENG)"
    )
    MI_VIDEO_WIDTH = FileToken("{mi_video_width}", "Video width (1920)")
    MOVIE_TITLE = FileToken(
        "{movie_title}", "Movie's title parsed from TMDB/IMDb with minimal formatting"
    )
    MOVIE_CLEAN_TITLE = FileToken(
        "{movie_clean_title}", "Movie's clean title parsed from TMDB/IMDb"
    )
    MOVIE_EXACT_TITLE = FileToken(
        "{movie_exact_title}",
        "Movie's title parsed from TMDB/IMDb with no modifications",
    )
    MOVIE_IMDB_ID = FileToken("{imdb_id}", "IMDb ID")
    MOVIE_TMDB_ID = FileToken("{tmdb_id}", "TMDB ID")
    MOVIE_TVDB_ID = FileToken("{tvdb_id}", "TVDB ID")
    MOVIE_MAL_ID = FileToken("{mal_id}", "MAL ID")
    ORIGINAL_FILENAME = FileToken("{original_filename}", "Original filename")
    RELEASE_GROUP = FileToken("{release_group}", "Release group")
    RELEASERS_NAME = FileToken("{releasers_name}", "Releaser's name (Anonymous)")
    RELEASE_YEAR = FileToken("{release_year}", "Release year")
    RELEASE_YEAR_PARENTHESES = FileToken(
        "{release_year_parentheses}", "Release year with parentheses"
    )
    RE_RELEASE = FileToken("{re_release}", "Repack/Proper")
    RESOLUTION = FileToken("{resolution}", "Resolution (1080p)")
    SOURCE = FileToken("{source}", "Source media (BluRay/DVD)")

    # NFO Tokens
    CHAPTER_TYPE = NfoToken(
        "{chapter_type}", "Chapter type (Named / Numbered (1 - 10) / Tagged)"
    )
    FORMAT_PROFILE = NfoToken("{format_profile}", "Format Profile (Main@L4)")
    MEDIA_FILE = NfoToken("{media_file}", "Media filename with extension")
    MEDIA_FILE_NO_EXT = NfoToken(
        "{media_file_no_ext}", "Media filename without extension"
    )
    MOVIE_FULL_TITLE = NfoToken(
        "{movie_full_title}", "Movie's full title with no formatting removed"
    )
    SOURCE_FILE = NfoToken("{source_file}", "Source filename with extension")
    SOURCE_FILE_NO_EXT = NfoToken(
        "{source_file_no_ext}", "Source filename without extension"
    )
    MEDIA_INFO = NfoToken("{media_info}", "Mediainfo output with filepath cleansed")
    MEDIA_INFO_SHORT = NfoToken(
        "{media_info_short}", "Shortened Mediainfo output with filepath cleansed"
    )
    MI_VIDEO_BIT_RATE = NfoToken(
        "{mi_video_bit_rate}", "Average video bit-rate in kbps (9975 kbps)"
    )
    MI_VIDEO_BIT_RATE_NUM_ONLY = NfoToken(
        "{mi_video_bit_rate_num_only}",
        "Average video bit-rate in kbps, numbers only (9975)",
    )
    REPACK = NfoToken("{repack}", "Returns 'REPACK' if repack was detected")
    REPACK_N = NfoToken("{repack_n}", "Repack and repack number if exists (REPACK2)")
    REPACK_REASON = NfoToken("{repack_reason}", "Reason for REPACK if provided")
    SCREEN_SHOTS = NfoToken("{screen_shots}", "Screenshots")
    FILE_SIZE_BYTES = NfoToken("{file_size_bytes}", "File size in bytes (8469985859)")
    FILE_SIZE = NfoToken("{file_size}", "File size (7.89 GiB)")
    DURATION_MILLISECONDS = NfoToken(
        "{duration_milliseconds}", "Duration in milliseconds (8469985859)"
    )
    DURATION_SHORT = NfoToken("{duration_short}", "Duration (2 h 14 min)")
    DURATION_LONG = NfoToken("{duration_long}", "Duration (2 h 14 min 34 s 65 ms)")
    DURATION_DETAILED = NfoToken("{duration_detailed}", "Duration (02:14:34.065)")
    VIDEO_WIDTH = NfoToken("{video_width}", "Video width (1920)")
    VIDEO_HEIGHT = NfoToken("{video_height}", "Video height (1080)")
    ASPECT_RATIO = NfoToken("{aspect_ratio}", "Aspect ratio (2.40:1)")
    VIDEO_FRAME_RATE = NfoToken("{video_frame_rate}", "FPS (23.976)")
    SUBTITLE_S = NfoToken("{subtitle_s}", "English, French, ...")
    PROPER = NfoToken("{proper}", "Returns 'PROPER' if proper was detected")
    PROPER_N = NfoToken("{proper_n}", "Proper and proper number if exists (PROPER2)")
    PROPER_REASON = NfoToken("{proper_reason}", "Reason for PROPER if provided")

    # nfo forge specific tokens
    PROGRAM_INFO = NfoToken("{program_info}", "NfoForge vx.x.x")
    SHARED_WITH = NfoToken("{shared_with}", "Shared with NfoForge vx.x.x")
    SHARED_WITH_BBCODE = NfoToken(
        "{shared_with_bbcode}", "Shared with NfoForge vx.x.x (hyperlink)"
    )
    SHARED_WITH_HTML = NfoToken(
        "{shared_with_html}", "Shared with NfoForge vx.x.x (hyperlink)"
    )

    @classmethod
    def get_token_objects(
        cls, token_type: Iterable[TokenType] | Type[TokenType] | None = None
    ) -> set[TokenType]:
        """Returns a set of token objects based on the specified token type"""
        token_types = [FileToken, NfoToken] if token_type is None else [token_type]
        return {
            getattr(cls, attr)
            for attr in dir(cls)
            for ttype in token_types
            if isinstance(
                getattr(cls, attr), ttype if isinstance(ttype, type) else type(ttype)
            )
        }

    @staticmethod
    def get_tokens(
        token_type: Iterable[TokenType] | Type[TokenType] | None = None,
    ) -> set[str]:
        """Returns a set of tokens without the brackets based on the specified token type"""
        return {token.token[1:-1] for token in Tokens.get_token_objects(token_type)}

    @staticmethod
    def generate_token_dataclass(
        token_type: Iterable[TokenType] | Type[TokenType] | None = None,
    ) -> Any:
        """This dynamically creates a data class for the tokens above"""
        fields = [
            (token, str | None, field(default=None))
            for token in Tokens.get_tokens(token_type)
        ]

        TokenDataClass = make_dataclass(
            cls_name="TokenData",
            fields=fields,
            namespace={"get_dict": lambda self: asdict(self)},
        )
        return TokenDataClass()
