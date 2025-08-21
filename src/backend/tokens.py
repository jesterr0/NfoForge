from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, make_dataclass
from typing import Any, NamedTuple, Type

from src.enums import CaseInsensitiveStrEnum


TITLE_CLEAN_REPLACE_DEF = [
    (r"", r"[unidecode]"),
    (r"&", r"and"),
    (r"'", r"[remove]"),
    (r"[^a-zA-Z0-9]", r"[space]"),
    (r"\s{2,}", r"[space]"),
]


@dataclass(frozen=True)
class TokenData:
    """Holds the data for tokens"""

    pre_token: str | None = None
    token: str | None = None
    bracket_token: str | None = None
    post_token: str | None = None
    full_match: str | None = None
    filters: tuple[str, ...] = field(default_factory=tuple)


class TokenType(NamedTuple):
    token: str
    description: str


class FileToken(TokenType):
    pass


class NfoToken(TokenType):
    pass


class TokenSelection(CaseInsensitiveStrEnum):
    FILE_TOKEN = "FileToken"
    NFO_TOKEN = "NfoToken"

    def get_token_obj(self) -> Type[TokenType]:
        if self == TokenSelection.FILE_TOKEN:
            return FileToken
        elif self == TokenSelection.NFO_TOKEN:
            return NfoToken
        raise AttributeError("Failed to get token object")


class Tokens:
    __slots__ = ()

    # File Tokens
    EDITION = FileToken("{edition}", "Edition")
    FRAME_SIZE = FileToken("{frame_size}", "Frame size (IMAX/Open Matte)")
    HYBRID = FileToken("{hybrid}", "HYBRID")
    LOCALIZATION = FileToken("{localization}", "Subbed/Dubbed")
    AUDIO_BITRATE = FileToken("{audio_bitrate}", "Audio bitrate (640000)")
    AUDIO_BITRATE_FORMATTED = FileToken(
        "{audio_bitrate_formatted}", "Audio bitrate formatted (640 kb/s)"
    )
    AUDIO_CHANNEL_S = FileToken("{audio_channel_s}", "Audio channels (5.1)")
    AUDIO_CHANNEL_S_I = FileToken("{audio_channel_s_i}", "Audio channels (6)")
    AUDIO_CHANNEL_S_LAYOUT = FileToken(
        "{audio_channel_s_layout}", "Audio channel layout (L R C LFE Ls Rs Lb Rb)"
    )
    AUDIO_CODEC = FileToken("{audio_codec}", "Audio codec")
    AUDIO_COMMERCIAL_NAME = FileToken(
        "{audio_commercial_name}", "Audio commercial name (Dolby Digital Plus)"
    )
    AUDIO_COMPRESSION = FileToken("{audio_compression}", "Audio compression (Lossy)")
    AUDIO_FORMAT_INFO = FileToken(
        "{audio_format_info}", "Audio format info (Enhanced AC-3)"
    )
    AUDIO_LANGUAGE_1_FULL = FileToken(
        "{audio_language_1_full}", "Audio language (first track 'English')"
    )
    AUDIO_LANGUAGE_1_ISO_639_1 = FileToken(
        "{audio_language_1_iso_639_1}", "Audio language (first track 'EN')"
    )
    AUDIO_LANGUAGE_1_ISO_639_2 = FileToken(
        "{audio_language_1_iso_639_2}", "Audio language (first track 'ENG')"
    )
    AUDIO_LANGUAGE_2_ISO_639_1 = FileToken(
        "{audio_language_2_iso_639_1}", "Audio language (first two tracks EN+ES)"
    )
    AUDIO_LANGUAGE_2_ISO_639_2 = FileToken(
        "{audio_language_2_iso_639_2}", "Audio languages (first two tracks ENG+SPA)"
    )
    AUDIO_LANGUAGE_ALL_ISO_639_1 = FileToken(
        "{audio_language_all_iso_639_1}",
        "All audio languages (all tracks EN+ES+etc..)",
    )
    AUDIO_LANGUAGE_ALL_ISO_639_2 = FileToken(
        "{audio_language_all_iso_639_2}",
        "All audio languages (all tracks ENG+SPA+etc..)",
    )
    AUDIO_LANGUAGE_ALL_FULL = FileToken(
        "{audio_language_all_full}",
        "All audio languages (all tracks English Spanish..)",
    )
    AUDIO_LANGUAGE_DUAL = FileToken(
        "{audio_language_dual}",
        "Audio language ('Dual Audio' will be returned if there are 2 or more tracks with unique languages)",
    )
    AUDIO_LANGUAGE_MULTI = FileToken(
        "{audio_language_multi}",
        "Audio languages ('Multi' will be returned if there are 3 or more tracks with unique languages)",
    )
    AUDIO_SAMPLE_RATE = FileToken("{audio_sample_rate}", "Audio sample rate (48.0 kHz)")
    VIDEO_3D = FileToken("{video_3d}", "Video 3D")
    VIDEO_BIT_DEPTH_SPACE = FileToken(
        "{video_bit_depth_space}", "Video bit depth (8 Bit)"
    )
    VIDEO_BIT_DEPTH_DASH = FileToken(
        "{video_bit_depth_dash}", "Video bit depth (8-Bit)"
    )
    VIDEO_CODEC = FileToken("{video_codec}", "Video codec")
    VIDEO_DYNAMIC_RANGE = FileToken(
        "{video_dynamic_range}", "Video dynamic range (HDR/SDR)"
    )
    VIDEO_DYNAMIC_RANGE_TYPE = FileToken(
        "{video_dynamic_range_type}",
        "Video dynamic range type (DV, DV HDR, HDR, HDR10Plus, HLG, PQ)",
    )
    VIDEO_DYNAMIC_RANGE_TYPE_INC_SDR = FileToken(
        "{video_dynamic_range_type_inc_sdr}",
        "Video dynamic range type (DV, DV HDR, HDR, HDR10Plus, HLG, PQ and SDR)",
    )
    VIDEO_DYNAMIC_RANGE_TYPE_INC_SDR_OVER_1080 = FileToken(
        "{video_dynamic_range_type_inc_sdr_over_1080}",
        "Video dynamic range type (DV, DV HDR, HDR, HDR10Plus, HLG, PQ and SDR) when video width >= 1080",
    )
    VIDEO_FORMAT = FileToken("{video_format}", "Video format (AVC/HEVC/MPEG Video)")
    VIDEO_HEIGHT = FileToken("{video_height}", "Video height (1040)")
    VIDEO_LANGUAGE_FULL = FileToken("{video_language_full}", "Video language (English)")
    VIDEO_LANGUAGE_ISO_639_1 = FileToken(
        "{video_language_iso_639_1}", "Video language (EN)"
    )
    VIDEO_LANGUAGE_ISO_639_2 = FileToken(
        "{video_language_iso_639_2}", "Video language (ENG)"
    )
    VIDEO_WIDTH = FileToken("{video_width}", "Video width (1920)")
    TITLE = FileToken(
        "{title}", "Title parsed from media databases with minimal formatting"
    )
    TITLE_CLEAN = FileToken("{title_clean}", "Clean title parsed from media databases")
    TITLE_EXACT = FileToken(
        "{title_exact}",
        "Title parsed from media databases with no modifications",
    )
    IMDB_ID = FileToken("{imdb_id}", "IMDb ID")
    TMDB_ID = FileToken("{tmdb_id}", "TMDB ID")
    TVDB_ID = FileToken("{tvdb_id}", "TVDB ID")
    MAL_ID = FileToken("{mal_id}", "MAL ID")
    ORIGINAL_FILENAME = FileToken("{original_filename}", "Original filename")
    RELEASE_GROUP = FileToken("{release_group}", "Release group")
    RELEASERS_NAME = FileToken("{releasers_name}", "Releaser's name (Anonymous)")
    RELEASE_YEAR = FileToken("{release_year}", "Release year")
    RELEASE_YEAR_PARENTHESES = FileToken(
        "{release_year_parentheses}", "Release year with parentheses"
    )
    RE_RELEASE = FileToken("{re_release}", "Repack/Proper")
    RESOLUTION = FileToken("{resolution}", "Resolution (1080p)")
    REMUX = FileToken("{remux}", "REMUX")
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
    SOURCE_FILE = NfoToken("{source_file}", "Source filename with extension")
    SOURCE_FILE_NO_EXT = NfoToken(
        "{source_file_no_ext}", "Source filename without extension"
    )
    MEDIA_INFO = NfoToken("{media_info}", "Mediainfo output with filepath cleansed")
    MEDIA_INFO_SHORT = NfoToken(
        "{media_info_short}", "Shortened Mediainfo output with filepath cleansed"
    )
    VIDEO_BIT_RATE = NfoToken(
        "{video_bit_rate}", "Average video bit-rate in kbps (9975 kbps)"
    )
    VIDEO_BIT_RATE_NUM_ONLY = NfoToken(
        "{video_bit_rate_num_only}",
        "Average video bit-rate in kbps, numbers only (9975)",
    )
    RELEASE_NOTES = NfoToken(
        "{release_notes}",
        "Special token that is optionally applied for each job process",
    )
    REPACK = NfoToken("{repack}", "Returns 'REPACK' if repack was detected")
    REPACK_N = NfoToken("{repack_n}", "Repack and repack number if exists (REPACK2)")
    REPACK_REASON = NfoToken("{repack_reason}", "Reason for REPACK if provided")
    SCREEN_SHOTS = NfoToken("{screen_shots}", "Screenshots")
    SCREEN_SHOTS_COMPARISON = NfoToken(
        "{screen_shots_comparison}",
        "Screenshots in comparison mode (raw URLs only; user must add comparison tags)",
    )
    SCREEN_SHOTS_EVEN_OJB = NfoToken(
        "{screen_shots_even_obj}",
        "Even screenshot objects in a list with both obj.url and obj.medium_url (both are not guaranteed)",
    )
    SCREEN_SHOTS_ODD_OBJ = NfoToken(
        "{screen_shots_odd_obj}",
        "Odd screenshot URLs in a list with both obj.url and obj.medium_url (both are not guaranteed)",
    )
    SCREEN_SHOTS_EVEN_STR = NfoToken(
        "{screen_shots_even_str}",
        "Even screenshot URLs as strings (medium_url if available, else url)",
    )
    SCREEN_SHOTS_ODD_STR = NfoToken(
        "{screen_shots_odd_str}",
        "Odd screenshot URLs as strings (medium_url if available, else url)",
    )
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
            cls_name="TokenInfo",
            fields=fields,
            namespace={"get_dict": lambda self: asdict(self)},
        )
        return TokenDataClass()
