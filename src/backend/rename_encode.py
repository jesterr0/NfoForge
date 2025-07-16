from pathlib import Path

from pymediainfo import MediaInfo

from src.backend.token_replacer import TokenReplacer
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.payloads.media_search import MediaSearchPayload


class RenameEncodeBackEnd:
    __slots__ = ("token_replacer", "override_tokens")

    def __init__(self):
        self.token_replacer = TokenReplacer | None
        self.override_tokens = {}

    def media_renamer(
        self,
        media_file: Path,
        source_file: Path | None,
        mvr_token: str,
        mvr_colon_replacement: ColonReplace,
        media_search_payload: MediaSearchPayload,
        media_info_obj: MediaInfo,
        source_file_mi_obj: MediaInfo | None,
        movie_clean_title_rules: list[tuple[str, str]] | None,
        user_tokens: dict[str, str] | None,
    ) -> Path | None:
        self.token_replacer = TokenReplacer(
            media_input=media_file,
            jinja_engine=None,
            source_file=source_file,
            token_string=mvr_token,
            colon_replace=mvr_colon_replacement,
            media_search_obj=media_search_payload,
            media_info_obj=media_info_obj,
            source_file_mi_obj=source_file_mi_obj,
            flatten=True,
            file_name_mode=True,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            movie_clean_title_rules=movie_clean_title_rules,
            override_tokens=self.override_tokens,
            user_tokens=user_tokens,
        )
        data = self.token_replacer.get_output()
        if data:
            return Path(data)

    def reset(self) -> None:
        self.token_replacer = None
        self.override_tokens.clear()
