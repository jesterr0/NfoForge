from ast import literal_eval
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
import re
from typing import Any, cast

from auto_qpf import ChapterGenerator
from auto_qpf.enums import ChapterType
from babelfish.language import Language as BabelLanguage
from guessit import guessit
from iso639 import Lang
from iso639.exceptions import InvalidLanguageValue
from jinja2 import meta
from pymediainfo import MediaInfo, Track
import unidecode

from src.backend.tokens import FileToken, NfoToken, TokenData, Tokens, TokenType
from src.backend.utils.anime import is_anime_release
from src.backend.utils.audio_channels import ParseAudioChannels
from src.backend.utils.audio_codecs import AudioCodecs
from src.backend.utils.guessit_helpers import get_guessit_title
from src.backend.utils.language import (
    get_full_language_str,
    get_language_mi,
    get_language_str,
)
from src.backend.utils.media_info_utils import (
    MinimalMediaInfo,
    calculate_avg_bitrate,
    calculate_avg_video_bit_rate,
)
from src.backend.utils.rename_normalizations import (
    CUT_EDITION_NAMES,
    EDITION_INFO,
)
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.backend.utils.streaming_services import abbreviate_streaming_service
from src.backend.utils.working_dir import RUNTIME_DIR
from src.config.models import DynamicRangeSettings, HdrType, ResolutionKey
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.rename import QualitySelection
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace, SharedWithType, UnfilledTokenRemoval
from src.exceptions import GuessitParsingError, InvalidTokenError
from src.logger.nfo_forge_logger import LOG
from src.nf_jinja2 import Jinja2TemplateEngine
from src.packages.custom_types import ImageUploadData, RenameNormalization
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.series import format_multi_season_range
from src.plugins.api import FlatFilter
from src.version import __version__, program_name, program_url

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_DEVICE_NAMES = frozenset({"CON", "PRN", "AUX", "NUL"})

# Parks a '*title_clean' value while the colon pass runs over everything else.
# A control character so it cannot collide with template text, and stripped
# again before _format_token_string returns.
_TITLE_CLEAN_SENTINEL = "\x00"

# Source-override spellings that no longer match a QualitySelection value.
# `dynamic_data` (which carries the override tokens) is persisted with a saved
# job, so a job created before WEB_DL became "WEB-DL" replays the old text and
# still has to resolve to the right source.
_LEGACY_SOURCE_OVERRIDES = {"webdl": QualitySelection.WEB_DL}

# Characters that cannot appear in a Windows path component. Shared by the
# standard title formatter and the exact-episode-title token so the two
# cannot drift apart.
_TITLE_UNSAFE_CHARS = re.compile(r'[:\\/<>\?*"|]')
_REPEATED_WHITESPACE = re.compile(r"\s{2,}")


class TokenReplacer:
    # Overrides that must not be emitted verbatim. `source` comes from the
    # wizard's Quality combo, whose item text is a QualitySelection value, and
    # is also replayed from jobs saved by earlier versions -- where it is the
    # pre-rename "WEBDL" spelling. Routing it back through its own token
    # handler re-maps it to the canonical name instead of printing whatever
    # string happens to be stored.
    CANONICALIZED_OVERRIDES = frozenset({"source"})

    # TVDB placeholder episode titles that should render as empty rather
    # than landing in output verbatim: exactly "TBA", or "Episode" followed
    # by optional whitespace and digits (e.g. "Episode 12", "Episode12").
    # Anchored on both ends so real titles like "TBA Confidential" or
    # "Episode of Care" are left untouched.
    _PLACEHOLDER_EPISODE_TITLE_RE = re.compile(
        r"^(?:tba|episode\s*\d+)$", re.IGNORECASE
    )

    # matches the Atmos suffix the audio conventions file produces ("DDP Atmos",
    # "TrueHD Atmos"). Leading whitespace is part of the pattern so stripping
    # leaves "DDP" rather than "DDP ".
    _ATMOS_RE = re.compile(r"\s*\bAtmos\b", re.IGNORECASE)

    __slots__ = (
        # __init__
        "media_input_obj",
        "active_file",
        "token_string",
        "jinja_engine",
        "colon_replace",
        "media_search_obj",
        "flatten",
        "flat_filters",
        "custom_edition_info",
        "custom_cut_names",
        "file_name_mode",
        "append_suffix",
        "token_type",
        "unfilled_token_mode",
        "releasers_name",
        "override_tokens",
        "user_tokens",
        "edition_override",
        "frame_size_override",
        "title_clean_rules",
        "override_title_rules",
        "video_dynamic_range",
        "screen_shots",
        "screen_shots_comparison",
        "screen_shots_even_obj",
        "screen_shots_odd_obj",
        "screen_shots_even_str",
        "screen_shots_odd_str",
        "release_notes",
        "dummy_screen_shots",
        "preserve_literal_formatting",
        # series exclusive args
        "season_number",
        "season_end",
        "episode_number",
        "episode_format",
        "multi_episode_style",
        # derived properties (computed from payload)
        "primary_file",
        "source_file",
        "media_info_obj",
        "source_file_mi_obj",
        "guess_name",
        "guess_source_name",
        "guessit_title",
        # vars (set during __init__)
        "guessit_language",
        "token_data",
        # series caches
        "_series_counts",
        "_series_episode_cache",
        # audio codec cache
        "_audio_codec_cache",
    )

    def __init__(
        self,
        media_input_obj: MediaInputPayload,
        token_string: str,
        jinja_engine: Jinja2TemplateEngine | None = None,
        colon_replace: ColonReplace = ColonReplace.REPLACE_WITH_DASH,
        media_search_obj: MediaSearchPayload | None = None,
        flatten: bool | None = False,
        flat_filters: Mapping[str, FlatFilter] | None = None,
        custom_edition_info: Sequence[RenameNormalization] | None = None,
        custom_cut_names: frozenset[str] | None = None,
        file_name_mode: bool = True,
        append_suffix: bool = True,
        token_type: Iterable[TokenType] | type[TokenType] | None = None,
        unfilled_token_mode: UnfilledTokenRemoval = UnfilledTokenRemoval.KEEP,
        releasers_name: str | None = "",
        override_tokens: dict[str, str] | None = None,
        user_tokens: dict[str, str] | None = None,
        edition_override: str | None = None,
        frame_size_override: str | None = None,
        title_clean_rules: list[tuple[str, str]] | None = None,
        override_title_rules: list[tuple[str, str]] | None = None,
        video_dynamic_range: DynamicRangeSettings | None = None,
        screen_shots: str | None = None,
        screen_shots_comparison: str | None = None,
        screen_shots_even_obj: Sequence[ImageUploadData] | None = None,
        screen_shots_odd_obj: Sequence[ImageUploadData] | None = None,
        screen_shots_even_str: Sequence[str] | None = None,
        screen_shots_odd_str: Sequence[str] | None = None,
        release_notes: str | None = "",
        dummy_screen_shots: bool = False,
        preserve_literal_formatting: bool = False,
        season_number: int | None = None,
        season_end: int | None = None,
        episode_number: int | None = None,
        episode_format: EpisodeFormat | None = None,
        multi_episode_style: MultiEpisodeStyle = MultiEpisodeStyle.RANGE,
        active_file: Path | None = None,
    ):
        """
        Takes a MediaInputPayload and outputs formatted strings based on tokens.

        Args:
            media_input_obj (MediaInputPayload): Payload containing all file information.
            token_string (str): Token string.
            jinja_engine (Optional[Jinja2TemplateEngine]): JinjaEngine class.
            colon_replace (ColonReplace): What to do with colons.
            media_search_obj (Optional[MediaSearchPayload], optional): Payload.
            flatten (Optional[bool]): Rather or not to flatten the data to a single string
            file_name_mode: bool: Returned string will be in 'x.x.ext' format (ignored if not using flatten).
              with no newlines or extra white space (used for filenames). `colon_replace` is ignored
              when this is used.
            append_suffix (bool): Whether `file_name_mode` ends the name with the input
              file's extension. Set False for a folder name, which has none: the
              extension is then neither appended nor charged against the 255-character
              budget. Ignored outside `file_name_mode`.
            token_type (Optional[Iterable[TokenType]]): Specific `TokenType`'s to use, or None for all.
            unfilled_token_mode (UnfilledTokenRemoval): What to do with unused tokens.
            eg. (TokenType, TokenType).
            releasers_name (Optional[str]): Releasers name.
            override_tokens (Optional[dict[str, str]]): Override tokens with a supplied value regardless of logic.
            user_tokens (Optional[dict[str, str]]): User tokens (must be prefixed with usr_).
            edition_override (Optional[str]): Edition override.
            frame_size_override (Optional[str]): Frame size override.
            title_clean_rules: (Optional[list[tuple[str, str]]]: Rules to iterate and replace for 'title_clean' token.
            override_title_rules: (Optional[list[tuple[str, str]]]: Rules to iterate and replace for final title output.
            video_dynamic_range: Rules to control formatting of video dynamic range.
            screen_shots (Optional[str]): Screenshots.
            screen_shots_comparison (Optional[str]): Screenshots in comparison mode
              (raw URLs only; user must add comparison tags).
            screen_shots_even_obj (Optional[Sequence[ImageUploadData]]): Even screenshot objects in a
              list with both obj.url and obj.medium_url (both are not guaranteed).
            screen_shots_odd_obj (Optional[Sequence[ImageUploadData]]): Odd screenshot URLs in a list
              with both obj.url and obj.medium_url (both are not guaranteed).
            screen_shots_even_str (Optional[Sequence[str]]): Even screenshot URLs as strings
              (medium_url if available, else url).
            screen_shots_odd_str (Optional[Sequence[str]]): Odd screenshot URLs as strings
              (medium_url if available, else url).
            release_notes (Optional[str]): Release notes.
            dummy_screen_shots (Optional[bool]): If set to True will generate some dummy screenshot data for the
              screenshot token (This overrides screen_shots if used, so only use when you have screenshot data).
            preserve_literal_formatting: Return flattened title-mode output
              without normalizing whitespace or punctuation. This is intended
              for templates whose literal text carries meaning, such as paths.
            season_number (Optional[int]): Season number.
            season_end (Optional[int]): Highest season number in a multi-season pack. When
                set and different from `season_number`, the {season_number} token renders
                a pre-padded "SS-Seend" range instead of the raw start season (e.g.
                season_number=1, season_end=5 -> "01-S05"). Ignored (single season) when
                None or equal to `season_number`.
            episode_number (Optional[int]): Episode number.
            episode_format (Optional[EpisodeFormat]): Episode format (Standard, Daily, Anime).
            multi_episode_style (MultiEpisodeStyle): How the {episode_number} token renders a
                multi-episode file's span (e.g. RANGE -> "01-03", SCENE -> "01-E03"). Ignored for
                single-episode files, whose {episode_number} stays the raw start number.
            flat_filters (Optional[Mapping[str, FlatFilter]]): Custom filters for flat mode.
                Dictionary mapping filter names to callable functions that take (value, *args) and return str.
            custom_edition_info (Optional[Sequence[RenameNormalization]]): Plugin-contributed
                entries merged with EDITION_INFO for the {edition}/{cut} tokens.
            custom_cut_names (Optional[frozenset[str]]): Plugin-contributed entry names merged
                with CUT_EDITION_NAMES -- which of `custom_edition_info` (by `.normalized`) counts
                as a Cut for the {cut} token, same as the built-in CUT_EDITION_NAMES split.
            active_file (Optional[Path]): File to use for filename and MediaInfo-derived
                tokens. When omitted, the payload's comparison media or first file is used.
        """
        self.media_input_obj = media_input_obj
        self.active_file = active_file
        self.token_string = token_string
        self.jinja_engine = jinja_engine
        self.colon_replace = ColonReplace(colon_replace)
        self.media_search_obj = (
            media_search_obj if media_search_obj else MediaSearchPayload()
        )
        self.flatten = flatten
        self.flat_filters = flat_filters
        self.custom_edition_info = custom_edition_info or ()
        self.custom_cut_names = custom_cut_names or frozenset()
        self.file_name_mode = file_name_mode
        self.append_suffix = append_suffix
        self.token_type = token_type
        self.unfilled_token_mode = UnfilledTokenRemoval(unfilled_token_mode)
        self.releasers_name = releasers_name
        self.override_tokens = override_tokens
        self.user_tokens = user_tokens
        self.edition_override = edition_override
        self.frame_size_override = frame_size_override
        self.title_clean_rules = title_clean_rules
        self.override_title_rules = override_title_rules
        self.video_dynamic_range = video_dynamic_range
        self.screen_shots = screen_shots
        self.screen_shots_comparison = screen_shots_comparison
        self.screen_shots_even_obj = screen_shots_even_obj
        self.screen_shots_odd_obj = screen_shots_odd_obj
        self.screen_shots_even_str = screen_shots_even_str
        self.screen_shots_odd_str = screen_shots_odd_str
        self.release_notes = release_notes
        self.dummy_screen_shots = dummy_screen_shots
        self.preserve_literal_formatting = preserve_literal_formatting
        # series exclusive args
        self.season_number = season_number
        self.season_end = season_end
        self.episode_number = episode_number
        self.episode_format = episode_format
        self.multi_episode_style = MultiEpisodeStyle(multi_episode_style)

        # derive file references from payload (paths are always current after renames)
        self.primary_file = self._get_primary_file()
        self.source_file = self._get_source_file()
        self.media_info_obj = self._get_primary_mediainfo()
        self.source_file_mi_obj = self._get_source_mediainfo()
        self.guess_name = guessit(self.primary_file.name)
        self.guess_source_name = (
            guessit(self.source_file.name) if self.source_file else None
        )
        self.guessit_title = get_guessit_title(self.guess_name)
        self.guessit_language = self._guessit_language()
        self.token_data = Tokens.generate_token_dataclass(token_type)

        # series counts and episode lookups have different key/value shapes
        self._series_counts: dict[str, int] = {}
        # keyed by ordering type id first: TVDB serves several episode
        # orderings and the same (season, episode) pair names a different
        # episode in each, so a cache keyed only on the pair would answer a
        # DVD-order lookup with an aired-order episode.
        self._series_episode_cache: dict[Any, dict[int, dict[int, dict[str, Any]]]] = {}

        # the conventions file is read from disk per lookup, and three tokens
        # share the result, so resolve it once per instance
        self._audio_codec_cache: str | None = None

        if not self.flatten and not self.jinja_engine:
            raise AttributeError(
                "You must pass in 'jinja_engine' if you are not flattening your output string"
            )

    def _get_primary_file(self) -> Path:
        """Determine the primary file for token analysis based on context."""
        if self.active_file is not None:
            return self.active_file

        # if comparison mode, use the media file (not source)
        if self.media_input_obj.comparison_pair:
            return self.media_input_obj.comparison_pair.media

        # use first file in list
        if self.media_input_obj.file_list:
            return self.media_input_obj.file_list[0]

        # fallback to input path if it's a file
        if (
            self.media_input_obj.input_path
            and self.media_input_obj.input_path.is_file()
        ):
            return self.media_input_obj.input_path

        raise ValueError("No valid primary file found in MediaInputPayload")

    def _get_source_file(self) -> Path | None:
        """Determine the source file based on context."""
        # if comparison mode, use the source from comparison pair
        if self.media_input_obj.comparison_pair:
            return self.media_input_obj.comparison_pair.source
        return None

    def _get_primary_mediainfo(self) -> MediaInfo | None:
        """Get MediaInfo for the primary file."""
        if not self.media_input_obj.file_list_mediainfo:
            return None
        return self.media_input_obj.file_list_mediainfo.get(self.primary_file)

    def _get_source_mediainfo(self) -> MediaInfo | None:
        """Get MediaInfo for the source file."""
        if not self.source_file:
            return None

        # Get from file_list_mediainfo if available
        if self.media_input_obj.file_list_mediainfo:
            return self.media_input_obj.file_list_mediainfo.get(self.source_file)

        return None

    @property
    def media_input(self) -> Path:
        """Backward compatibility property."""
        return self.primary_file

    @property
    def is_series_mode(self) -> bool:
        """Check if we're processing a series."""
        return self.media_input_obj.media_type == MediaType.SERIES

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
            # Keyed by the *occurrence* -- the literal `{token|filter}` text as
            # written -- not by the base token name. A template may use the same
            # token twice with different filters (`{video_codec|only_if(remux)}`
            # alongside `{video_codec|unless(remux)}`), and a base-name key made
            # the second occurrence overwrite the first, then substituted that
            # single value into both spots.
            flattened_tokens: dict[str, tuple[str, str]] = {}
            # `token_data` is a dataclass whose fields are the bare token names,
            # so its update still needs base-name keys. Later occurrences of a
            # token overwrite earlier ones here, which is the pre-existing
            # behaviour for a name that can only hold one value.
            token_data_values: dict[str, str] = {}
            for token in tokens:
                if token.token is None or token.full_match is None:
                    continue
                token_value = self._get_token_value(token)
                resolved = token_value if isinstance(token_value, str) else ""
                flattened_tokens[token.full_match] = (token.token, resolved)
                token_data_values[token.token] = resolved
            self._update_token_data(token_data_values)
            return self._format_token_string(flattened_tokens)
        else:
            jinja_tokens: dict[str, object] = {}
            for token in self._parse_jinja_input():
                if token.token is not None:
                    jinja_tokens[token.token] = self._get_token_value(token)
            # add user tokens to the context for jinja2 rendering
            if self.user_tokens:
                for key, value in self.user_tokens.items():
                    jinja_tokens[key] = value
            self._update_token_data(jinja_tokens)
            if not self.jinja_engine:
                raise AttributeError("Could not detect 'jinja_engine'")
            jinja_output = self.jinja_engine.render_from_str(
                self.token_string,
                jinja_tokens,
            )
            return jinja_output

    def _update_token_data(self, filled_tokens: Mapping[str, object]) -> None:
        for key, value in filled_tokens.items():
            setattr(self.token_data, key, value)

    def _parse_user_input(self) -> set[TokenData]:
        """
        Extract valid tokens from user input string, supporting |filter and :opt=x:.
        Filters are always parsed and applied.
        """
        valid_tokens = Tokens.get_tokens()

        # match tokens with optional :opt=...: before or after, and filters using |filter
        matches = re.finditer(
            r"{(?::opt=([^:}]*):)?([^}]+?)(?::opt=([^:}]*):)?}", self.token_string
        )
        parsed_tokens: set[TokenData] = set()
        for match in matches:
            pre_opt = match.group(1) if match.group(1) else ""
            token_and_filters = match.group(2)
            post_opt = match.group(3) if match.group(3) else ""

            # split token and filters
            parts = [p.strip() for p in token_and_filters.split("|")]
            base_token = parts[0]
            filters = parts[1:] if len(parts) > 1 else []

            # only accept built-in or user tokens
            if base_token in valid_tokens or (
                base_token.startswith("usr_")
                and self.user_tokens
                and base_token in self.user_tokens
            ):
                token_data = TokenData(
                    pre_token=pre_opt,
                    token=base_token,
                    bracket_token=f"{{{base_token}}}",
                    post_token=post_opt,
                    full_match=match.group(0),
                    filters=tuple(filters),  # make filters a tuple for hash-ability
                )
                parsed_tokens.add(token_data)

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

    def _parse_jinja_input(self) -> set[TokenData]:
        if not self.jinja_engine:
            raise AttributeError("Could not detect 'jinja_engine'")

        valid_tokens = Tokens.get_tokens()
        ast = self.jinja_engine.environment.parse(self.token_string)
        referenced_tokens = meta.find_undeclared_variables(ast)
        return {
            TokenData(
                pre_token="",
                token=token,
                bracket_token=f"{{{token}}}",
                post_token="",
                full_match=f"{{{token}}}",
            )
            for token in referenced_tokens
            if token in valid_tokens
        }

    def _get_token_value(self, token_data: TokenData) -> str | Sequence[Any] | None:
        # handle user and prompt tokens
        if (
            self.user_tokens
            and token_data.token
            and (
                token_data.token.startswith("usr_")
                or token_data.token.startswith("prompt_")
            )
        ):
            return self._optional_user_input(
                self.user_tokens.get(token_data.token, ""), token_data
            )

        # handle override tokens
        if (
            self.override_tokens
            and token_data.token in self.override_tokens
            and token_data.token not in self.CANONICALIZED_OVERRIDES
        ):
            return self._optional_user_input(
                self.override_tokens[token_data.token], token_data
            )

        # get raw token value
        raw_value = self._get_raw_token_value(token_data)
        if not raw_value:
            return ""

        return raw_value

    def _get_raw_token_value(self, token_data: TokenData) -> str | Sequence[Any] | None:
        """Get the raw token value without filters or pre/post tokens."""
        # determine which token types to check
        if self.token_type:
            token_types = (
                self.token_type
                if isinstance(self.token_type, list | set | tuple)
                else [self.token_type]
            )
        else:
            # no specific type: check both media and nfo tokens
            token_types = [FileToken, NfoToken]

        for token_type in token_types:
            if token_type == FileToken:
                media_value = self._media_tokens(token_data)
                if media_value:
                    return media_value
            elif token_type == NfoToken:
                nfo_value = self._nfo_tokens(token_data)
                if nfo_value:
                    return nfo_value

        return ""

    def _apply_custom_filters(self, value: str, filters: tuple[str, ...]) -> str:
        """Apply custom filters to a string value.

        Filters run left to right. Most of them *describe* a value, so with
        nothing to describe they are skipped rather than run on an empty string
        -- otherwise a missing episode number would come back from `zfill(2)`
        as "00". `default` is the deliberate exception: it exists to supply a
        value where the release has none, and any filter written after it sees
        the value it supplied.
        """
        for f in filters:
            f_lowered = f.lower()
            if not value and not f_lowered.startswith("default("):
                continue
            if f_lowered.startswith("default(") and f_lowered.endswith(")"):
                if not value:
                    value = self._parse_filter_argument(f) or value
            elif f_lowered.startswith(("only_if(", "unless(")) and f_lowered.endswith(
                ")"
            ):
                value = self._apply_conditional_filter(value, f)
            elif f_lowered == "upper":
                value = value.upper()
            elif f_lowered == "lower":
                value = value.lower()
            elif f_lowered == "title":
                value = value.title()
            elif f_lowered == "swapcase":
                value = value.swapcase()
            elif f_lowered == "capitalize":
                value = value.capitalize()
            elif f_lowered.startswith("zfill(") and f_lowered.endswith(")"):
                m = re.match(r"zfill\((\d+)\)", f, re.IGNORECASE)
                if m:
                    try:
                        value = value.zfill(int(m.group(1)))
                    except ValueError:
                        LOG.warning(
                            LOG.LOG_SOURCE.BE,
                            f"Ignoring zfill filter with an unusable width: {f}",
                        )
                else:
                    LOG.warning(
                        LOG.LOG_SOURCE.BE,
                        f"Ignoring malformed zfill filter argument: {f}",
                    )
            elif f_lowered.startswith("replace(") and f_lowered.endswith(")"):
                m = re.match(r"replace\((['\"])(.*?)\1,\s*?(['\"])(.*?)\3\)", f)
                if m:
                    old = m.group(2)
                    new = m.group(4)
                    value = value.replace(old, new)
            # extensible filters (supporting both simple filters and functions with parameters)
            else:
                value = self._apply_extensible_filter(value, f)

        return value

    @staticmethod
    def _parse_filter_argument(filter_expr: str) -> str:
        """Return a single-argument filter's argument, unquoted.

        `default('NOGROUP')`, `default("NOGROUP")` and `default(NOGROUP)` all
        yield "NOGROUP".
        """
        arg = filter_expr[filter_expr.index("(") + 1 : -1].strip()
        if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "\"'":
            return arg[1:-1]
        return arg

    def _apply_conditional_filter(self, value: str, filter_expr: str) -> str:
        """Blank ``value`` based on whether other tokens resolve to anything.

        ``only_if(a, b)`` keeps the value only when *every* named token
        resolves truthy; ``unless(a, b)`` drops it when *any* of them does.
        Together they let one template carry two component orders and emit the
        one that fits the release -- Aither and LST put audio last for a remux
        and first for an encode, which is otherwise inexpressible in a single
        token string.

        Conditions resolve through the same machinery that renders the tokens
        themselves, so a condition can never disagree with what is printed:
        whatever makes `{remux}` render is exactly what flips the order.
        """
        name = filter_expr[: filter_expr.index("(")].lower()
        raw_args = self._parse_filter_argument(filter_expr)
        conditions = [
            part.strip().strip("\"'") for part in raw_args.split(",") if part.strip()
        ]
        if not conditions:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Ignoring '{name}' filter with no token to test: {filter_expr}",
            )
            return value

        valid_tokens = Tokens.get_tokens()
        results: list[bool] = []
        for condition in conditions:
            if condition not in valid_tokens:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Ignoring '{name}' filter: '{condition}' is not a token.",
                )
                return value
            results.append(bool(self._resolve_condition_token(condition)))

        met = all(results) if name == "only_if" else not any(results)
        return value if met else ""

    def _resolve_condition_token(self, token: str) -> str:
        """Resolve ``token`` to its plain value, for use as a condition.

        Deliberately filterless and without any `:opt=` wrapper: a condition
        asks whether the token has a value at all, so re-entering
        `_apply_conditional_filter` (and a template able to make a token depend
        on itself) is impossible.
        """
        value = self._get_token_value(
            TokenData(
                pre_token="",
                token=token,
                bracket_token=f"{{{token}}}",
                post_token="",
                full_match=f"{{{token}}}",
            )
        )
        return value if isinstance(value, str) else ""

    def _apply_extensible_filter(self, value: str, filter_expr: str) -> str:
        """Apply extensible filters with argument parsing."""
        if not self.flat_filters:
            return value

        # parse filter name and arguments
        if "(" in filter_expr and filter_expr.endswith(")"):
            filter_name = filter_expr[: filter_expr.index("(")]
            args_str = filter_expr[filter_expr.index("(") + 1 : -1]

            # parse arguments safely
            try:
                # handle common cases
                if not args_str.strip():
                    args = None
                else:
                    # try to parse as Python literals (strings, numbers, booleans)
                    if len(args_str) > 200:
                        args = (args_str,)
                    else:
                        args = literal_eval(f"[{args_str}]")
            except (ValueError, SyntaxError):
                # fallback: treat as single string argument (remove quotes if present)
                args_str = args_str.strip()
                if (args_str.startswith('"') and args_str.endswith('"')) or (
                    args_str.startswith("'") and args_str.endswith("'")
                ):
                    args = (args_str[1:-1],)
                else:
                    args = (args_str,)
        else:
            filter_name = filter_expr
            args = None

        # apply registered filter
        if filter_name in self.flat_filters:
            try:
                if args:
                    return self.flat_filters[filter_name](value, *args)
                return self.flat_filters[filter_name](value)
            except Exception as error:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Flat filter '{filter_name}' failed, using the unfiltered "
                    f"value: {error}",
                )
                # return original value if filter fails
                return value

        # unknown filter: return unchanged (graceful degradation)
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Unknown flat filter '{filter_name}'; the value is emitted "
            "unfiltered. Check the filter name and that its plugin is enabled.",
        )
        return value

    def _media_tokens(self, token_data: TokenData) -> str:
        if token_data.bracket_token == Tokens.EDITION.token:
            return self._edition(token_data)

        elif token_data.bracket_token == Tokens.CUT.token:
            return self._cut(token_data)

        elif token_data.bracket_token == Tokens.FRAME_SIZE.token:
            return self._frame_size(token_data)

        elif token_data.bracket_token == Tokens.HYBRID.token:
            return self._hybrid(token_data)

        elif token_data.bracket_token == Tokens.LOCALIZATION.token:
            return self._localization(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_BITRATE.token:
            return self._audio_bitrate(token_data, False)

        elif token_data.bracket_token == Tokens.AUDIO_BITRATE_FORMATTED.token:
            return self._audio_bitrate(token_data, True)

        elif token_data.bracket_token == Tokens.AUDIO_CHANNEL_S.token:
            return self._audio_channel_s(token_data, True)

        elif token_data.bracket_token == Tokens.AUDIO_CHANNEL_S_I.token:
            return self._audio_channel_s(token_data, False)

        elif token_data.bracket_token == Tokens.AUDIO_CHANNEL_S_LAYOUT.token:
            return self._audio_channel_s_layout(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_CODEC.token:
            return self._audio_codec(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_CODEC_NO_ATMOS.token:
            return self._audio_codec_no_atmos(token_data)

        elif token_data.bracket_token == Tokens.ATMOS.token:
            return self._atmos(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_COMMERCIAL_NAME.token:
            return self._audio_commercial_name(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_COMPRESSION.token:
            return self._audio_compression(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_FORMAT_INFO.token:
            return self._audio_format_info(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_1_FULL.token:
            return self._audio_language_1_full(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_1_ISO_639_1.token:
            return self._audio_language_1_iso_639_x(1, token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_1_ISO_639_2.token:
            return self._audio_language_1_iso_639_x(2, token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_2_ISO_639_1.token:
            return self._audio_language_2_all_iso_639_x(1, False, token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_2_ISO_639_2.token:
            return self._audio_language_2_all_iso_639_x(2, False, token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_ALL_ISO_639_1.token:
            return self._audio_language_2_all_iso_639_x(1, True, token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_ALL_ISO_639_2.token:
            return self._audio_language_2_all_iso_639_x(2, True, token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_ALL_FULL.token:
            return self._audio_language_all_full(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_DUAL.token:
            return self._audio_language_dual(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_LANGUAGE_MULTI.token:
            return self._audio_language_multi(token_data)

        elif token_data.bracket_token == Tokens.AUDIO_SAMPLE_RATE.token:
            return self._audio_sample_rate(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_3D.token:
            return self._3d(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_BIT_DEPTH_SPACE.token:
            return self._video_bit_depth_x(False, token_data)

        elif token_data.bracket_token == Tokens.VIDEO_BIT_DEPTH_DASH.token:
            return self._video_bit_depth_x(True, token_data)

        elif token_data.bracket_token == Tokens.VIDEO_CODEC.token:
            return self._video_codec(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_DYNAMIC_RANGE.token:
            return self._video_dynamic_range(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_DYNAMIC_RANGE_TYPE.token:
            return self._video_dynamic_range_type(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_DYNAMIC_RANGE_TYPE_INC_SDR.token:
            return self._video_dynamic_range_type(token_data, include_sdr=True)

        elif (
            token_data.bracket_token
            == Tokens.VIDEO_DYNAMIC_RANGE_TYPE_INC_SDR_OVER_1080.token
        ):
            return self._video_dynamic_range_type(
                token_data, include_sdr=True, uhd_only=True
            )

        elif token_data.bracket_token == Tokens.VIDEO_FORMAT.token:
            return self._video_format(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_HEIGHT.token:
            return self._video_height(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_LANGUAGE_FULL.token:
            return self._video_language_full(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_LANGUAGE_ISO_639_1.token:
            return self._video_language_iso_639_x(1, token_data)

        elif token_data.bracket_token == Tokens.VIDEO_LANGUAGE_ISO_639_2.token:
            return self._video_language_iso_639_x(2, token_data)

        elif token_data.bracket_token == Tokens.VIDEO_WIDTH.token:
            return self._video_width(token_data)

        elif token_data.bracket_token == Tokens.TITLE.token:
            return self._title(token_data)

        elif token_data.bracket_token == Tokens.TITLE_CLEAN.token:
            return self._title_clean(token_data)

        elif token_data.bracket_token == Tokens.TITLE_EXACT.token:
            return self._title_exact(token_data)

        elif token_data.bracket_token == Tokens.IMDB_ID.token:
            return self._imdb_id(token_data)

        elif token_data.bracket_token == Tokens.ORIGINAL_TITLE.token:
            return self._original_title(token_data)

        elif token_data.bracket_token == Tokens.ORIGINAL_TITLE_FALLBACK_TITLE.token:
            return self._original_title(token_data, True)

        elif (
            token_data.bracket_token == Tokens.ORIGINAL_TITLE_FALLBACK_TITLE_CLEAN.token
        ):
            return self._original_title(token_data, True, True)

        elif token_data.bracket_token == Tokens.TMDB_ID.token:
            return self._tmdb_id(token_data)

        elif token_data.bracket_token == Tokens.TVDB_ID.token:
            return self._tvdb_id(token_data)

        elif token_data.bracket_token == Tokens.MAL_ID.token:
            return self._mal_id(token_data)

        elif token_data.bracket_token == Tokens.ORIGINAL_FILENAME.token:
            return self._original_filename(token_data)

        elif token_data.bracket_token == Tokens.ORIGINAL_LANGUAGE.token:
            return self._original_language(token_data)

        elif token_data.bracket_token == Tokens.ORIGINAL_LANGUAGE_ISO_639_1.token:
            return self._original_language(token_data, 1)

        elif token_data.bracket_token == Tokens.ORIGINAL_LANGUAGE_ISO_639_2.token:
            return self._original_language(token_data, 2)

        elif token_data.bracket_token == Tokens.RELEASE_GROUP.token:
            return self._release_group(token_data)

        elif token_data.bracket_token == Tokens.RELEASE_DATE.token:
            return self._release_date(token_data)

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

        elif token_data.bracket_token == Tokens.STREAMING_SERVICE.token:
            return self._streaming_service(token_data)

        elif token_data.bracket_token == Tokens.AIR_DATE.token:
            return self._air_date(token_data)

        elif token_data.bracket_token == Tokens.SEASON_NUMBER.token:
            return self._season_number(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_AIR_DATE.token:
            return self._episode_air_date(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_NUMBER.token:
            return self._episode_number(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_NUMBER_ABSOLUTE.token:
            return self._episode_number_absolute(token_data)

        elif token_data.bracket_token == Tokens.END_EPISODE_NUMBER.token:
            return self._end_episode_number(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_TITLE.token:
            return self._episode_title(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_TITLE_CLEAN.token:
            return self._episode_title_clean(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_TITLE_EXACT.token:
            return self._episode_title_exact(token_data)

        return ""

    def _nfo_tokens(self, token_data: TokenData) -> str | Sequence[Any] | None:
        if token_data.bracket_token == Tokens.MEDIA_TYPE.token:
            return self._media_type(token_data)

        elif token_data.bracket_token == Tokens.IS_ANIME.token:
            return self._is_anime(token_data)

        elif token_data.bracket_token == Tokens.CHAPTER_TYPE.token:
            return self._chapter_type(token_data)

        elif token_data.bracket_token == Tokens.FORMAT_PROFILE.token:
            return self._format_profile(token_data)

        elif token_data.bracket_token == Tokens.MEDIA_FILE.token:
            return self._media_file(token_data)

        elif token_data.bracket_token == Tokens.MEDIA_FILE_NO_EXT.token:
            return self._media_file_no_ext(token_data)

        elif token_data.bracket_token == Tokens.SOURCE_FILE.token:
            return self._source_file(token_data)

        elif token_data.bracket_token == Tokens.SOURCE_FILE_NO_EXT.token:
            return self._source_file_no_ext(token_data)

        elif token_data.bracket_token == Tokens.MEDIA_INFO.token:
            return self._media_info(token_data)

        elif token_data.bracket_token == Tokens.MEDIA_INFO_SHORT.token:
            return self._media_info_short(token_data)

        elif token_data.bracket_token == Tokens.VIDEO_BIT_RATE.token:
            return self._video_bit_rate(token_data, False)

        elif token_data.bracket_token == Tokens.VIDEO_BIT_RATE_NUM_ONLY.token:
            return self._video_bit_rate(token_data, True)

        elif token_data.bracket_token == Tokens.REPACK.token:
            return self._repack(token_data)

        elif token_data.bracket_token == Tokens.REPACK_N.token:
            return self._repack_n(token_data)

        elif token_data.bracket_token == Tokens.REPACK_REASON.token:
            return self._repack_reason(token_data)

        elif token_data.bracket_token == Tokens.SCREEN_SHOTS.token:
            return self._screen_shots(token_data)

        elif token_data.bracket_token == Tokens.SCREEN_SHOTS_COMPARISON.token:
            return self._screen_shots_comparison(token_data)

        elif token_data.bracket_token == Tokens.SCREEN_SHOTS_EVEN_OJB.token:
            return self._screen_shots_even_obj()

        elif token_data.bracket_token == Tokens.SCREEN_SHOTS_ODD_OBJ.token:
            return self._screen_shots_odd_obj()

        elif token_data.bracket_token == Tokens.SCREEN_SHOTS_EVEN_STR.token:
            return self._screen_shots_even_str()

        elif token_data.bracket_token == Tokens.SCREEN_SHOTS_ODD_STR.token:
            return self._screen_shots_odd_str()

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

        elif token_data.bracket_token == Tokens.EPISODE_MEDIAINFO.token:
            return self._episode_mediainfo(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_METADATA.token:
            return self._episode_metadata(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_METADATA_MEDIAINFO.token:
            return self._episode_metadata_mediainfo(token_data)

        elif token_data.bracket_token == Tokens.TOTAL_SEASONS.token:
            return self._total_seasons(token_data)

        elif token_data.bracket_token == Tokens.TOTAL_EPISODES.token:
            return self._total_episodes(token_data)

        # nfo forge specific tokens
        elif token_data.bracket_token == Tokens.PROGRAM_INFO.token:
            return self._program_info(token_data)

        elif token_data.bracket_token == Tokens.SHARED_WITH.token:
            return self._shared_with(token_data, SharedWithType.BASIC)

        elif token_data.bracket_token == Tokens.SHARED_WITH_BBCODE.token:
            return self._shared_with(token_data, SharedWithType.BBCODE)

        elif token_data.bracket_token == Tokens.SHARED_WITH_HTML.token:
            return self._shared_with(token_data, SharedWithType.HTML)

        return ""

    def _format_token_string(
        self, filled_tokens: dict[str, tuple[str, str]]
    ) -> str | None:
        """Substitute resolved values back into the token string.

        ``filled_tokens`` maps each token's literal occurrence -- the exact
        ``{token}``/``{token|filter}``/``{:opt=x:token}`` text as written -- to
        its base token name and its resolved value. Keying on the occurrence is
        what lets the same token appear twice with different filters and keep
        two distinct values.
        """
        try:
            formatted_title = self.token_string

            # '*title_clean' values must not go through _colon_replace -- the
            # clean rules have already dealt with punctuation. Park them behind
            # a colon-free sentinel rather than substituting them afterwards:
            # an occurrence can carry its own `:opt=` wrapper, and leaving that
            # text in place while the colon pass runs would rewrite the very
            # colons the substitution still has to match on.
            clean_values: dict[str, str] = {}
            for occurrence, (name, value) in filled_tokens.items():
                if "title_clean" in name:  # covers all '*title_clean' tokens
                    sentinel = f"{_TITLE_CLEAN_SENTINEL}{len(clean_values)}{_TITLE_CLEAN_SENTINEL}"
                    clean_values[sentinel] = value
                    formatted_title = formatted_title.replace(occurrence, sentinel)

            for occurrence, (name, value) in filled_tokens.items():
                if "title_clean" not in name:
                    formatted_title = formatted_title.replace(occurrence, value)

            # One pass over the fully substituted string. _colon_replace is a
            # plain str.replace, so running it once here is equivalent to the
            # per-substitution pass this used to make -- and it can no longer
            # corrupt a token that has not been substituted yet.
            formatted_title = self._colon_replace(self.colon_replace, formatted_title)

            for sentinel, value in clean_values.items():
                formatted_title = formatted_title.replace(sentinel, value)

            # remove unfilled tokens if needed
            formatted_title = self._remove_unfilled_tokens(formatted_title)

            # apply final formatting
            if self.preserve_literal_formatting:
                return formatted_title
            # if filename mode
            if self.file_name_mode:
                formatted_file_name = re.sub(r"\s{1,}", ".", formatted_title)
                formatted_file_name = re.sub(r"\.{2,}", ".", formatted_file_name)
                formatted_file_name = re.sub(r":\.", ".", formatted_file_name)
                formatted_file_name = re.sub(r"\.-\.|\.-|-\.", "-", formatted_file_name)
                # Sanitize metadata/user-token output before it becomes a path
                # component; this also rejects empty and reserved device names.
                return self._sanitize_filename(formatted_file_name)
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
        except (ValueError, KeyError, IndexError) as error:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Failed to format token string '{self.token_string}': "
                f"{type(error).__name__}: {error}",
            )
            return None

    def _sanitize_filename(self, filename: str) -> str | None:
        """Return a safe single filename component with the input suffix.

        Flat token values can come from metadata, user tokens, or release-group
        overrides, so they cannot be assumed to have gone through the editable
        title-clean rules. Replacing reserved characters here keeps them from
        becoming path separators and makes the final rename target portable to
        Windows. Returning ``None`` for an empty or reserved device name lets
        the rename page reject the result before it creates a plan.

        ``append_suffix`` is False for a folder name, which has no extension.
        The suffix then costs nothing against the length budget either, so a
        folder is not capped short for an extension it never carries.
        """
        suffix = self.media_input.suffix if self.append_suffix else ""
        filename = _INVALID_FILENAME_CHARS.sub(".", filename)
        filename = re.sub(r"\.{2,}", ".", filename)
        filename = filename.strip(". -")
        if not filename:
            return None

        device_stem = filename.split(".", maxsplit=1)[0].upper()
        if device_stem in _RESERVED_DEVICE_NAMES or re.fullmatch(
            r"(?:COM|LPT)[1-9]", device_stem
        ):
            return None

        max_filename_length = 255 - len(suffix)
        if max_filename_length <= 0:
            return None
        filename = filename[:max_filename_length].rstrip(". ")
        return f"{filename}{suffix}" if filename else None

    def _remove_unfilled_tokens(self, formatted_title: str) -> str:
        if self.unfilled_token_mode == UnfilledTokenRemoval.KEEP:
            return formatted_title
        elif self.unfilled_token_mode == UnfilledTokenRemoval.TOKEN_ONLY:
            return re.sub(r"{[^{}]*}", "", formatted_title, flags=re.MULTILINE)
        elif self.unfilled_token_mode == UnfilledTokenRemoval.ENTIRE_LINE:
            return re.sub(r"(\b.*?{.+}*?\n)", "", formatted_title, flags=re.MULTILINE)
        else:
            raise InvalidTokenError("Invalid 'unfilled_token_mode'")

    def _air_date(self, token_data: TokenData) -> str:
        """Series-level first-aired date (parallels the movie {release_date} token)."""
        if self.media_search_obj.media_type is not MediaType.SERIES:
            return ""
        tvdb_data = self.media_search_obj.tvdb_data
        if not tvdb_data:
            return ""
        return self._optional_user_input(tvdb_data.get("firstAired", ""), token_data)

    def _edition(self, token_data: TokenData) -> str:
        """The release's edition, as the user accepted it.

        Stage 1 detects editions from EDITION_INFO plus any plugin-supplied
        entries; stage 2 puts what the user left in the control into the
        overrides. Nothing is inferred here, because a cleared control and
        an undetected edition are indistinguishable at this point -- falling
        back to a detection of our own would make the control disagree with
        the output, which is the pattern this design removes.
        """
        if self.edition_override:
            return self._optional_user_input(self.edition_override, token_data)
        return self._optional_user_input("", token_data)

    def _cut(self, token_data: TokenData) -> str:
        """Subset of {edition} covering only "Cut"-classified entries (see
        CUT_EDITION_NAMES) -- e.g. Director's Cut/Extended/Unrated, which stay
        in a title that must follow Aither's naming guide, unlike
        marketing-style Editions (Criterion, Deluxe, Special, ...).

        Plugin-contributed entries (src.plugins.api.CustomEditionContribution)
        are recognized alongside the built-in table -- `custom_edition_info`
        for the entries themselves, `custom_cut_names` for which of those
        count as a Cut.

        The edition is still classified rather than emitted verbatim: one
        that is not a known Cut is dropped, because an unrecognized string
        cannot confidently be called one and the guide's own default for an
        omitted Cut is "assumed Theatrical".

        Both carriers of the user's edition are read. {edition} is satisfied
        by either -- an override token short-circuits its handler before it
        runs -- and this token has no override of its own to be satisfied by,
        so reading one carrier would blank it wherever the other is used.
        The rename page carries the edition in `override_tokens`; the upload
        path passes `edition_override`. Same precedence as {edition}: the
        override token wins.
        """
        all_edition_info = (*EDITION_INFO, *self.custom_edition_info)
        all_cut_names = {*CUT_EDITION_NAMES, *self.custom_cut_names}
        edition = (self.override_tokens or {}).get("edition") or self.edition_override

        if edition:
            for rename_normalize in all_edition_info:
                if rename_normalize.normalized not in all_cut_names:
                    continue
                for regex_str in rename_normalize.re_gex:
                    if re.search(regex_str, edition, flags=re.I):
                        return self._optional_user_input(
                            rename_normalize.normalized, token_data
                        )
        return self._optional_user_input("", token_data)

    def _frame_size(self, token_data: TokenData) -> str:
        """IMAX / Open Matte, as the user accepted it.

        Detected in stage 1 from FRAME_SIZE_INFO. Nothing is inferred here,
        for the same reason as {edition}.
        """
        if self.frame_size_override:
            return self._optional_user_input(self.frame_size_override, token_data)
        return self._optional_user_input("", token_data)

    def _hybrid(self, token_data: TokenData) -> str:
        # Stage 1 detects this; an accepted claim arrives as an override.
        return self._optional_user_input("", token_data)

    def _localization(self, token_data: TokenData) -> str:
        # Stage 1 detects Dubbed/Subbed from LOCALIZATION_INFO; an accepted
        # claim arrives as an override.
        return self._optional_user_input("", token_data)

    def _audio_bitrate(self, token_data: TokenData, formatted: bool) -> str:
        bitrate = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            a_track = self.media_info_obj.audio_tracks[0]
            if a_track and not formatted:
                bitrate = str(a_track.bit_rate) if a_track.bit_rate else ""
            elif a_track and formatted:
                bitrate = a_track.other_bit_rate[0] if a_track.other_bit_rate else ""

        return self._optional_user_input(bitrate, token_data)

    def _audio_channel_s(self, token_data: TokenData, convert_to_layout: bool) -> str:
        # Only audio_tracks[0] is read here, matching every other single-value
        # audio token in this class (bitrate, layout, codec, sample rate,
        # etc.): there's no single channel count that could represent
        # multiple tracks with differing layouts, so the first/primary track
        # is treated as canonical. Tokens that need to reflect every track
        # (dual/multi audio detection, combined language lists) iterate
        # `audio_tracks` instead -- see `_audio_language_dual` and
        # `_audio_language_multi` below.
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

    def _audio_channel_s_layout(self, token_data: TokenData) -> str:
        layout = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_channel_layout = self.media_info_obj.audio_tracks[0].channel_layout
            if mi_channel_layout:
                layout = mi_channel_layout

        return self._optional_user_input(layout, token_data)

    def _resolved_audio_codec(self) -> str:
        """Audio codec for the primary file, computed once per instance (conventions
        file when MediaInfo is available, guessit otherwise).

        ``audio_codec_no_atmos`` and ``atmos`` are derived views of
        ``audio_codec``.  The rename wizard exposes the latter in its editable
        token grid, so its override must be the source for all three views.
        Otherwise a filename can reflect a hand-corrected codec while tracker
        templates that split Atmos out (notably Aither and LST) silently keep
        the detected value.
        """
        if self._audio_codec_cache is None:
            overridden_codec = (
                self.override_tokens.get("audio_codec")
                if self.override_tokens is not None
                else None
            )
            if overridden_codec is not None:
                codec = overridden_codec
            else:
                # guessit can hand back a list here; it already reached output via
                # f-string interpolation downstream, so coercing early is a no-op
                codec = str(self.guess_name.get("audio_codec", "") or "")
            if (
                overridden_codec is None
                and self.media_info_obj
                and self.media_info_obj.audio_tracks
            ):
                audio_codecs = AudioCodecs()
                # The bundled conventions file is a runtime asset in both source and frozen builds.
                audio_convention_path = Path(
                    RUNTIME_DIR / "config" / "audio_conventions" / "default.json"
                )
                codec = audio_codecs.get_codec(
                    self.media_info_obj.audio_tracks[0],
                    audio_convention_path,
                )
            self._audio_codec_cache = codec
        return self._audio_codec_cache

    def _audio_codec(self, token_data: TokenData) -> str:
        return self._optional_user_input(self._resolved_audio_codec(), token_data)

    def _audio_codec_no_atmos(self, token_data: TokenData) -> str:
        # trailing strip covers a conventions file that puts the word first
        codec = self._ATMOS_RE.sub("", self._resolved_audio_codec()).strip()
        return self._optional_user_input(codec, token_data)

    def _atmos(self, token_data: TokenData) -> str:
        # reads the same resolved codec the other two audio tokens use, so the
        # three can never disagree. The empty case still routes through
        # _optional_user_input so that any filters on the token are applied and
        # its `:opt=` wrapper is dropped along with the missing value.
        atmos = "Atmos" if self._ATMOS_RE.search(self._resolved_audio_codec()) else ""
        return self._optional_user_input(atmos, token_data)

    def _audio_commercial_name(self, token_data: TokenData) -> str:
        commercial_name = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_commercial_name = self.media_info_obj.audio_tracks[0].commercial_name
            if mi_commercial_name:
                commercial_name = mi_commercial_name

        return self._optional_user_input(commercial_name, token_data)

    def _audio_compression(self, token_data: TokenData) -> str:
        compression = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_compression = self.media_info_obj.audio_tracks[0].compression_mode
            if mi_compression:
                compression = mi_compression

        return self._optional_user_input(compression, token_data)

    def _audio_format_info(self, token_data: TokenData) -> str:
        format_info = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_format_info = self.media_info_obj.audio_tracks[0].channel_s
            if mi_format_info:
                format_info = mi_format_info

        return self._optional_user_input(format_info, token_data)

    def _audio_language_1_full(self, token_data: TokenData) -> str:
        language = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            detect_language_code = get_language_mi(self.media_info_obj.audio_tracks[0])
            if detect_language_code:
                detect_language = get_full_language_str(detect_language_code)
                if detect_language:
                    language = detect_language

        return self._optional_user_input(language, token_data)

    def _audio_language_1_iso_639_x(self, char_code: int, token_data: TokenData) -> str:
        language = self.guessit_language
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            detect_language = get_language_mi(
                self.media_info_obj.audio_tracks[0], char_code
            )
            if detect_language:
                language = detect_language

        return self._optional_user_input(language, token_data)

    def _audio_language_2_all_iso_639_x(
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
            language = get_language_str(guess_lang, char_code) or ""

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

    def _audio_language_all_full(self, token_data: TokenData) -> str:
        all_lang = ""
        guess_lang = self.guessit_language
        if isinstance(guess_lang, list):
            language_s = {
                lang for x in guess_lang if (lang := get_full_language_str(x))
            }
            if language_s:
                if len(language_s) == 1:
                    all_lang = next(iter(language_s))
                else:
                    all_lang = " ".join(language_s)
        else:
            all_lang = get_full_language_str(guess_lang) or ""

        if self.media_info_obj and self.media_info_obj.audio_tracks:
            language_set = {
                lang
                for track in self.media_info_obj.audio_tracks
                if (lang := get_language_mi(track))
            }

            if language_set:
                if len(language_set) == 1:
                    all_lang = get_full_language_str(next(iter(language_set))) or ""
                else:
                    all_lang = " ".join(
                        [get_full_language_str(x) or "" for x in language_set]
                    )

        return self._optional_user_input(all_lang, token_data)

    def _audio_language_dual(self, token_data: TokenData) -> str:
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

    def _audio_language_multi(self, token_data: TokenData) -> str:
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

    def _audio_sample_rate(self, token_data: TokenData) -> str:
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

    def _video_bit_depth_x(self, dash: bool, token_data: TokenData) -> str:
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

    def _video_codec(self, token_data: TokenData) -> str:
        current_quality = self._get_source_quality()
        codec = self._get_video_codec(current_quality)
        return self._optional_user_input(codec, token_data)

    def _get_video_codec(self, quality: QualitySelection) -> str:
        """Get video codec with source-aware logic."""
        parse_guessit = self._guessit_codec()
        parse_media_info = self._mediainfo_codec(quality)

        # prefer MediaInfo result, fallback to guessit
        if parse_media_info:
            return parse_media_info
        return parse_guessit if parse_guessit else ""

    def _guessit_codec(self) -> str:
        """Extract codec from guessit."""
        video_codec = str(self.guess_name.get("video_codec", ""))
        if video_codec in ["H.264", "H.265"]:
            video_codec = video_codec.replace("H.", "x")
        return video_codec

    def _mediainfo_codec(self, quality: QualitySelection) -> str:
        """Extract codec from MediaInfo with source awareness."""
        if not (self.media_info_obj and self.media_info_obj.video_tracks):
            return ""

        # a remux keeps the container's codec name (AVC/HEVC); only an encode
        # is reported as x264/x265
        is_remux = bool(self._detect_remux())

        track = self.media_info_obj.video_tracks[0]
        detect_video_codec = track.format

        if not detect_video_codec:
            return ""

        if detect_video_codec == "AV1":
            return str(track.format)
        elif detect_video_codec == "AVC":
            if is_remux:
                return "AVC"
            elif quality in (QualitySelection.WEB_DL, QualitySelection.HDTV):
                return "H.264"
            else:
                return "x264"
        elif detect_video_codec == "HEVC":
            if is_remux:
                return "HEVC"
            elif quality in (QualitySelection.WEB_DL, QualitySelection.HDTV):
                return "H.265"
            else:
                return "x265"
        elif detect_video_codec == "MPEG Video":
            return self._mpeg_codec(track)
        elif detect_video_codec == "VC-1":
            return str(track.format)
        elif detect_video_codec in ["VP8", "VP9"]:
            return str(track.format)

        return ""

    def _mpeg_codec(self, track: Track) -> str:
        """Get MPEG codec name."""
        if track.format_version:
            version_num = re.search(r"\d", track.format_version)
            if version_num and int(version_num.group()) > 1:
                return f"MPEG-{version_num.group()}"
        return "MPEG"

    def _video_dynamic_range(self, token_data: TokenData) -> str:
        hdr_string = ""

        if (
            self.video_dynamic_range
            and self.media_info_obj
            and self.media_info_obj.video_tracks
        ):

            def normalize(s: str) -> str:
                return s.replace(" ", "").lower()

            fallback_names: dict[HdrType, str] = {
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
            res_map: dict[int, ResolutionKey] = {
                720: "720p",
                1080: "1080p",
                2160: "2160p",
            }
            res_key: ResolutionKey | None = next(
                (v for k, v in res_map.items() if abs(resolution - k) < 100), None
            )

            if not res_key or not self.video_dynamic_range.resolutions.get(
                res_key, False
            ):
                return self._optional_user_input("", token_data)

            # get data from dict
            enabled_hdr_types: list[HdrType] = [
                k for k, v in self.video_dynamic_range.hdr_types.items() if v
            ]
            custom_strings = self.video_dynamic_range.custom_strings
            enabled_hdr_types_sorted: list[HdrType] = sorted(
                enabled_hdr_types, key=len, reverse=True
            )
            norm_enabled_types: dict[str, HdrType] = {
                normalize(k): k for k in enabled_hdr_types_sorted
            }

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
            # track if we matched a specific HDR format (not just PQ/HLG)
            matched_hdr_format = False
            for candidate in mi_candidates:
                norm_candidate = normalize(candidate)
                if norm_candidate in norm_enabled_types:
                    hdr_type = norm_enabled_types[norm_candidate]
                    custom = custom_strings.get(hdr_type, "").strip()
                    hdr_string = custom or fallback_names.get(hdr_type, hdr_type)
                    # HDR10, HDR10+, DV formats use PQ transfer - don't append PQ later
                    if candidate not in ("PQ", "HLG"):
                        matched_hdr_format = True
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
            # only do this if we didn't match a specific HDR format (HDR10, HDR10+, DV, etc.)
            # since those formats already use PQ transfer characteristics
            if not matched_hdr_format:
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

    def _resolution_over_1080(self) -> bool:
        """Whether the release is above 1080p.

        An unparseable or missing resolution answers False rather than
        raising. ``_detect_resolution`` falls back to guessit's
        ``screen_size``, which carries the scan letter ("1080p"), and an
        int() over that raised out of token rendering.
        """
        resolution = self._detect_resolution(self.media_info_obj, True)
        leading_digits = re.match(r"\d+", resolution)
        if not leading_digits:
            return False
        return int(leading_digits.group()) > 1080

    def _video_dynamic_range_type(
        self, token_data: TokenData, include_sdr: bool = False, uhd_only: bool = False
    ) -> str:
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
            elif include_sdr and (not uhd_only or self._resolution_over_1080()):
                # `uhd_only` gates the SDR spelling alone, not the whole
                # token: 2160p is usually HDR so SDR is worth stating there,
                # while 1080p is SDR by default and does not need it. Gating
                # the method entrypoint suppressed DV, HDR10Plus, HDR, HLG
                # and PQ at 1080p as well.
                dynamic_range_type = "SDR"
            else:
                dynamic_range_type = ""

        return self._optional_user_input(dynamic_range_type, token_data)

    def _video_format(self, token_data: TokenData) -> str:
        v_format = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            track = self.media_info_obj.video_tracks[0]
            v_format = str(track.format) if track.format else ""

        return self._optional_user_input(v_format, token_data)

    def _video_height(self, token_data: TokenData) -> str:
        height = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            track = self.media_info_obj.video_tracks[0]
            height = str(track.height) if track.height else ""

        return self._optional_user_input(height, token_data)

    def _video_language_full(self, token_data: TokenData) -> str:
        language = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            detect_language_code = get_language_mi(self.media_info_obj.video_tracks[0])
            if detect_language_code:
                detect_language = get_full_language_str(detect_language_code)
                if detect_language:
                    language = detect_language

        return self._optional_user_input(language, token_data)

    def _video_language_iso_639_x(self, char_code: int, token_data: TokenData) -> str:
        detect_language = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            track = self.media_info_obj.video_tracks[0]
            detect_language = get_language_mi(track, char_code) or ""

        return self._optional_user_input(detect_language, token_data)

    def _video_width(self, token_data: TokenData) -> str:
        width = ""
        if self.media_info_obj and self.media_info_obj.video_tracks:
            track = self.media_info_obj.video_tracks[0]
            width = str(track.width) if track.width else ""

        return self._optional_user_input(width, token_data)

    def _title(self, token_data: TokenData) -> str:
        title = (
            self.media_search_obj.title
            if self.media_search_obj.title
            else self.guessit_title
        )
        title = self._title_formatting_standard(title)
        return self._optional_user_input(title, token_data)

    def _title_clean(self, token_data: TokenData) -> str:
        title = (
            self.media_search_obj.title
            if self.media_search_obj.title
            else self.guessit_title
        )
        title = self._title_formatting_cleaned(title, self.title_clean_rules)
        return self._optional_user_input(title, token_data)

    def _title_exact(self, token_data: TokenData) -> str:
        title = (
            self.media_search_obj.title
            if self.media_search_obj.title
            else self.guessit_title
        )
        return self._optional_user_input(title, token_data)

    def _imdb_id(self, token_data: TokenData) -> str:
        imdb_id = self.media_search_obj.imdb_id if self.media_search_obj.imdb_id else ""
        return self._optional_user_input(imdb_id, token_data)

    def _original_title(
        self,
        token_data: TokenData,
        fallback: bool = False,
        cleaned_fallback: bool = False,
    ) -> str:
        if self.media_search_obj.original_title:
            original_title = self.media_search_obj.original_title
            return self._optional_user_input(original_title, token_data)

        # The base token has no selected-title fallback.
        if not fallback:
            return ""

        original_title = self.media_search_obj.title or ""
        if original_title and cleaned_fallback:
            original_title = self._title_formatting_cleaned(
                original_title, self.title_clean_rules
            )
        elif original_title:
            original_title = self._title_formatting_standard(original_title)
        return self._optional_user_input(original_title, token_data)

    def _tmdb_id(self, token_data: TokenData) -> str:
        tmdb_id = self.media_search_obj.tmdb_id if self.media_search_obj.tmdb_id else ""
        return self._optional_user_input(tmdb_id, token_data)

    def _tvdb_id(self, token_data: TokenData) -> str:
        tvdb_id = self.media_search_obj.tvdb_id if self.media_search_obj.tvdb_id else ""
        return self._optional_user_input(tvdb_id, token_data)

    def _mal_id(self, token_data: TokenData) -> str:
        mal_id = self.media_search_obj.mal_id if self.media_search_obj.mal_id else ""
        return self._optional_user_input(mal_id, token_data)

    def _original_filename(self, token_data: TokenData) -> str:
        # For series, use directory name or episode filename based on context
        if self.is_series_mode and self.media_input_obj.input_path:
            if self.media_input_obj.input_is_directory():
                return self._optional_user_input(
                    self.media_input_obj.input_path.name, token_data
                )

        return self._optional_user_input(self.primary_file.stem, token_data)

    def _original_language(self, token_data: TokenData, char: int | None = None) -> str:
        lang = ""
        # if media type is movie we'll use tmdb
        if self.media_search_obj.media_type is MediaType.MOVIE:
            tmdb_data = self.media_search_obj.tmdb_data
            if not tmdb_data:
                return ""
            lang = tmdb_data.get("original_language", "")

        # if not a movie we'll use tvdb
        else:
            tvdb_data = self.media_search_obj.tvdb_data
            if not tvdb_data:
                return ""
            lang = tvdb_data.get("originalLanguage", "")

        # convert lang to the required format
        if not lang:
            return ""
        if char is None:
            return self._optional_user_input(
                get_full_language_str(lang) or "", token_data
            )
        elif char == 1:
            return self._optional_user_input(
                get_language_str(lang, 1) or "", token_data
            )
        else:
            return self._optional_user_input(
                get_language_str(lang, 2) or "", token_data
            )

    def _release_group(self, token_data: TokenData) -> str:
        release_group = str(self.guess_name.get("release_group", ""))
        return self._optional_user_input(release_group.lstrip("-"), token_data)

    def _release_date(self, token_data: TokenData) -> str:
        if self.media_search_obj.media_type is not MediaType.MOVIE:
            return ""
        if not self.media_search_obj.tmdb_data:
            return ""
        return self._optional_user_input(
            self.media_search_obj.tmdb_data.get("release_date", ""), token_data
        )

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
        return self._optional_user_input(self._detect_remux(), token_data)

    def _detect_remux(self) -> str:
        """Return "REMUX" when this release is one, otherwise "".

        The single answer every caller uses -- the `{remux}` token, the codec
        picker (a remux keeps the container codec name, AVC/HEVC, where an
        encode reports x264/x265), and the `only_if(remux)`/`unless(remux)`
        filters that pick a component order. They used to disagree: the codec
        picker looked only at the override, so a remux with no override was
        given an encode's codec name.
        """
        if self.override_tokens and "remux" in self.override_tokens:
            return self.override_tokens["remux"]
        return ""

    def _re_release(self, token_data: TokenData) -> str:
        # Stage 1 detects this; an accepted claim arrives as an override and
        # short-circuits before this handler runs.
        return self._optional_user_input("", token_data)

    def _get_source_quality(self) -> QualitySelection:
        """Get the detected source quality."""
        # check if source is being overridden first
        if self.override_tokens and "source" in self.override_tokens:
            override_source = self.override_tokens["source"].strip()
            legacy = _LEGACY_SOURCE_OVERRIDES.get(override_source.lower())
            if legacy is not None:
                return legacy
            try:
                # QualitySelection matches case-insensitively on both the value
                # and the member name, so this covers every spelling the
                # wizard's Quality combo can produce without a parallel list
                # here that a new member could be left out of.
                return QualitySelection(override_source)
            except ValueError:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Ignoring unrecognized source override '{override_source}'; "
                    "falling back to detection.",
                )

        # base source
        source_quality = self.guess_name.get("source", "").lower()

        # if we have a source file as well use that instead
        if self.guess_source_name:
            check_source_file = self.guess_source_name.get("source", "").lower()
            if check_source_file:
                source_quality = check_source_file

        if "ultra hd blu-ray" in source_quality:
            source_quality = QualitySelection.UHD_BLURAY
        elif "blu-ray" in source_quality:
            source_quality = QualitySelection.BLURAY
        elif "dvd" in source_quality:
            source_quality = QualitySelection.DVD
        elif "hdtv" in source_quality:
            source_quality = QualitySelection.HDTV
        elif "web" in source_quality:
            # guessit reports `source: Web` for both and marks a rip with
            # `other: Rip`, so the distinction comes from its parse rather
            # than a second regex of our own over the filename. Quality is
            # always parsed and has no switch, so the detection stays -- it
            # just stops being a separate scan.
            source_other = self.guess_name.get("other", [])
            if isinstance(source_other, str):
                source_other = [source_other]
            if any(str(item).lower() == "rip" for item in source_other):
                source_quality = QualitySelection.WEB_RIP
            else:
                source_quality = QualitySelection.WEB_DL
        # if we can't detect we'll default to BluRay
        else:
            source_quality = QualitySelection.BLURAY

        if not source_quality or source_quality is QualitySelection.BLURAY:
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
                        source_quality = QualitySelection.BLURAY
                    elif video_format == "HEVC" and "HDR" in dynamic_range:
                        source_quality = QualitySelection.UHD_BLURAY
                elif resolution_value > 1080 and video_format == "HEVC":
                    source_quality = QualitySelection.UHD_BLURAY

        return source_quality

    def _source(self, token_data: TokenData) -> str:
        return self._optional_user_input(str(self._get_source_quality()), token_data)

    def _streaming_service(self, token_data: TokenData) -> str:
        """The service abbreviation, for web sources only.

        Both trackers that require this scope it to web content -- Aither's
        component table says "Web content only", and LST lists it as the
        *source* for WEB-DLs and WEBRips. Emitting it for a disc or an encode
        would put a service in a title that never came from one, so a
        non-web release resolves to nothing here.

        A user's explicit choice on the rename page never reaches this method:
        `_get_token_value` returns an override before the token is resolved, so
        picking a service by hand is always honoured.
        """
        if self._get_source_quality() not in (
            QualitySelection.WEB_DL,
            QualitySelection.WEB_RIP,
        ):
            return self._optional_user_input("", token_data)

        return self._optional_user_input(
            abbreviate_streaming_service(self.guess_name.get("streaming_service", "")),
            token_data,
        )

    def _season_number(self, token_data: TokenData) -> str:
        season = self._validate_int_var(self.season_number)
        if season is None:
            return self._optional_user_input("", token_data)

        # a multi-season pack (season_end set and higher than the start season)
        # renders a pre-padded "SS-Seend" range so a template's own |zfill(2) is
        # a harmless no-op; a single season renders exactly as it did before.
        season_end = self._validate_int_var(self.season_end)
        if season_end is not None and season_end != season:
            int_val = format_multi_season_range(season, season_end)
        else:
            int_val = str(season)

        return self._optional_user_input(int_val, token_data)

    def _episode_air_date(self, token_data: TokenData) -> str:
        """Air date of the selected episode.

        A file spanning several episodes keeps the date only when every
        episode in it aired that day -- a two-parter broadcast in one block.
        Where the episodes aired apart, or the end episode's date cannot be
        read, the token blanks rather than presenting the first episode's
        date as the date of the whole file.

        Unlike an episode title this is not simply dropped for a span. In
        the packaged daily templates the air date is the only episode
        identifier, with no SxxExx anywhere, so blanking unconditionally
        would trade a wrong claim for no claim. A date range is not an
        option either: ISO dates already contain hyphens, so
        "2024-01-15-2024-01-17" has no unambiguous reading.
        """
        get_info = self._verify_series_info()
        if not get_info:
            return ""

        season, episode = get_info
        type_id = self._selected_order_type_id(season, episode)
        episode_data = self._get_selected_episode_data(season, episode, type_id)
        air_date = episode_data.get("aired", "") if episode_data else ""

        # An absent date is not a date two episodes can share: the two
        # synthesized payloads spell it "" and None respectively, and
        # comparing them would call that a match.
        if not air_date:
            return self._optional_user_input("", token_data)

        end_episode = self._span_end_episode(season, episode)
        if end_episode is not None:
            end_data = self._get_selected_episode_data(season, end_episode, type_id)
            end_air_date = end_data.get("aired", "") if end_data else ""
            if not end_air_date or end_air_date != air_date:
                air_date = ""

        return self._optional_user_input(air_date, token_data)

    def _episode_number(self, token_data: TokenData) -> str:
        episode = self._validate_int_var(self.episode_number)
        if episode is None:
            return self._optional_user_input("", token_data)

        # multi-episode files render a style-aware span (already zero-padded);
        # single-episode files keep the raw start number so a template's own
        # |zfill filter still pads it exactly as before.
        designator = self._multi_episode_designator(episode)
        int_val = designator if designator is not None else str(episode)
        return self._optional_user_input(int_val, token_data)

    def _span_end_episode(self, season: int, episode: int) -> int | None:
        """Last episode number for a file spanning more than one episode.

        ``None`` when the file covers a single episode -- either no mapping
        row exists for it, or the row's ``episode_end`` is absent, invalid,
        or not greater than the start.

        This is the only definition of "span" in the class. Every token that
        behaves differently for a multi-episode file asks here, so the token
        that renders ``E01-03`` and the tokens that suppress an episode's
        own metadata cannot disagree about what they are looking at.
        """
        mapped_episode = self._get_mapped_episode_payload(season, episode)
        if not mapped_episode:
            return None

        end_episode = self._validate_int_var(mapped_episode.get("episode_end"))
        if end_episode is None or end_episode <= episode:
            return None
        return end_episode

    def _span_episode_list(self, season: int, episode: int) -> list[int]:
        """Every episode the file covers, lowest first.

        A row written before ``episode_list`` existed carries only the ends,
        so the range is derived. That is exact rather than approximate: the
        old code took the first and last of a *sorted* guessit list, so every
        span it could produce was contiguous. A stored list is preferred
        where present, because it is the only thing that can describe a
        non-contiguous file such as "S01E01E05".
        """
        mapped_episode = self._get_mapped_episode_payload(season, episode)
        if mapped_episode:
            stored = mapped_episode.get("episode_list")
            if isinstance(stored, list):
                numbers = [
                    value
                    for value in (self._validate_int_var(item) for item in stored)
                    if value is not None
                ]
                if numbers:
                    return sorted(numbers)

        end_episode = self._span_end_episode(season, episode)
        if end_episode is None:
            return [episode]
        return list(range(episode, end_episode + 1))

    def _multi_episode_designator(self, episode: int) -> str | None:
        """Render the season/episode span designator for a multi-episode file
        per the configured ``MultiEpisodeStyle``, or ``None`` when the file
        covers a single episode (the caller then emits the raw start number).

        Numbers are pre-padded to width 2 so a template's own ``|zfill(2)``
        on the composite string is a harmless no-op. Given season 1 and a
        file covering episodes 1 to 3 the styles render:

        - EXTEND (0):          ``01-02-03``
        - DUPLICATE (1):       ``01.S01E02.S01E03``
        - REPEAT (2):          ``01E02E03``
        - SCENE (3):           ``01-E02-E03``
        - RANGE (4):           ``01-03``
        - PREFIXED_RANGE (5):  ``01-E03``

        The split matches Sonarr's: the first four expand, naming every
        episode the file holds, and the last two state a range from its ends.
        A range cannot say which episodes between its ends are present, so
        the two read ``episode_end`` while the four read the episode list.
        """
        season = self._validate_int_var(self.season_number)
        if season is None:
            return None

        end_episode = self._span_end_episode(season, episode)
        if end_episode is None:
            return None

        start = f"{episode:02d}"
        style = self.multi_episode_style

        if style is MultiEpisodeStyle.RANGE:
            return f"{start}-{end_episode:02d}"
        if style is MultiEpisodeStyle.PREFIXED_RANGE:
            return f"{start}-E{end_episode:02d}"

        rest = self._span_episode_list(season, episode)[1:]
        if style is MultiEpisodeStyle.DUPLICATE:
            return ".".join([start, *(f"S{season:02d}E{num:02d}" for num in rest)])
        if style is MultiEpisodeStyle.REPEAT:
            return "".join([start, *(f"E{num:02d}" for num in rest)])
        if style is MultiEpisodeStyle.SCENE:
            return "-".join([start, *(f"E{num:02d}" for num in rest)])
        # EXTEND, and any future member
        return "-".join([start, *(f"{num:02d}" for num in rest)])

    def _absolute_number_for(
        self, season: int, episode: int, episode_order_type_id: Any | None
    ) -> int | None:
        """One episode's TVDB absolute number, or ``None`` when it has none.

        TVDB stores ``absoluteNumber: 0`` for non-anime episodes, which
        means "no absolute number" rather than zero.
        """
        episode_data = self._get_selected_episode_data(
            season, episode, episode_order_type_id
        )
        if not episode_data:
            return None
        absolute_number = self._validate_int_var(episode_data.get("absoluteNumber"))
        if not absolute_number:
            return None
        return absolute_number

    def _episode_number_absolute(self, token_data: TokenData) -> str:
        """Absolute episode number, or the absolute range for a span.

        A span renders "001-003" rather than the first episode's number.
        This is an identifier, so blanking it the way an episode title is
        blanked could leave a file with no episode in its name at all.

        Deliberately not styled by ``MultiEpisodeStyle``: Duplicate's
        "01.S01E03", Repeat's "01E03" and Scene's "01-E03" all embed
        season/episode structure that absolute numbering does not have. Both
        ends are padded to width 3, the width every packaged anime template
        applies via ``|zfill(3)``, so that filter is a no-op on the
        composite. A single episode still returns its raw unpadded number,
        keeping the asymmetry ``{episode_number}`` already has.

        Both ends come from the same source or neither does. The end
        episode's data is read through the start row's ordering, since no
        mapping row matches the end of a span. When either end has no
        absolute number, or the two are inconsistent with the span's length
        -- a TVDB gap, or an end episode a user typed by hand -- both
        components fall back to the plain episode numbers. A
        wrong-but-plausible absolute range is worse than a designator
        repeated from the token beside it.
        """
        get_info = self._verify_series_info()
        if not get_info:
            return ""

        season, episode = get_info
        type_id = self._selected_order_type_id(season, episode)
        start_absolute = self._absolute_number_for(season, episode, type_id)
        end_episode = self._span_end_episode(season, episode)

        if end_episode is None:
            absolute_number = start_absolute
            if absolute_number is None:
                absolute_number = self._validate_int_var(self.episode_number)
            return self._optional_user_input(
                str(absolute_number) if absolute_number is not None else "",
                token_data,
            )

        end_absolute = self._absolute_number_for(season, end_episode, type_id)
        if (
            start_absolute is not None
            and end_absolute is not None
            and end_absolute - start_absolute == end_episode - episode
        ):
            return self._optional_user_input(
                f"{start_absolute:03d}-{end_absolute:03d}", token_data
            )

        return self._optional_user_input(f"{episode:02d}-{end_episode:02d}", token_data)

    def _end_episode_number(self, token_data: TokenData) -> str:
        """Range end for a multi-episode file; blank when the file covers a
        single episode (``episode_end`` is None/absent or matches the start
        episode number)."""
        get_info = self._verify_series_info()
        if not get_info:
            return ""

        season, episode = get_info
        end_episode = None
        mapped_episode = self._get_mapped_episode_payload(season, episode)
        if mapped_episode:
            end_episode = self._validate_int_var(mapped_episode.get("episode_end"))

        if end_episode is None or end_episode == episode:
            return self._optional_user_input("", token_data)

        return self._optional_user_input(str(end_episode), token_data)

    def _selected_episode_title(self) -> str | None:
        """Raw title for the selected episode, before any formatting.

        ``None`` means there is no series context at all: no season or
        episode number, or no TVDB data. Callers surface that as a bare ""
        without running filters, preserving the early return these tokens
        have always had.

        ``""`` means there is series context but no usable title: no episode
        data, a TVDB placeholder such as "TBA" or "Episode 12", or a file
        spanning more than one episode. A span has no single episode title,
        so naming it after the first episode would assert that one episode's
        title describes all of them.
        """
        get_info = self._verify_series_info()
        if not get_info:
            return None

        season, episode = get_info
        if self._span_end_episode(season, episode) is not None:
            return ""

        title = ""
        episode_data = self._get_selected_episode_data(season, episode)
        if episode_data:
            title = episode_data.get("name", "")
        if self._is_placeholder_episode_title(title):
            title = ""
        # a manually mapped episode with no TVDB match synthesizes name: None
        return title or ""

    def _episode_title(self, token_data: TokenData) -> str:
        title = self._selected_episode_title()
        if title is None:
            return ""

        # apply basic formatting
        return self._optional_user_input(
            self._title_formatting_standard(title), token_data
        )

    def _episode_title_clean(self, token_data: TokenData) -> str:
        title = self._selected_episode_title()
        if title is None:
            return ""

        return self._optional_user_input(
            self._title_formatting_cleaned(title, self.title_clean_rules), token_data
        )

    def _episode_title_exact(self, token_data: TokenData) -> str:
        """The episode title with no formatting at all, like {title_exact}.

        The title tokens come in three tiers: {title}/{episode_title} strip
        and unidecode, {title_clean}/{episode_title_clean} answer to the
        configured clean rules, and the exact pair apply nothing. This token
        used to strip ``[:\\/<>?*"|]``, which is tier-one behaviour under a
        tier-three name and the one cell where the episode family did not
        mirror the film family.

        The colon is why that mattered beyond tidiness. Removing it here,
        inside the handler, meant the configured colon rule -- which runs
        once over the whole rendered string -- never saw it, so a tracker
        set to keep colons kept them in film titles and lost them in
        episode titles, with no setting that could say otherwise.

        Filenames are unaffected: ``_sanitize_filename`` covers the same
        characters downstream, and the two routes converge on the same
        string. Characters a given tracker will not accept belong in that
        tracker's own ``generate_release_title``, next to the allowlist
        HDBits already applies there.
        """
        title = self._selected_episode_title()
        if title is None:
            return ""
        return self._optional_user_input(title, token_data)

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

    def _video_bit_rate(self, token_data: TokenData, num_only: bool) -> str:
        mi_bit_rate = calculate_avg_video_bit_rate(self.media_info_obj)
        if mi_bit_rate is None:
            return self._optional_user_input("", token_data)
        output = str(mi_bit_rate) if num_only else f"{mi_bit_rate} kbps"
        return self._optional_user_input(output, token_data)

    def _repack(self, token_data: TokenData) -> str:
        """REPACK for the NFO.

        The filename scan this used to carry was a second detector, and it
        ran independently of the file-name side -- so an NFO could claim a
        REPACK the rendered filename did not. It now follows the same
        accepted claim, through the jinja global the process page sets.
        """
        repack = ""
        if self.jinja_engine and self.jinja_engine.environment.globals.get("repack_n"):
            repack = "REPACK"
        return self._optional_user_input(repack, token_data)

    def _repack_n(self, token_data: TokenData) -> str:
        repack = ""
        if self.jinja_engine:
            detect_jinja_repack_n = self.jinja_engine.environment.globals.get(
                "repack_n", ""
            )
            if isinstance(detect_jinja_repack_n, str) and detect_jinja_repack_n:
                detect_repack = re.search(
                    r"(repack\d*)", detect_jinja_repack_n, flags=re.IGNORECASE
                )
                if detect_repack:
                    repack = detect_repack.group(1)

        return self._optional_user_input(repack.upper(), token_data)

    def _repack_reason(self, token_data: TokenData) -> str:
        repack_reason = ""
        if self.jinja_engine:
            configured_reason = self.jinja_engine.environment.globals.get(
                "repack_reason", ""
            )
            if isinstance(configured_reason, str):
                repack_reason = configured_reason
        return self._optional_user_input(repack_reason, token_data)

    def _screen_shots(self, token_data: TokenData) -> str:
        if self.dummy_screen_shots:
            return (
                "#### DUMMY SCREENSHOTS #### \n"
                "(Real screenshots will be generated on the process page in the appropriate format for the tracker)"
                "\nScreen1 Screen2\nScreen3 Screen4\n#### DUMMY SCREENSHOTS ####"
            )
        return self._optional_user_input(
            self.screen_shots if self.screen_shots else "", token_data
        )

    def _screen_shots_comparison(self, token_data: TokenData) -> str:
        if self.dummy_screen_shots:
            return (
                "#### DUMMY SCREENSHOTS #### \n"
                "Note: You MUST fill in the comparison tag that is required!"
                "(Real screenshots will be generated on the process page)"
                "\nScreen1 Screen2\nScreen3 Screen4\n#### DUMMY SCREENSHOTS ####"
            )
        return self._optional_user_input(
            self.screen_shots_comparison if self.screen_shots_comparison else "",
            token_data,
        )

    def _screen_shots_even_obj(self) -> Sequence[ImageUploadData] | None:
        if self.dummy_screen_shots:
            return [
                ImageUploadData(
                    f"https://fakeimage.com/img/{str(i).zfill(2)}.png",
                    f"https://fakeimage.com/img/{str(i).zfill(2)}md.png",
                )
                for i in range(2, 13, 2)
            ]
        return self.screen_shots_even_obj

    def _screen_shots_odd_obj(self) -> Sequence[ImageUploadData] | None:
        if self.dummy_screen_shots:
            return [
                ImageUploadData(
                    f"https://fakeimage.com/img/{str(i).zfill(2)}.png",
                    f"https://fakeimage.com/img/{str(i).zfill(2)}md.png",
                )
                for i in range(1, 12, 2)
            ]
        return self.screen_shots_odd_obj

    def _screen_shots_even_str(self) -> Sequence[str] | None:
        if self.dummy_screen_shots:
            return [
                f"https://fakeimage.com/img/{str(i).zfill(2)}.png"
                for i in range(2, 13, 2)
            ]
        return self.screen_shots_even_str

    def _screen_shots_odd_str(self) -> Sequence[str] | None:
        if self.dummy_screen_shots:
            return [
                f"https://fakeimage.com/img/{str(i).zfill(2)}.png"
                for i in range(1, 12, 2)
            ]
        return self.screen_shots_odd_str

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
        """PROPER for the NFO. See `_repack` for why the filename scan went."""
        proper = ""
        if self.jinja_engine and self.jinja_engine.environment.globals.get("proper_n"):
            proper = "PROPER"
        return self._optional_user_input(proper, token_data)

    def _proper_n(self, token_data: TokenData) -> str:
        proper = ""

        if self.jinja_engine:
            detect_jinja_proper_n = self.jinja_engine.environment.globals.get(
                "proper_n", ""
            )
            if isinstance(detect_jinja_proper_n, str) and detect_jinja_proper_n:
                detect_proper = re.search(
                    r"(proper\d*)", detect_jinja_proper_n, flags=re.IGNORECASE
                )
                if detect_proper:
                    proper = detect_proper.group(1)

        return self._optional_user_input(proper.upper(), token_data)

    def _proper_reason(self, token_data: TokenData) -> str:
        proper_reason = ""
        if self.jinja_engine:
            configured_reason = self.jinja_engine.environment.globals.get(
                "proper_reason", ""
            )
            if isinstance(configured_reason, str):
                proper_reason = configured_reason
        return self._optional_user_input(proper_reason, token_data)

    def _episode_mediainfo(self, token_data: TokenData) -> str:
        if (
            not self.is_series_mode
            or not self.media_input_obj.file_list
            or not self.media_input_obj.file_list_mediainfo
        ):
            return ""

        output = []
        for file_path in self.media_input_obj.file_list:
            mi_obj = self.media_input_obj.file_list_mediainfo.get(file_path)
            if mi_obj:
                get_synopsis = self.get_mi_synopsis(mi_obj)
                if not get_synopsis:
                    continue
                output.append(f"{file_path.stem}\n{get_synopsis}")

        return self._optional_user_input(
            "\n\n".join(output) if output else "", token_data
        )

    def get_mi_synopsis(self, mi_obj: MediaInfo) -> str:
        output = ""

        # video
        video_tracks = getattr(mi_obj, "video_tracks", []) or []
        if video_tracks:
            v_track = video_tracks[0]
            v_avg_bitrate = calculate_avg_bitrate(v_track)
            resolution = VideoResolutionAnalyzer(mi_obj).get_resolution()
            video_data = (
                v_track.format,
                f"{v_avg_bitrate} kbps" if v_avg_bitrate else None,
                resolution if resolution else None,
                f"{v_track.frame_rate} FPS" if v_track.frame_rate else "",
                v_track.other_display_aspect_ratio[0]
                if v_track.other_display_aspect_ratio
                else None,
                v_track.format_profile,
            )
            output += " / ".join(str(x) for x in video_data if x)

        # audios
        audio_s = []
        for a_track in mi_obj.audio_tracks:
            a_channel_s = ParseAudioChannels.get_channel_layout(a_track)
            a_lang = None
            detect_language_code = get_language_mi(a_track)
            if detect_language_code:
                a_lang = get_full_language_str(detect_language_code)
            a_avg_bitrate = calculate_avg_bitrate(a_track)
            audio_data = (
                f"{a_track.format} {a_channel_s}",
                a_lang if a_lang else None,
                a_track.other_sampling_rate[0] if a_track.other_sampling_rate else None,
                f"{a_avg_bitrate} kbps" if a_avg_bitrate else None,
            )
            audio_s.append(audio_data)

        output += "\n" + "\n".join(" / ".join(str(x) for x in a if x) for a in audio_s)
        return output

    def _season_episode_label(self, season_num: object, episode_num: object) -> str:
        """Build a "Season XX Episode XX" label, treating `0` as a valid value.

        Season/episode `0` (e.g. specials) is a legitimate value and must not
        be dropped by a falsy check like `if season_num:`.
        """
        parts = []
        if season_num is not None:
            parts.append(f"Season {str(season_num).zfill(2)}")
        if episode_num is not None:
            parts.append(f"Episode {str(episode_num).zfill(2)}")
        return " ".join(parts)

    def _episode_metadata(self, token_data: TokenData) -> str:
        if (
            not self.is_series_mode
            or not self.media_input_obj.file_list
            or not self.media_input_obj.series_episode_map
        ):
            return ""

        epi_data = []
        for file_path in self.media_input_obj.file_list:
            episode_data = self.media_input_obj.series_episode_map.get(file_path)
            if not episode_data:
                continue

            season_num = episode_data.get("season")
            episode_num = episode_data.get("episode")
            season_episode_str = self._season_episode_label(season_num, episode_num)

            air_date = ""
            get_air_date = episode_data.get("episode_data")
            if get_air_date and get_air_date.get("aired"):
                air_date = get_air_date.get("aired")

            episode_name = episode_data.get("episode_name")
            if self._is_placeholder_episode_title(episode_name):
                episode_name = None

            data = (
                season_episode_str,
                episode_name,
                air_date if air_date else None,
            )
            # prepend filename/stem to the metadata block so the filename is shown at the top
            try:
                filename_header = file_path.stem
            except Exception:
                filename_header = str(file_path)

            if data:
                meta_block = "\n".join(str(x) for x in data if x)
                if meta_block:
                    epi_data.append(f"{filename_header}\n{meta_block}")

        return self._optional_user_input(
            "\n\n".join(epi_data) if epi_data else "", token_data
        )

    def _episode_metadata_mediainfo(self, token_data: TokenData) -> str:
        """Combined token: filename once, then mediainfo synopsis, then metadata.

        <filename>
        <video / audio lines...>
        Season XX Episode XX
        Episode Name
        Air Date
        """
        if (
            not self.is_series_mode
            or not self.media_input_obj
            or not self.media_input_obj.file_list
        ):
            return ""

        output_blocks: list[str] = []

        for file_path in self.media_input_obj.file_list:
            block_lines: list[str] = []

            # filename header
            try:
                filename_header = file_path.stem
            except Exception:
                filename_header = str(file_path)
            block_lines.append(filename_header)

            # mediainfo (if present)
            mi_obj = (
                self.media_input_obj.file_list_mediainfo.get(file_path)
                if self.media_input_obj.file_list_mediainfo
                else None
            )
            if mi_obj:
                synopsis = self.get_mi_synopsis(mi_obj)
                if synopsis:
                    # synopsis may be multi-line; extend lines
                    block_lines.extend(synopsis.splitlines())

            # metadata (if present)
            episode_data = (
                self.media_input_obj.series_episode_map.get(file_path)
                if self.media_input_obj.series_episode_map
                else None
            )

            if episode_data:
                season_num = episode_data.get("season")
                episode_num = episode_data.get("episode")
                season_episode_str = self._season_episode_label(season_num, episode_num)

                if season_episode_str:
                    block_lines.append(season_episode_str)

                episode_name = episode_data.get("episode_name")
                if episode_name and not self._is_placeholder_episode_title(
                    episode_name
                ):
                    block_lines.append(str(episode_name))

                air_date = ""
                get_air_date = episode_data.get("episode_data")
                if get_air_date and get_air_date.get("aired"):
                    air_date = get_air_date.get("aired")
                if air_date:
                    block_lines.append(str(air_date))

            # only include the file if we have more than the filename alone
            if len(block_lines) > 1:
                output_blocks.append("\n".join(block_lines))

        return self._optional_user_input(
            "\n\n".join(output_blocks) if output_blocks else "", token_data
        )

    def get_metadata_synopsis(self) -> str:
        """Build a combined metadata + mediainfo synopsis per-file.

        Output format (per file):
        <filename>
        <season/episode line>
        <episode name>
        <air date>
        <mediainfo synopsis block>

        Files are separated by a blank line.
        """
        # ensure we have files to work with
        if (
            not self.is_series_mode
            or not self.media_input_obj
            or not self.media_input_obj.file_list
        ):
            return ""

        combined: list[str] = []
        for file_path in self.media_input_obj.file_list:
            parts: list[str] = []

            # filename header
            try:
                filename_header = file_path.stem
            except Exception:
                filename_header = str(file_path)
            parts.append(filename_header)

            # metadata (if present)
            episode_data = (
                self.media_input_obj.series_episode_map.get(file_path)
                if self.media_input_obj.series_episode_map
                else None
            )
            if episode_data:
                season_num = episode_data.get("season")
                episode_num = episode_data.get("episode")
                season_episode_str = self._season_episode_label(season_num, episode_num)

                if season_episode_str:
                    parts.append(season_episode_str)

                episode_name = episode_data.get("episode_name")
                if episode_name and not self._is_placeholder_episode_title(
                    episode_name
                ):
                    parts.append(str(episode_name))

                air_date = ""
                get_air_date = episode_data.get("episode_data")
                if get_air_date and get_air_date.get("aired"):
                    air_date = get_air_date.get("aired")
                if air_date:
                    parts.append(str(air_date))

            # mediainfo (if present)
            mi_obj = (
                self.media_input_obj.file_list_mediainfo.get(file_path)
                if self.media_input_obj.file_list_mediainfo
                else None
            )
            if mi_obj:
                synopsis = self.get_mi_synopsis(mi_obj)
                if synopsis:
                    parts.append(synopsis)

            # only include files that had some useful info (beyond filename)
            if len(parts) > 1:
                combined.append("\n".join(parts))

        return "\n\n".join(combined)

    def _get_series_total_count(
        self,
        cache_key: str,
        tmdb_key: str,
        tvdb_key: str,
        tvdb_counter: Callable[[list[dict[str, Any]]], int],
        token_data: TokenData,
    ) -> str:
        """Helper method to get a total seasons/episodes count with caching.

        Prefers TMDB's rollup counts (`number_of_seasons`/`number_of_episodes`),
        which already exclude season 0 (specials). TVDB's `series/extended`
        response has no equivalent rollup field, so when TMDB data isn't
        available we fall back to TVDB, using `tvdb_counter` to collapse its
        raw rows into a real count.
        """
        # check cache first
        if cache_key in self._series_counts:
            return self._optional_user_input(
                str(self._series_counts[cache_key]), token_data
            )

        count = None

        # prefer TMDB's clean rollup counts when available
        tmdb_data = self.media_search_obj.tmdb_data if self.media_search_obj else None
        if tmdb_data:
            tmdb_count = tmdb_data.get(tmdb_key)
            if tmdb_count:
                count = int(tmdb_count)

        # fall back to TVDB
        if count is None:
            tvdb_data = (
                self.media_search_obj.tvdb_data if self.media_search_obj else None
            )
            rows = tvdb_data.get(tvdb_key) if tvdb_data else None
            if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
                count = tvdb_counter(cast(list[dict[str, Any]], rows))

        if not count:
            return self._optional_user_input("", token_data)

        # cache and return count
        self._series_counts[cache_key] = count
        return self._optional_user_input(str(count), token_data)

    @staticmethod
    def _count_tvdb_seasons(seasons: list[dict[str, Any]]) -> int:
        """Count real seasons from TVDB's per-season-type "seasons" rows.

        TVDB's `series/extended` "seasons" list has one row per
        (season-type x season) combination -- aired/official, DVD, absolute,
        and regional orders can each contribute a row for the same season
        number -- plus a row for season 0 (specials). `len(...)` on that list
        wildly overcounts, so this filters down to a single season-type and
        drops season 0.

        The list has no ordering guarantee, so "official" (the codebase's
        canonical/aired order -- see `TVDBSeasonType.AIRED_ORDER` and
        `media_search.py`'s `season_type.api_param == "official"` checks) is
        always preferred when present, regardless of where it falls in the
        list. Only when no "official"-typed rows exist at all does this fall
        back to whichever other season-type is encountered first.
        """
        official_numbers: set[int] = set()
        has_official = False

        fallback_type = None
        fallback_numbers: set[int] = set()

        for row in seasons:
            number = row.get("number")
            row_type = row.get("type")
            type_name = (
                row_type.get("type") or row_type.get("name")
                if isinstance(row_type, dict)
                else None
            )

            if type_name == "official":
                has_official = True
                if number is not None and number != 0:
                    official_numbers.add(number)
                continue

            if number is None or number == 0:
                continue
            if fallback_type is None:
                fallback_type = type_name
            elif type_name != fallback_type:
                continue
            fallback_numbers.add(number)

        if has_official:
            return len(official_numbers)
        return len(fallback_numbers)

    @staticmethod
    def _count_tvdb_episodes(episodes: list[dict[str, Any]]) -> int:
        """Count real episodes from TVDB's "episodes" rows, excluding season 0 (specials)."""
        count = 0
        for row in episodes:
            if isinstance(row, dict) and row.get("seasonNumber") == 0:
                continue
            count += 1
        return count

    def _total_seasons(self, token_data: TokenData) -> str:
        return self._get_series_total_count(
            cache_key="total_seasons",
            tmdb_key="number_of_seasons",
            tvdb_key="seasons",
            tvdb_counter=self._count_tvdb_seasons,
            token_data=token_data,
        )

    def _total_episodes(self, token_data: TokenData) -> str:
        return self._get_series_total_count(
            cache_key="total_episodes",
            tmdb_key="number_of_episodes",
            tvdb_key="episodes",
            tvdb_counter=self._count_tvdb_episodes,
            token_data=token_data,
        )

    def _media_type(self, token_data: TokenData) -> str:
        # `media_input_obj` rather than `media_search_obj`: both receive the
        # value in the same statement when the user confirms a match, but this
        # one is a required constructor argument while `media_search_obj` falls
        # back to an empty payload. It is also what `is_series_mode` reads.
        media_type = self.media_input_obj.media_type
        if not media_type:
            return ""
        return self._optional_user_input(str(media_type), token_data)

    def _is_anime(self, token_data: TokenData) -> str:
        # A word rather than a bool: Jinja treats any non-empty string as true,
        # so returning "False" here would make {% if is_anime %} always fire.
        if not is_anime_release(self.media_input_obj, self.media_search_obj):
            return ""
        return self._optional_user_input("Anime", token_data)

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
            return str(babel_instance.alpha2).upper()
        if hasattr(babel_instance, "alpha3"):
            return str(babel_instance.alpha3).upper()
        if hasattr(babel_instance, "name"):
            return str(babel_instance.name)

        raise GuessitParsingError(
            "Failed to determine language from BabelLanguage instance"
        )

    def _optional_user_input(self, token_str: str | None, token_data: TokenData) -> str:
        # Filters describe the value, so they run before the optional pre/post
        # strings are wrapped around it. Applied after the wrap,
        # `{:opt=E:episode_number|zfill(2)}` handed "E2" to zfill -- already two
        # characters -- and single episodes shipped as "S01E2".
        #
        # They also run on an empty value, because some filters exist precisely
        # to act on one: `default('NOGROUP')` supplies a value where the release
        # has none.
        if self.flatten and token_data.filters:
            token_str = self._apply_custom_filters(token_str or "", token_data.filters)

        # Emptiness is re-checked *after* filtering: a filter can blank a value
        # it was handed (`only_if`/`unless` do exactly that), and wrapping the
        # pre/post strings around nothing strands the separator they carry --
        # `{:opt=-:video_codec|only_if(remux)}` would ship a bare "-".
        if not token_str:
            return ""

        return f"{token_data.pre_token}{token_str}{token_data.post_token}"

    def _detect_resolution(self, mi_obj: MediaInfo | None, remove_scan: bool) -> str:
        resolution = str(self.guess_name.get("screen_size", ""))

        if mi_obj:
            cached_resolution = self.media_input_obj.analysis_cache.get_resolution(
                mi_obj, remove_scan
            )
            if cached_resolution is not None:
                return cached_resolution

            detect_resolution = VideoResolutionAnalyzer(mi_obj).get_resolution(
                remove_scan
            )
            if detect_resolution:
                resolution = detect_resolution
            self.media_input_obj.analysis_cache.set_resolution(
                mi_obj, remove_scan, resolution
            )

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

    def _verify_series_info(self) -> tuple[int, int] | None:
        """Checks to ensure we have season/episode number and return them in a tuple."""
        # if season/episode num is missing return
        season_num = self._validate_int_var(self.season_number)
        episode_num = self._validate_int_var(self.episode_number)
        if season_num is None or episode_num is None:
            return None

        # if no valid object return
        tvdb_data = self.media_search_obj.tvdb_data
        if not tvdb_data:
            return None

        return season_num, episode_num

    def _tvdb_episode_list(
        self, episode_order_type_id: Any | None
    ) -> list[dict[str, Any]]:
        """Episode list for one TVDB ordering, or the flat list.

        ``episodes_by_type`` holds one list per ordering; the flat
        ``episodes`` key is the official/aired order. An id that is absent,
        or names an ordering this payload does not carry, falls back to the
        flat list, which is what every lookup did before orderings were
        recorded.

        The id is matched against both the int and str forms of each key: a
        saved job round-trips ``tvdb_data`` through JSON, which turns the int
        keys of ``episodes_by_type`` into strings, while the mapping row's
        id stays an int.
        """
        tvdb_data = self.media_search_obj.tvdb_data if self.media_search_obj else None
        if not tvdb_data:
            return []

        if episode_order_type_id is not None:
            episodes_by_type = tvdb_data.get("episodes_by_type") or {}
            if isinstance(episodes_by_type, dict):
                type_data = episodes_by_type.get(episode_order_type_id)
                if type_data is None:
                    type_data = episodes_by_type.get(str(episode_order_type_id))
                if isinstance(type_data, dict):
                    episodes = type_data.get("episodes")
                    if isinstance(episodes, list):
                        return cast(list[dict[str, Any]], episodes)

        return cast(list[dict[str, Any]], tvdb_data.get("episodes", []))

    def _get_tvdb_episode_dict(
        self, season: int, episode: int, episode_order_type_id: Any | None = None
    ) -> dict[str, Any] | None:
        """
        Iterate TVDB data and return episode data as a dictionary or None.

        ``episode_order_type_id`` selects which episode ordering to search;
        ``None`` searches the flat official/aired list.

        Example output:
        ```python
        {'id': 3436461, 'seriesId': 121361, 'name': 'You Win or You Die', 'aired': '2011-05-29',
        'runtime': 57, 'nameTranslations': None, 'overview': "Ned confronts...",
        'overviewTranslations': None, 'image': '/banners/episodes/121361/65970f51c2923.jpg',
        'imageType': 11, 'isMovie': 0, 'seasons': None, 'number': 7, 'absoluteNumber': 7,
        'seasonNumber': 1, 'lastUpdated': '2024-01-04 20:05:52', 'finaleType': None, 'year': '2011'}
        ```
        """
        # check cache first for a faster lookup
        cached_order = self._series_episode_cache.get(episode_order_type_id)
        if cached_order:
            cached_data = cached_order.get(season, {}).get(episode)
            if cached_data:
                return cached_data

        # search through TVDB data
        for ep in self._tvdb_episode_list(episode_order_type_id):
            s = ep.get("seasonNumber")
            e = ep.get("number")
            if s is None or e is None:
                continue
            try:
                if int(s) == season and int(e) == episode:
                    episode_data = cast(dict[str, Any], ep)
                    # initialize season dict if it doesn't exist
                    order_cache = self._series_episode_cache.setdefault(
                        episode_order_type_id, {}
                    )
                    order_cache.setdefault(season, {})[episode] = episode_data
                    return episode_data
            except ValueError:
                continue

        return None

    def _selected_order_type_id(self, season: int, episode: int) -> Any | None:
        """Which TVDB ordering the mapping row for this episode was built
        from, or ``None`` when the row predates the field or no row exists.
        """
        mapped_episode = self._get_mapped_episode_payload(season, episode)
        if not mapped_episode:
            return None
        return mapped_episode.get("episode_order_type_id")

    def _get_selected_episode_data(
        self, season: int, episode: int, episode_order_type_id: Any | None = None
    ) -> dict[str, Any] | None:
        """Return episode data from the user's selected mapping before TVDB fallback.

        ``episode_order_type_id`` is only consulted for the TVDB fallback. A
        caller looking up a *different* episode of the same file -- the end
        of a multi-episode span -- passes the start row's ordering, because
        no mapping row matches the end and the fallback would otherwise read
        the aired list whatever the row was built from.
        """
        mapped_episode = self._get_mapped_episode_payload(season, episode)
        if mapped_episode:
            episode_data = mapped_episode.get("episode_data")
            if isinstance(episode_data, dict):
                return cast(dict[str, Any], episode_data)
            if mapped_episode.get("episode_name"):
                return {
                    "seasonNumber": season,
                    "number": episode,
                    "name": mapped_episode.get("episode_name", ""),
                    "aired": "",
                }
            if episode_order_type_id is None:
                episode_order_type_id = mapped_episode.get("episode_order_type_id")
        return self._get_tvdb_episode_dict(season, episode, episode_order_type_id)

    def _get_mapped_episode_payload(
        self, season: int, episode: int
    ) -> dict[str, Any] | None:
        if not self.media_input_obj.series_episode_map:
            return None
        for mapped_data in self.media_input_obj.series_episode_map.values():
            try:
                mapped_season = self._validate_int_var(mapped_data.get("season"))
                mapped_episode = self._validate_int_var(mapped_data.get("episode"))
            except AttributeError:
                continue
            if mapped_season == season and mapped_episode == episode:
                return mapped_data
        return None

    @staticmethod
    def _is_placeholder_episode_title(name: str | None) -> bool:
        """Return True when *name* is a TVDB placeholder episode title
        ("TBA", "Episode 12") that should be treated as no title at all.

        ``name`` may be ``None`` (a manually-mapped episode with no TVDB
        match synthesizes ``name: None``); that is not a placeholder match,
        just an absent title, and is handled safely here without raising.
        """
        if not name:
            return False
        return bool(TokenReplacer._PLACEHOLDER_EPISODE_TITLE_RE.match(name.strip()))

    @staticmethod
    def _title_formatting_standard(title: str) -> str:
        if not title:
            return ""
        title = unidecode.unidecode(title)
        title = _TITLE_UNSAFE_CHARS.sub(" ", title)
        title = _REPEATED_WHITESPACE.sub(" ", title)
        return title

    @staticmethod
    def _title_formatting_cleaned(
        title: str, title_clean_rules: list[tuple[str, str]] | None
    ) -> str:
        if not title:
            return ""
        if title_clean_rules:
            for replace, replace_with in title_clean_rules:
                if replace_with == "[unidecode]":
                    title = unidecode.unidecode(title)
                else:
                    replace_with = replace_with.replace("[remove]", "").replace(
                        "[space]", " "
                    )
                    title = re.sub(rf"{replace}", rf"{replace_with}", title)
        return title

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
        raise InvalidTokenError("Invalid 'colon_replace'")

    @staticmethod
    def _validate_int_var(val: Any, allow_negative: bool = False) -> int | None:
        """Accept any input and return it if it's a valid int"""
        if val is None:
            return None
        if isinstance(val, int):
            if not allow_negative and val < 0:
                return None
            return val
        return None
