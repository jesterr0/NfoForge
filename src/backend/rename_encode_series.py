from pathlib import Path

from src.backend.rename_encode import RenameEncodeBackEnd
from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.config.models import DynamicRangeSettings
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


class RenameEncodeSeriesBackEnd(RenameEncodeBackEnd):
    """Backend for series rename operations. Inherits from RenameEncodeBackEnd to utilize common functionality."""

    __slots__ = ("token_replacer", "override_tokens")

    def __init__(self):
        super().__init__()

    def series_renamer(
        self,
        media_input_obj: MediaInputPayload,
        token: str,
        colon_replacement: ColonReplace,
        media_search_payload: MediaSearchPayload,
        season_num: int,
        episode_num: int,
        title_clean_rules: list[tuple[str, str]] | None,
        video_dynamic_range: DynamicRangeSettings | None,
        user_tokens: dict[str, str] | None,
        episode_format: EpisodeFormat,
        multi_episode_style: MultiEpisodeStyle,
        season_end: int | None = None,
    ) -> Path | None:
        """Rename series file.

        Args:
            media_input_obj: MediaInputPayload with series data
            token: Token string template for rename
            colon_replacement: Colon replacement strategy
            media_search_payload: Media search data (TVDB, etc.)
            title_clean_rules: Title cleaning rules
            video_dynamic_range: Video dynamic range settings
            user_tokens: User-defined tokens
            episode_format: Episode format (Standard, Daily, Anime)
            multi_episode_style: How multi-episode spans render in {episode_number}
            season_end: Highest season number in a multi-season pack, for {season_number}
                range rendering. None (or equal to season_num) keeps single-season output.

        Returns:
            Path object with the generated filename (no extension), or None if failed
        """
        # create TokenReplacer for this specific episode
        self.token_replacer = TokenReplacer(
            media_input_obj=media_input_obj,
            token_string=token,
            colon_replace=colon_replacement,
            media_search_obj=media_search_payload,
            flatten=True,
            file_name_mode=True,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            title_clean_rules=title_clean_rules,
            video_dynamic_range=video_dynamic_range,
            override_tokens=self.override_tokens,
            user_tokens=user_tokens,
            season_number=season_num,
            season_end=season_end,
            episode_number=episode_num,
            episode_format=episode_format,
            multi_episode_style=multi_episode_style,
        )

        # get rename output
        data = self.token_replacer.get_output()
        if data:
            return Path(data)

    def series_folder_renamer(
        self,
        media_input_obj: MediaInputPayload,
        token: str,
        colon_replacement: ColonReplace,
        media_search_payload: MediaSearchPayload,
        season_num: int,
        title_clean_rules: list[tuple[str, str]] | None,
        video_dynamic_range: DynamicRangeSettings | None,
        user_tokens: dict[str, str] | None,
        season_end: int | None = None,
    ) -> Path | None:
        """Render the season pack folder name from the season folder token.

        Mirrors ``series_renamer`` but with no episode context, so episode
        tokens drop out. Because ``file_name_mode`` appends the primary file's
        extension (token_replacer.py:951), the trailing extension is stripped so
        the result is a bare folder name.

        Args:
            season_num: Lowest season number in the pack.
            season_end: Highest season number in a multi-season pack, for
                {season_number} range rendering. None or equal to season_num
                keeps single-season output.

        Returns:
            Path holding the folder name (no extension), or None if empty.
        """
        self.token_replacer = TokenReplacer(
            media_input_obj=media_input_obj,
            token_string=token,
            colon_replace=colon_replacement,
            media_search_obj=media_search_payload,
            flatten=True,
            file_name_mode=True,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            title_clean_rules=title_clean_rules,
            video_dynamic_range=video_dynamic_range,
            override_tokens=self.override_tokens,
            user_tokens=user_tokens,
            season_number=season_num,
            season_end=season_end,
        )

        data = self.token_replacer.get_output()
        if data:
            # file_name_mode appends the primary file's extension; a folder has
            # none, so strip the single trailing suffix it added.
            return Path(data).with_suffix("")

    @staticmethod
    def build_folder_rename_targets(
        input_path: Path | None,
        rename_map: dict[Path, Path],
        folder_name: str,
    ) -> dict[Path, Path]:
        """Relocate every rename target into ``input_path.parent / folder_name``.

        Only fires when a directory was opened and every mapped file sits
        directly inside it (mirrors the movie flow's folder guard). Returns a new
        mapping on success, or a copy of the original mapping unchanged when the
        guard fails or ``folder_name`` is empty.
        """
        if (
            not input_path
            or not folder_name
            or not rename_map
            or not input_path.is_dir()
            or any(src.parent != input_path for src in rename_map)
        ):
            return dict(rename_map)

        new_folder = input_path.parent / folder_name
        return {src: new_folder / trg.name for src, trg in rename_map.items()}
