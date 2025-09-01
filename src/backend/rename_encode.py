from pathlib import Path
from typing import Any

from guessit import guessit

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.enums.rename import QualitySelection
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
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
