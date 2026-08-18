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

    __slots__ = ()

    def series_renamer(
        self,
        media_input_obj: MediaInputPayload,
        media_file: Path,
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
        parse_filename_attributes: bool = False,
        season_end: int | None = None,
    ) -> Path | None:
        """Rename series file.

        Args:
            media_input_obj: MediaInputPayload with series data
            media_file: Episode file whose filename and MediaInfo should feed tokens
            token: Token string template for rename
            colon_replacement: Colon replacement strategy
            media_search_payload: Media search data (TVDB, etc.)
            title_clean_rules: Title cleaning rules
            video_dynamic_range: Video dynamic range settings
            user_tokens: User-defined tokens
            episode_format: Episode format (Standard, Daily, Anime)
            multi_episode_style: How multi-episode spans render in {episode_number}
            parse_filename_attributes: Detect per-file REMUX/HYBRID/REPACK/PROPER
                attributes when they are not explicitly overridden
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
            parse_filename_attributes=parse_filename_attributes,
            season_number=season_num,
            season_end=season_end,
            episode_number=episode_num,
            episode_format=episode_format,
            multi_episode_style=multi_episode_style,
            active_file=media_file,
            flat_filters=self.flat_filters,
            custom_edition_info=self.custom_edition_info,
            custom_cut_names=self.custom_cut_names,
        )

        # get rename output
        data = self.token_replacer.get_output()
        if data:
            return Path(data)
        return None

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
            flat_filters=self.flat_filters,
            custom_edition_info=self.custom_edition_info,
            custom_cut_names=self.custom_cut_names,
        )

        data = self.token_replacer.get_output()
        if data:
            # file_name_mode appends the primary file's extension; a folder has
            # none, so strip the single trailing suffix it added.
            return Path(data).with_suffix("")
        return None

    @staticmethod
    def build_pack_rename_targets(
        input_path: Path | None,
        rename_map: dict[Path, Path],
        file_seasons: dict[Path, int],
        root_folder_name: str,
        season_folder_names: dict[int, str],
    ) -> tuple[dict[Path, Path], dict[Path, Path]]:
        """Re-home a pack's files under a renamed root and season subfolders.

        Handles the three layouts a pack actually arrives in: episodes sitting
        directly in the opened folder (single- or multi-season), and episodes
        split across ``Season NN`` subfolders. Only fires when a directory was
        opened and every mapped file lives somewhere beneath it.

        A subfolder is renamed only when every episode in it belongs to one
        season that ``season_folder_names`` has a name for. One that mixes
        seasons, or that has no name available, keeps its own name -- it still
        moves, because its parent is renamed around it. Anything else in the
        pack (``Extras``, artwork, a stray sample) is likewise carried along by
        the folder rename without needing a target of its own.

        Args:
            file_seasons: Season per source file, from the episode mapping.
            root_folder_name: Name for the opened folder. Empty leaves it alone.
            season_folder_names: Season -> subfolder name. Empty leaves every
                subfolder alone.

        Returns:
            ``(file_targets, directory_targets)``, both absolute and final. On
            guard failure, the original mapping and an empty folder map, so the
            caller falls back to renaming filenames in place.
        """
        if (
            not input_path
            or not rename_map
            or not input_path.is_dir()
            or any(not src.is_relative_to(input_path) for src in rename_map)
        ):
            return dict(rename_map), {}

        directory_targets: dict[Path, Path] = {}
        if root_folder_name:
            directory_targets[input_path] = input_path.parent / root_folder_name

        if season_folder_names:
            for directory, seasons in _seasons_by_directory(
                rename_map, file_seasons, input_path
            ).items():
                if len(seasons) != 1:
                    continue
                folder_name = season_folder_names.get(next(iter(seasons)))
                if not folder_name:
                    continue
                # A subfolder's final path sits under its parent's final path,
                # which for a season folder is the renamed root.
                directory_targets[directory] = (
                    _relocate(directory.parent, directory_targets) / folder_name
                )

        file_targets = {
            src: _relocate(src.parent, directory_targets) / trg.name
            for src, trg in rename_map.items()
        }
        return file_targets, directory_targets


def _seasons_by_directory(
    rename_map: dict[Path, Path],
    file_seasons: dict[Path, int],
    input_path: Path,
) -> dict[Path, set[int]]:
    """Season numbers found in each folder that directly holds episodes.

    Only the folder an episode actually sits in is a candidate for a season
    name. An intermediate folder between it and the opened root is left out
    deliberately -- naming both it and its child from the same season would
    produce a duplicated "Show.S01/Show.S01" path. The opened folder itself is
    excluded too: it is named from the whole pack's season range, not from the
    seasons of whichever files happen to sit loose in it.

    Keyed outermost-first so a caller resolving a folder's new location can
    rely on its ancestors having been resolved already.
    """
    seasons_by_directory: dict[Path, set[int]] = {}
    for source in rename_map:
        season = file_seasons.get(source)
        if season is None:
            continue
        directory = source.parent
        if directory == input_path or not directory.is_relative_to(input_path):
            continue
        seasons_by_directory.setdefault(directory, set()).add(season)

    return dict(
        sorted(seasons_by_directory.items(), key=lambda item: len(item[0].parts))
    )


def _relocate(directory: Path, directory_targets: dict[Path, Path]) -> Path:
    """``directory``'s final location once every ancestor rename is applied."""
    mapped = directory_targets.get(directory)
    if mapped is not None:
        return mapped
    parent = directory.parent
    if parent == directory:
        return directory
    mapped_parent = _relocate(parent, directory_targets)
    if mapped_parent == parent:
        return directory
    return mapped_parent / directory.name
