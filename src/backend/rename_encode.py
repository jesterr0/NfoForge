from pathlib import Path
from pymediainfo import MediaInfo

from src.backend.token_replacer import TokenReplacer
from src.enums.token_replacer import ColonReplace
from src.payloads.media_search import MediaSearchPayload


class RenameEncodeBackEnd:
    # def __init__(self):
    #     pass

    @staticmethod
    def media_renamer(
        media_file: Path,
        source_file: Path | None,
        mvr_token: str,
        mvr_colon_replacement: ColonReplace,
        media_search_payload: MediaSearchPayload,
        media_info_obj: MediaInfo,
        source_file_mi_obj: MediaInfo | None,
        movie_clean_title_rules: list[tuple[str, str]] | None,
    ) -> Path | None:
        output = None
        token_replacer = TokenReplacer(
            media_input=media_file,
            jinja_engine=None,
            source_file=source_file,
            token_string=mvr_token,
            colon_replace=mvr_colon_replacement,
            media_search_obj=media_search_payload,
            media_info_obj=media_info_obj,
            source_file_mi_obj=source_file_mi_obj,
            flatten=True,
            movie_clean_title_rules=movie_clean_title_rules,
        )
        data = token_replacer.get_output()
        if data:
            _, output = data
        return Path(output) if output else None
