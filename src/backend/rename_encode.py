from pathlib import Path
from typing import Any

from guessit import guessit

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.enums.rename import QualitySelection
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.logger.nfo_forge_logger import LOG
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


class RenameEncodeBackEnd:
    __slots__ = ("token_replacer", "override_tokens")

    def __init__(self):
        self.token_replacer = TokenReplacer | None
        self.override_tokens = {}

    def media_renamer(
        self,
        media_input_obj: MediaInputPayload,
        mvr_token: str,
        mvr_colon_replacement: ColonReplace,
        media_search_payload: MediaSearchPayload,
        title_clean_rules: list[tuple[str, str]] | None,
        video_dynamic_range: dict[str, Any] | None,
        user_tokens: dict[str, str] | None,
    ) -> Path | None:
        self.token_replacer = TokenReplacer(
            media_input_obj=media_input_obj,
            token_string=mvr_token,
            colon_replace=mvr_colon_replacement,
            media_search_obj=media_search_payload,
            flatten=True,
            file_name_mode=True,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            title_clean_rules=title_clean_rules,
            video_dynamic_range=video_dynamic_range,
            override_tokens=self.override_tokens,
            user_tokens=user_tokens,
        )
        data = self.token_replacer.get_output()
        if data:
            return Path(data)

    def reset(self) -> None:
        self.token_replacer = None
        self.override_tokens.clear()

    @staticmethod
    def get_quality(
        media_input: Path,
        source_input: Path | None = None,
    ) -> QualitySelection | None:
        source = guessit(media_input.name).get("source", "")

        # if we have access to the source file let's instead parse that
        if source_input:
            check_source_file = guessit(source_input.name).get("source", "")
            if check_source_file:
                source = check_source_file

        if "Ultra HD Blu-ray" in source:
            return QualitySelection.UHD_BLURAY
        elif "Blu-ray" in source:
            return QualitySelection.BLURAY
        elif "DVD" in source:
            return QualitySelection.DVD
        elif "Web" in source:
            return QualitySelection.WEB_DL
        elif "HDTV" in source:
            return QualitySelection.HDTV
        elif "SDTV" in source:
            return QualitySelection.SDTV

    @staticmethod
    def execute_renames(
        file_list_rename_map: dict[Path, Path],
        input_path: Path | None,
    ) -> tuple[dict[Path, Path], Path | None]:
        """Execute filesystem renames in 2 phases: directories first, then files.

        Args:
            file_list_rename_map: Map of original paths to renamed paths
            input_path: The original input path (file or directory)
            callback_text: Optional callback for status updates (callable that takes str)

        Returns:
            Tuple of (updated_rename_map, updated_input_path)
        """
        # PHASE 1: rename directories first
        directory_renames: dict[Path, Path] = {}
        for src_file, trg_file in file_list_rename_map.items():
            if src_file.parent != trg_file.parent:
                src_dir = src_file.parent
                trg_dir = trg_file.parent
                if src_dir not in directory_renames:
                    directory_renames[src_dir] = trg_dir

        # perform directory renames and update the map
        for src_dir, trg_dir in directory_renames.items():
            if src_dir.exists() and src_dir != trg_dir:
                actual_trg_dir = src_dir.rename(trg_dir)
                if not actual_trg_dir.exists():
                    raise FileNotFoundError(
                        f"Directory rename failed: {actual_trg_dir} does not exist"
                    )
                LOG.debug(LOG.LOG_SOURCE.BE, f"Renamed folder: {src_dir} -> {trg_dir}")

                # update input_path if it was pointing to the old directory
                if input_path and input_path == src_dir:
                    input_path = actual_trg_dir

                # update file_list_rename_map: ONLY update values (current paths), NOT keys (original paths)
                # Keys must stay as original paths to maintain mapping from file_list later
                updated_map: dict[Path, Path] = {}
                for orig_path, renamed_path in file_list_rename_map.items():
                    # KEEP the original key unchanged
                    new_orig = orig_path

                    # update value if it was in the old directory
                    new_renamed = renamed_path
                    if renamed_path.is_relative_to(src_dir):
                        relative = renamed_path.relative_to(src_dir)
                        new_renamed = actual_trg_dir / relative

                    updated_map[new_orig] = new_renamed

                file_list_rename_map = updated_map

        # PHASE 2: rename files
        # After Phase 1, directory may have moved, so keys (original paths) may not exist
        # We need to find where files currently are based on their parent directory updates
        for orig_path, target_path in file_list_rename_map.items():
            # calculate current physical location by updating parent from directory renames
            current_path = orig_path
            for src_dir, trg_dir in directory_renames.items():
                if orig_path.is_relative_to(src_dir):
                    relative = orig_path.relative_to(src_dir)
                    current_path = trg_dir / relative
                    break

            # only rename if target is different and current location exists
            if current_path != target_path and current_path.exists():
                trg_out = current_path.rename(target_path)
                if not trg_out.exists():
                    raise FileNotFoundError(
                        f"File rename failed: {trg_out} does not exist"
                    )
                LOG.debug(
                    LOG.LOG_SOURCE.BE,
                    f"Renamed file: {current_path} -> {target_path}",
                )

                # update input_path if it was pointing to this specific file
                if input_path and input_path == current_path:
                    input_path = trg_out

        return file_list_rename_map, input_path
