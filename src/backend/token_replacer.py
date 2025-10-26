import re
from ast import literal_eval
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Type

import unidecode
from auto_qpf import ChapterGenerator
from auto_qpf.enums import ChapterType
from babelfish.language import Language as BabelLanguage
from guessit import guessit
from iso639 import Lang
from iso639.exceptions import InvalidLanguageValue
from pymediainfo import MediaInfo, Track

from src.backend.tokens import FileToken, NfoToken, TokenData, Tokens, TokenType
from src.backend.utils.audio_channels import ParseAudioChannels
from src.backend.utils.audio_codecs import AudioCodecs
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
from src.backend.utils.rename_normalizations import EDITION_INFO
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.backend.utils.working_dir import RUNTIME_DIR
from src.enums.media_type import MediaType
from src.enums.rename import QualitySelection
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace, SharedWithType, UnfilledTokenRemoval
from src.exceptions import GuessitParsingError, InvalidTokenError
from src.nf_jinja2 import Jinja2TemplateEngine
from src.packages.custom_types import ComparisonPair, ImageUploadData
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.version import __version__, program_name, program_url


class TokenReplacer:
    FILENAME_ATTRIBUTES = ("remux", "hybrid", "re_release")

    __slots__ = (
        # __init__
        "media_input_obj",
        "token_string",
        "jinja_engine",
        "colon_replace",
        "media_search_obj",
        "flatten",
        "flat_filters",
        "file_name_mode",
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
        "parse_filename_attributes",
        # series exclusive args
        "season_number",
        "episode_number",
        "episode_format",
        # derived properties (computed from payload)
        "primary_file",
        "source_file",
        "media_info_obj",
        "source_file_mi_obj",
        "guess_name",
        "guess_source_name",
        # vars (set during __init__)
        "guessit_language",
        "token_data",
        # series vars
        "_series_cache",
    )

    def __init__(
        self,
        media_input_obj: MediaInputPayload,
        token_string: str,
        jinja_engine: Jinja2TemplateEngine | None = None,
        colon_replace: ColonReplace = ColonReplace.REPLACE_WITH_DASH,
        media_search_obj: MediaSearchPayload | None = None,
        flatten: bool | None = False,
        flat_filters: dict[str, Callable[..., str]] | None = None,
        file_name_mode: bool = True,
        token_type: Iterable[TokenType] | Type[TokenType] | None = None,
        unfilled_token_mode: UnfilledTokenRemoval = UnfilledTokenRemoval.KEEP,
        releasers_name: str | None = "",
        override_tokens: dict[str, str] | None = None,
        user_tokens: dict[str, str] | None = None,
        edition_override: str | None = None,
        frame_size_override: str | None = None,
        title_clean_rules: list[tuple[str, str]] | None = None,
        override_title_rules: list[tuple[str, str]] | None = None,
        video_dynamic_range: dict[str, Any] | None = None,
        screen_shots: str | None = None,
        screen_shots_comparison: str | None = None,
        screen_shots_even_obj: Sequence[ImageUploadData] | None = None,
        screen_shots_odd_obj: Sequence[ImageUploadData] | None = None,
        screen_shots_even_str: Sequence[str] | None = None,
        screen_shots_odd_str: Sequence[str] | None = None,
        release_notes: str | None = "",
        dummy_screen_shots: bool = False,
        parse_filename_attributes: bool = False,
        season_number: int | None = None,
        episode_number: int | None = None,
        episode_format: EpisodeFormat | None = None,
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
            video_dynamic_range: (Optional[dict[str, Any]]: Rules to control formatting of video dynamic range.
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
            parse_filename_attributes (Optional[bool]): If set to True attributes REMUX, HYBRID, PROPER, and REPACK will be
              detected from the filename.
            season_number (Optional[int]): Season number.
            episode_number (Optional[int]): Episode number.
            episode_format (Optional[EpisodeFormat]): Episode format (Standard, Daily, Anime).
            flat_filters (Optional[dict[str, Callable[..., str]]]): Custom filters for flat mode.
                Dictionary mapping filter names to callable functions that take (value, *args) and return str.
        """
        self.media_input_obj = media_input_obj
        self.token_string = token_string
        self.jinja_engine = jinja_engine
        self.colon_replace = ColonReplace(colon_replace)
        self.media_search_obj = (
            media_search_obj if media_search_obj else MediaSearchPayload()
        )
        self.flatten = flatten
        self.flat_filters = flat_filters
        self.file_name_mode = file_name_mode
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
        self.parse_filename_attributes = parse_filename_attributes
        # series exclusive args
        self.season_number = season_number
        self.episode_number = episode_number
        self.episode_format = episode_format

        # derive file references from payload (paths are always current after renames)
        self.primary_file = self._get_primary_file()
        self.source_file = self._get_source_file()
        self.media_info_obj = self._get_primary_mediainfo()
        self.source_file_mi_obj = self._get_source_mediainfo()
        self.guess_name = guessit(self.primary_file.name)
        self.guess_source_name = (
            guessit(self.source_file.name) if self.source_file else None
        )
        self.guessit_language = self._guessit_language()
        self.token_data = Tokens.generate_token_dataclass(token_type)

        # series cache
        self._series_cache = {}

        if not self.flatten and not self.jinja_engine:
            raise AttributeError(
                "You must pass in 'jinja_engine' if you are not flattening your output string"
            )

    def _get_primary_file(self) -> Path:
        """Determine the primary file for token analysis based on context."""
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
        primary = self._get_primary_file()
        return self.media_input_obj.file_list_mediainfo.get(primary)

    # def set_active_file(self, file_path: Path) -> None:
    #     """
    #     Set the active file for token processing.

    #     Args:
    #         file_path: Path to the file to make active
    #     """
    #     if file_path not in self.media_input_obj.file_list:
    #         raise ValueError(f"File {file_path} not found in media input file list")

    #     # Update primary file and related properties
    #     self.primary_file = file_path
    #     self.media_info_obj = (
    #         self.media_input_obj.file_list_mediainfo.get(file_path)
    #         if self.media_input_obj.file_list_mediainfo
    #         else None
    #     )
    #     self.guess_name = guessit(file_path.name)

    #     # For series, extract episode info from filename
    #     if self.is_series_mode:
    #         self._update_episode_info_from_file(file_path)

    # def get_output_for_file(self, file_path: Path) -> str | None:
    #     """
    #     Generate output for a specific file without permanently changing context.

    #     Args:
    #         file_path: Path to the file to process

    #     Returns:
    #         Formatted string for the file
    #     """
    #     # Store original state
    #     original_primary = self.primary_file
    #     original_media_info = self.media_info_obj
    #     original_guess = self.guess_name
    #     original_season = self.season_number
    #     original_episode = self.episode_number

    #     try:
    #         # Temporarily set the active file
    #         self.set_active_file(file_path)

    #         # Generate output
    #         return self.get_output()

    #     finally:
    #         # Restore original state
    #         self.primary_file = original_primary
    #         self.media_info_obj = original_media_info
    #         self.guess_name = original_guess
    #         self.season_number = original_season
    #         self.episode_number = original_episode

    # def get_output_for_all_files(self) -> dict[Path, str]:
    #     """
    #     Generate outputs for all files in the file list.

    #     Returns:
    #         Dictionary mapping file paths to their formatted outputs
    #     """
    #     outputs = {}
    #     for file_path in self.media_input_obj.file_list:
    #         try:
    #             output = self.get_output_for_file(file_path)
    #             if output:
    #                 outputs[file_path] = output
    #         except Exception as e:
    #             # Log error but continue with other files
    #             print(f"Error processing {file_path}: {e}")

    #     return outputs

    def _get_source_mediainfo(self) -> MediaInfo | None:
        """Get MediaInfo for the source file."""
        if not self.source_file:
            return None

        # Get from file_list_mediainfo if available
        if self.media_input_obj.file_list_mediainfo:
            return self.media_input_obj.file_list_mediainfo.get(self.source_file)

        return None

        # Get from file_list_mediainfo if available
        if self.media_input_obj.file_list_mediainfo:
            return self.media_input_obj.file_list_mediainfo.get(self.source_file)

        return None

    # def get_batch_outputs(
    #     self, template_per_file: dict[Path, str] | None = None
    # ) -> dict[Path, str]:
    #     """
    #     Generate outputs for multiple files, optionally with different templates per file.

    #     Args:
    #         template_per_file: Optional dict mapping file paths to specific token strings.
    #                           If None, uses the instance's token_string for all files.

    #     Returns:
    #         Dictionary mapping file paths to their formatted outputs
    #     """
    #     outputs = {}
    #     original_token_string = self.token_string

    #     for file_path in self.media_input_obj.file_list:
    #         try:
    #             # Set custom template if provided
    #             if template_per_file and file_path in template_per_file:
    #                 self.token_string = template_per_file[file_path]

    #             output = self.get_output_for_file(file_path)
    #             if output:
    #                 outputs[file_path] = output

    #         except Exception as e:
    #             print(f"Error processing {file_path}: {e}")
    #         finally:
    #             # Restore original template
    #             self.token_string = original_token_string

    #     return outputs

    # @property
    # def active_file_info(self) -> dict[str, Any]:
    #     """
    #     Get information about the currently active file.

    #     Returns:
    #         Dictionary with current file context information
    #     """
    #     return {
    #         "file_path": self.primary_file,
    #         "has_mediainfo": self.media_info_obj is not None,
    #         "season_number": self.season_number,
    #         "episode_number": self.episode_number,
    #         "guessit_info": self.guess_name,
    #         "is_series_mode": self.is_series_mode,
    #         "is_comparison_mode": self.is_comparison_mode,
    #     }

    @property
    def media_input(self) -> Path:
        """Backward compatibility property."""
        return self.primary_file

    # @property
    # def is_comparison_mode(self) -> bool:
    #     """Check if we're in comparison mode."""
    #     return self.media_input_obj.comparison_pair is not None

    @property
    def is_series_mode(self) -> bool:
        """Check if we're processing a series."""
        return self.media_input_obj.media_type == MediaType.SERIES

    # @property
    # def is_movie_mode(self) -> bool:
    #     """Check if we're processing a movie."""
    #     return self.media_input_obj.media_type == MediaType.MOVIE

    # def get_series_output(self, episode_file: Path) -> str | None:
    #     """
    #     Generate output for a specific episode file in a series.

    #     Args:
    #         episode_file: Specific episode file to process

    #     Returns:
    #         Formatted string for the episode
    #     """
    #     if not self.is_series_mode:
    #         raise ValueError(
    #             "get_series_output can only be used with series media type"
    #         )

    #     # Temporarily update context for this episode
    #     original_primary = self.primary_file
    #     original_media_info = self.media_info_obj
    #     original_guess = self.guess_name

    #     try:
    #         # Update to episode-specific data
    #         self.primary_file = episode_file
    #         self.media_info_obj = (
    #             self.media_input_obj.file_list_mediainfo.get(episode_file)
    #             if self.media_input_obj.file_list_mediainfo
    #             else None
    #         )
    #         self.guess_name = guessit(episode_file.name)

    #         # Extract episode info from filename
    #         self._update_episode_info_from_file(episode_file)

    #         # Generate output
    #         return self.get_output()

    #     finally:
    #         # Restore original values
    #         self.primary_file = original_primary
    #         self.media_info_obj = original_media_info
    #         self.guess_name = original_guess

    # def get_all_series_outputs(self) -> dict[Path, str]:
    #     """Generate outputs for all episodes in a series."""
    #     if not self.is_series_mode:
    #         raise ValueError(
    #             "get_all_series_outputs can only be used with series media type"
    #         )

    #     outputs = {}
    #     for episode_file in self.media_input_obj.file_list:
    #         try:
    #             output = self.get_series_output(episode_file)
    #             if output:
    #                 outputs[episode_file] = output
    #         except Exception as e:
    #             # Log error but continue with other episodes
    #             print(f"Error processing {episode_file}: {e}")

    #     return outputs

    # def _update_episode_info_from_file(self, episode_file: Path) -> None:
    #     """Extract season and episode numbers from filename."""
    #     guess_info = guessit(episode_file.name)

    #     # Update season/episode numbers if found
    #     if "season" in guess_info:
    #         self.season_number = guess_info["season"]
    #     if "episode" in guess_info:
    #         self.episode_number = guess_info["episode"]

    # @classmethod
    # def from_legacy_inputs(  # TODO: remove i doubt we will ever need this
    #     cls,
    #     media_input: Path,
    #     token_string: str,
    #     source_file: Path | None = None,
    #     media_info_obj: MediaInfo | None = None,
    #     source_file_mi_obj: MediaInfo | None = None,
    #     **kwargs,
    # ) -> "TokenReplacer":
    #     """
    #     Create TokenReplacer from legacy single-file inputs.
    #     Provides backward compatibility.
    #     """
    #     # create MediaInputPayload from legacy inputs
    #     file_list = [media_input] if media_input.is_file() else []

    #     # build file_list_mediainfo
    #     file_list_mediainfo = {}
    #     if media_info_obj:
    #         file_list_mediainfo[media_input] = media_info_obj
    #     elif media_input.exists():
    #         media_info = MediaInfo.parse(str(media_input))
    #         file_list_mediainfo[media_input] = media_info

    #     # add source file to file list and mediainfo if provided
    #     if source_file:
    #         file_list.append(source_file)
    #         if source_file_mi_obj:
    #             file_list_mediainfo[source_file] = source_file_mi_obj
    #         elif source_file.exists():
    #             media_info = MediaInfo.parse(str(source_file))
    #             file_list_mediainfo[source_file] = media_info

    #     # create comparison pair if we have both source and media files
    #     comparison_pair = None
    #     if source_file:
    #         comparison_pair = ComparisonPair(source=source_file, media=media_input)

    #     payload = MediaInputPayload(
    #         input_path=media_input,
    #         file_list=file_list,
    #         file_list_mediainfo=file_list_mediainfo if file_list_mediainfo else None,
    #         comparison_pair=comparison_pair,
    #         media_type=MediaType.MOVIE,  # Default to movie for legacy
    #     )

    #     return cls(payload, token_string, **kwargs)

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
            # add user tokens to the context for jinja2 rendering
            if self.user_tokens:
                for key, value in self.user_tokens.items():
                    filled_tokens[key] = value
            self._update_token_data(filled_tokens)
            if not self.jinja_engine:
                raise AttributeError("Could not detect 'jinja_engine'")
            jinja_output = self.jinja_engine.render_from_str(
                self.token_string,
                filled_tokens,
            )
            return jinja_output

    def _update_token_data(self, filled_tokens: dict):
        for key, value in filled_tokens.items():
            setattr(self.token_data, key, value)

    def _parse_user_input(self):
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
        if self.override_tokens and token_data.token in self.override_tokens:
            return self._optional_user_input(
                self.override_tokens[token_data.token], token_data
            )

        # get raw token value
        raw_value = self._get_raw_token_value(token_data)
        if not raw_value:
            return ""

        # apply custom filters only for flatten mode (filename generation)
        if self.flatten and token_data.filters and isinstance(raw_value, str):
            raw_value = self._apply_custom_filters(raw_value, token_data.filters)

        return raw_value

    def _get_raw_token_value(self, token_data: TokenData) -> str | Sequence[Any] | None:
        """Get the raw token value without filters or pre/post tokens."""
        # determine which token types to check
        if self.token_type:
            token_types = (
                self.token_type
                if isinstance(self.token_type, (list, set, tuple))
                else [self.token_type]
            )
        else:
            # no specific type: check both media and nfo tokens
            token_types = [FileToken, NfoToken]

        for token_type in token_types:
            if token_type == FileToken:
                if (
                    not self.parse_filename_attributes
                    and token_data.token in self.FILENAME_ATTRIBUTES
                ):
                    continue
                value = self._media_tokens(token_data)
                if value:
                    return value
            elif token_type == NfoToken:
                value = self._nfo_tokens(token_data)
                if value:
                    return value

        return ""

    def _apply_custom_filters(self, value: str, filters: tuple[str, ...]) -> str:
        """Apply custom filters to a string value."""
        for f in filters:
            f_lowered = f.lower()
            if f_lowered == "upper":
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
                        pass
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
                    args = [args_str[1:-1]]
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
            except Exception:
                # return original value if filter fails
                return value

        # unknown filter: return unchanged (graceful degradation)
        return value

    def _media_tokens(self, token_data: TokenData) -> str:
        if token_data.bracket_token == Tokens.EDITION.token:
            return self._edition(token_data)

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

        elif token_data.bracket_token == Tokens.IMDB_AKA.token:
            return self._imdb_aka(token_data)

        elif token_data.bracket_token == Tokens.IMDB_AKA_FALLBACK_TITLE.token:
            return self._imdb_aka(token_data, True)

        elif token_data.bracket_token == Tokens.IMDB_AKA_FALLBACK_TITLE_CLEAN.token:
            return self._imdb_aka(token_data, True, True)

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

        elif token_data.bracket_token == Tokens.AIR_DATE.token:
            return self._air_date(token_data)

        elif token_data.bracket_token == Tokens.SEASON_NUMBER.token:
            return self._season_number(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_AIR_DATE.token:
            return self._episode_air_date(token_data)

        elif token_data.bracket_token in {
            Tokens.EPISODE_NUMBER.token,
            Tokens.EPISODE_NUMBER_ABSOLUTE.token,
        }:
            return self._episode_number(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_TITLE.token:
            return self._episode_title(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_TITLE_CLEAN.token:
            return self._episode_title_clean(token_data)

        elif token_data.bracket_token == Tokens.EPISODE_TITLE_EXACT.token:
            return self._episode_title_exact(token_data)

        return ""

    def _nfo_tokens(self, token_data: TokenData) -> str | Sequence[Any] | None:
        if token_data.bracket_token == Tokens.CHAPTER_TYPE.token:
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

    def _format_token_string(self, filled_tokens) -> str | None:
        try:
            formatted_title = self.token_string
            for key, value in filled_tokens.items():
                if "title_clean" not in key:  # this covers all '*title_clean' tokens
                    formatted_title = formatted_title.replace(f"{{{key}}}", value)
                    formatted_title = self._colon_replace(
                        self.colon_replace, formatted_title
                    )

            # apply specific formatting for 'title_clean' tokens
            if filled_tokens:
                if "title_clean" in formatted_title:
                    formatted_title = formatted_title.replace(
                        "{title_clean}", filled_tokens["title_clean"]
                    )
                if "episode_title_clean" in formatted_title:
                    formatted_title = formatted_title.replace(
                        "{episode_title_clean}", filled_tokens["episode_title_clean"]
                    )
                if "imdb_aka_fallback_title_clean" in formatted_title:
                    formatted_title = formatted_title.replace(
                        "{imdb_aka_fallback_title_clean}",
                        filled_tokens["imdb_aka_fallback_title_clean"],
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

    def _air_date(self, token_data: TokenData) -> str:
        if self.media_search_obj.media_type is not MediaType.SERIES:
            return ""
        get_info = self._verify_series_info()
        if not get_info:
            return ""
        episode_data = self._get_tvdb_episode_dict(*get_info)
        if not episode_data:
            return ""
        return self._optional_user_input(episode_data.get("aired", ""), token_data)

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

    def _audio_channel_s_layout(self, token_data: TokenData) -> str:
        layout = ""
        if self.media_info_obj and self.media_info_obj.audio_tracks:
            mi_channel_layout = self.media_info_obj.audio_tracks[0].channel_layout
            if mi_channel_layout:
                layout = mi_channel_layout

        return self._optional_user_input(layout, token_data)

    def _audio_codec(self, token_data: TokenData) -> str:
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
            all_lang = get_full_language_str(guess_lang)

        if self.media_info_obj and self.media_info_obj.audio_tracks:
            language_set = {
                lang
                for track in self.media_info_obj.audio_tracks
                if (lang := get_language_mi(track))
            }

            if language_set:
                if len(language_set) == 1:
                    all_lang = get_full_language_str(next(iter(language_set)))
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
        video_codec = self.guess_name.get("video_codec", "")
        if video_codec in ["H.264", "H.265"]:
            video_codec = video_codec.replace("H.", "x")
        return video_codec

    def _mediainfo_codec(self, quality: QualitySelection) -> str:
        """Extract codec from MediaInfo with source awareness."""
        if not (self.media_info_obj and self.media_info_obj.video_tracks):
            return ""

        # we'll check to see if we have a remux in the filename or in the override tokens
        is_remux = self.override_tokens and "remux" in self.override_tokens

        track = self.media_info_obj.video_tracks[0]
        detect_video_codec = track.format

        if not detect_video_codec:
            return ""

        if detect_video_codec == "AV1":
            return track.format
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
            return track.format
        elif detect_video_codec in ["VP8", "VP9"]:
            return track.format

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

            if not res_key or not self.video_dynamic_range["resolutions"].get(
                res_key, False
            ):
                return self._optional_user_input("", token_data)

            # get data from dict
            enabled_hdr_types = [
                k for k, v in self.video_dynamic_range["hdr_types"].items() if v
            ]
            custom_strings = self.video_dynamic_range.get("custom_strings", {})
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

    def _video_dynamic_range_type(
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
            detect_language = get_language_mi(track, char_code)

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
            else self.guess_name.get("title", "")
        )
        title = self._title_formatting_standard(title)
        return self._optional_user_input(title, token_data)

    def _title_clean(self, token_data: TokenData) -> str:
        title = (
            self.media_search_obj.title
            if self.media_search_obj.title
            else self.guess_name.get("title", "")
        )
        title = self._title_formatting_cleaned(title, self.title_clean_rules)
        return self._optional_user_input(title, token_data)

    def _title_exact(self, token_data: TokenData) -> str:
        title = (
            self.media_search_obj.title
            if self.media_search_obj.title
            else self.guess_name.get("title", "")
        )
        return self._optional_user_input(title, token_data)

    def _imdb_id(self, token_data: TokenData) -> str:
        imdb_id = self.media_search_obj.imdb_id if self.media_search_obj.imdb_id else ""
        return self._optional_user_input(imdb_id, token_data)

    def _imdb_aka(
        self,
        token_data: TokenData,
        fallback: bool = False,
        cleaned_fallback: bool = False,
    ) -> str:
        # attempt to get AKA from IMDb data
        if self.media_search_obj.imdb_data and self.media_search_obj.imdb_data.title:
            aka = self.media_search_obj.imdb_data.title
            return self._optional_user_input(aka, token_data)

        # if no fall back return nothing
        if not fallback:
            return ""

        # fallback to tmdb title if we can
        aka = ""
        if self.media_search_obj.title:
            if not cleaned_fallback:
                aka = self._title_formatting_standard(self.media_search_obj.title)
            else:
                aka = self._title_formatting_cleaned(
                    self.media_search_obj.title, self.title_clean_rules
                )
        return self._optional_user_input(aka, token_data)

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
            if self.media_input_obj.input_path.is_dir():
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
        return self._optional_user_input(
            "REMUX" if "remux" in self.media_input.stem.lower() else "", token_data
        )

    def _re_release(self, token_data: TokenData) -> str:
        search_re_release = re.findall(
            r"\b(PROPER\d*|REPACK\d*)\b", self.media_input.name, flags=re.IGNORECASE
        )
        re_release_str = " ".join((str(x).upper() for x in search_re_release))

        return self._optional_user_input(re_release_str, token_data)

    def _get_source_quality(self) -> QualitySelection:
        """Get the detected source quality."""
        # check if source is being overridden first
        if self.override_tokens and "source" in self.override_tokens:
            override_source = self.override_tokens["source"].lower()
            # map the override value to QualitySelection
            if override_source == "webdl":
                return QualitySelection.WEB_DL
            elif override_source == "webrip":
                return QualitySelection.WEB_RIP
            elif override_source == "bluray":
                return QualitySelection.BLURAY
            elif override_source == "uhd bluray":
                return QualitySelection.UHD_BLURAY
            elif override_source == "dvd":
                return QualitySelection.DVD
            elif override_source == "hdtv":
                return QualitySelection.HDTV

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
            if re.search(r"web[-_\.]?dl", self.media_input.name, flags=re.I):
                source_quality = QualitySelection.WEB_DL
            else:
                source_quality = QualitySelection.WEB_RIP
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

    def _season_number(self, token_data: TokenData) -> str:
        int_val = str(self._validate_int_var(self.season_number)) or ""
        return self._optional_user_input(int_val, token_data)

    def _episode_air_date(self, token_data: TokenData) -> str:
        get_info = self._verify_series_info()
        if not get_info:
            return ""

        # get episode dict
        air_date = ""
        episode_data = self._get_tvdb_episode_dict(*get_info)
        if episode_data:
            air_date = episode_data.get("aired", "")
        return self._optional_user_input(air_date, token_data)

    def _episode_number(self, token_data: TokenData) -> str:
        int_val = str(self._validate_int_var(self.episode_number)) or ""
        return self._optional_user_input(int_val, token_data)

    def _episode_title(self, token_data: TokenData) -> str:
        get_info = self._verify_series_info()
        if not get_info:
            return ""

        # get episode dict
        title = ""
        episode_data = self._get_tvdb_episode_dict(*get_info)
        if episode_data:
            title = episode_data.get("name", "")

        # apply basic formatting
        title = self._title_formatting_standard(title)
        return self._optional_user_input(title, token_data)

    def _episode_title_clean(self, token_data: TokenData) -> str:
        get_info = self._verify_series_info()
        if not get_info:
            return ""

        # get episode dict
        title = ""
        episode_data = self._get_tvdb_episode_dict(*get_info)
        if episode_data:
            title = episode_data.get("name", "")
        title = self._title_formatting_cleaned(title, self.title_clean_rules)
        return self._optional_user_input(title, token_data)

    def _episode_title_exact(self, token_data: TokenData) -> str:
        get_info = self._verify_series_info()
        if not get_info:
            return ""

        # get episode dict
        title = ""
        episode_data = self._get_tvdb_episode_dict(*get_info)
        if episode_data:
            title = episode_data.get("name", "")
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
        v_track = mi_obj.video_tracks[0]
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
        output += " / ".join((str(x) for x in video_data if x))

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

    def _episode_metadata(self, token_data: TokenData) -> str:
        if not self.is_series_mode or not self.media_input_obj.series_episode_map:
            return ""

        epi_data = []
        for episode, episode_data in self.media_input_obj.series_episode_map.items():
            # `episode` is expected to be a Path (filename) in the map keys
            season_episode_str = ""
            season_num = episode_data.get("season")
            episode_num = episode_data.get("episode")
            if season_num:
                season_episode_str += f"Season {str(season_num).zfill(2)}"
            if episode_num:
                season_episode_str += (
                    f" Episode {str(episode_num).zfill(2)}"
                    if season_num
                    else f"Episode {str(episode_num).zfill(2)}"
                )

            air_date = ""
            get_air_date = episode_data.get("episode_data")
            if get_air_date and get_air_date.get("aired"):
                air_date = get_air_date.get("aired")

            data = (
                season_episode_str,
                episode_data.get("episode_name"),
                air_date if air_date else None,
            )
            # prepend filename/stem to the metadata block so the filename is shown at the top
            # use `episode.stem` if `episode` looks like a Path-like object, otherwise fall back
            filename_header = ""
            try:
                # path-like objects have .stem
                filename_header = episode.stem
            except Exception:
                # fallback to string cast
                filename_header = str(episode)

            if data:
                meta_block = "\n".join((str(x) for x in data if x))
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
                season_episode_str = ""
                season_num = episode_data.get("season")
                episode_num = episode_data.get("episode")
                if season_num:
                    season_episode_str += f"Season {str(season_num).zfill(2)}"
                if episode_num:
                    season_episode_str += (
                        f" Episode {str(episode_num).zfill(2)}"
                        if season_num
                        else f"Episode {str(episode_num).zfill(2)}"
                    )

                if season_episode_str:
                    block_lines.append(season_episode_str)

                episode_name = episode_data.get("episode_name")
                if episode_name:
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

    def get_metadata_synopsis(self):
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

        combined = []
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
                season_episode_str = ""
                season_num = episode_data.get("season")
                episode_num = episode_data.get("episode")
                if season_num:
                    season_episode_str += f"Season {str(season_num).zfill(2)}"
                if episode_num:
                    season_episode_str += (
                        f" Episode {str(episode_num).zfill(2)}"
                        if season_num
                        else f"Episode {str(episode_num).zfill(2)}"
                    )

                if season_episode_str:
                    parts.append(season_episode_str)

                episode_name = episode_data.get("episode_name")
                if episode_name:
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

    def _get_tvdb_data_count(
        self, data_key: str, cache_key: str, token_data: TokenData
    ) -> str:
        """Helper method to get count from TVDB data with caching."""
        # check cache first
        if cache_key in self._series_cache:
            return self._optional_user_input(
                str(self._series_cache[cache_key]), token_data
            )

        # early return if no TVDB data
        if not self.media_search_obj or not self.media_search_obj.tvdb_data:
            return self._optional_user_input("", token_data)

        # get data from TVDB
        data = self.media_search_obj.tvdb_data.get(data_key)
        if not data:
            return self._optional_user_input("", token_data)

        # cache and return count
        count = len(data)
        self._series_cache[cache_key] = count
        return self._optional_user_input(str(count), token_data)

    def _total_seasons(self, token_data: TokenData) -> str:
        return self._get_tvdb_data_count("seasons", "total_seasons", token_data)

    def _total_episodes(self, token_data: TokenData) -> str:
        return self._get_tvdb_data_count("episodes", "total_episodes", token_data)

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
        output = ""
        if token_str:
            pre = token_data.pre_token
            post = token_data.post_token
            output = f"{pre}{token_str}{post}"

        # strip optional strings from user token
        if token_data.full_match and token_data.bracket_token:
            self.token_string = self.token_string.replace(
                token_data.full_match, token_data.bracket_token
            )

        return output if output else ""

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

    def _verify_series_info(self) -> tuple[int, int] | None:
        """Checks to ensure we have season/episode number and return them in a tuple."""
        # if season/episode num is missing return
        season_num = self._validate_int_var(self.season_number)
        episode_num = self._validate_int_var(self.episode_number)
        if season_num is None or episode_num is None:
            return

        # if no valid object return
        tvdb_data = self.media_search_obj.tvdb_data
        if not tvdb_data:
            return

        return season_num, episode_num

    def _get_tvdb_episode_dict(
        self, season: int, episode: int
    ) -> dict[str, Any] | None:
        """
        Iterate TVDB data and return episode data as a dictionary or None.

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
        if self._series_cache:
            cached_data = self._series_cache.get(season, {}).get(episode)
            if cached_data:
                return cached_data

        if not self.media_search_obj or not self.media_search_obj.tvdb_data:
            return None

        # search through TVDB data
        for ep in self.media_search_obj.tvdb_data:
            s = ep.get("seasonNumber")
            e = ep.get("number")
            if s is None or e is None:
                continue
            try:
                if int(s) == season and int(e) == episode:
                    self._series_cache[season][episode] = ep
                    return ep
            except ValueError:
                continue

        return None

    @staticmethod
    def _title_formatting_standard(title: str) -> str:
        if not title:
            return ""
        title = unidecode.unidecode(title)
        title = re.sub(r'[:\\/<>\?*"|]', " ", title)
        title = re.sub(r"\s{2,}", " ", title)
        return title

    @staticmethod
    def _title_formatting_cleaned(
        title: str, title_clean_rules: list[tuple[str, str]] | None
    ) -> str:
        if not title or not title_clean_rules:
            return ""
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

    @staticmethod
    def _validate_int_var(val: Any, allow_negative: bool = False) -> int | None:
        """Accept any input and return it if it's a valid int"""
        if val is None:
            return
        if isinstance(val, int):
            if not allow_negative and val < 0:
                return
            return val


# Individual File Processing
# Process a specific file temporarily
# output = token_replacer.get_output_for_file(Path("S01E01.mkv"))

# Or set a file as the active context
# token_replacer.set_active_file(Path("S01E01.mkv"))
# output = token_replacer.get_output()


# Batch Processing
# Process all files with the same template
# all_outputs = token_replacer.get_output_for_all_files()

# Process files with different templates per file
# templates = {
#     Path("S01E01.mkv"): "{title} S{season_number:02d}E{episode_number:02d}",
#     Path("S01E02.mkv"): "{title} - {episode_title}",
# }
# outputs = token_replacer.get_batch_outputs(templates)
