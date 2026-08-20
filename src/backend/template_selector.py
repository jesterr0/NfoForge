from os import PathLike
from pathlib import Path

from src.backend.utils.working_dir import RUNTIME_DIR
from src.enums.media_type import MediaType
from src.logger.nfo_forge_logger import LOG

DEF_MV_TEMPLATE = """\
Info
Title:                  : {{ title_exact }} {{ release_year_parentheses }}
Source:                 : {{ source_file_no_ext }}
Format Profile          : {{ format_profile }}
Resolution              : {{ resolution }}
Average Bitrate         : {{ video_bit_rate }}
{% if releasers_name %}
Encoder                 : {{ releasers_name }}
{% endif %}

{% if screen_shots %}
{{ screen_shots }}
{% endif %}

{% if release_notes %}
Release Notes:
{{ release_notes }}
{% endif %}

{% if media_info_short %}
MediaInfo
{{ media_info_short }}
{% endif %}

{{ shared_with_bbcode }}"""

DEF_SERIES_TEMPLATE = """\
Info
Title:                  : {{ title_exact }} {{ release_year_parentheses }}
Season                  : {{ season_number }}
Episode                 : {{ episode_number }}
Episode Title           : {{ episode_title_exact }}
Air Date                : {{ air_date }}
Source                  : {{ source_file_no_ext }}
Format Profile          : {{ format_profile }}
Resolution              : {{ resolution }}
Average Bitrate         : {{ video_bit_rate }}
{% if releasers_name %}
Encoder                 : {{ releasers_name }}
{% endif %}

{% if screen_shots %}
{{ screen_shots }}
{% endif %}

{% if release_notes %}
Release Notes:
{{ release_notes }}
{% endif %}

{% if media_info_short %}
MediaInfo
{{ media_info_short }}
{% endif %}

{{ shared_with_bbcode }}"""


class TemplateSelectorBackEnd:
    __slots__ = ("template_dir", "templates")

    def __init__(self) -> None:
        self.template_dir = RUNTIME_DIR / "templates"
        self.template_dir.mkdir(exist_ok=True, parents=True)
        self.templates: dict[str, Path] = {}

    def load_templates(self) -> dict[str, Path]:
        self.templates.clear()
        if self.template_dir.is_dir():
            for item in self.template_dir.iterdir():
                if item.is_file() and item.suffix == ".txt":
                    self.templates[item.stem] = item
        return self.templates

    def read_template(
        self, name: str | None = None, idx: int | None = None
    ) -> str | None:
        """
        Attempts to read template to text from name and/or index

        Returns:
            Optional[str]: Template text or None

        A template can vanish out from under this cache -- deleted from disk,
        or deleted through another open template editor pointed at the same
        directory -- between it being listed and being read. That is treated
        the same as "no template selected": the stale cache entry is dropped
        and None is returned instead of letting FileNotFoundError escape.
        """
        if not name and idx is None:
            raise ValueError(
                "You must supply 'name' or 'idx' arg when reading templates "
                "(This is likely caused due to no templates being configured for the current tracker)"
            )

        _key: str | None = None
        _path: Path | None = None

        if name:
            if name in self.templates:
                _key = name
                _path = self.templates[name]
        elif idx is not None and idx != -1:
            keys = tuple(self.templates.keys())
            if 0 <= idx < len(keys):
                _key = keys[idx]
                _path = self.templates[_key]

        if _path:
            try:
                with open(_path, encoding="utf-8") as template:
                    return template.read()
            except OSError as error:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Template '{_key}' is missing on disk ({_path}), dropping "
                    f"it from the cache: {error}",
                )
                if _key is not None:
                    self.templates.pop(_key, None)
                return None
        return None

    def create_template(self, path: PathLike[str] | str, media_type: MediaType) -> Path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as new_template:
            # determine correct template based on media type selection from frontend
            new_template.write(
                DEF_MV_TEMPLATE
                if media_type is MediaType.MOVIE
                else DEF_SERIES_TEMPLATE
            )
        self.load_templates()
        return Path(path)

    def save_template(self, path: PathLike[str] | str, text: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as save_file:
            save_file.write(text)

    def delete_template(self, path: PathLike[str] | str) -> None:
        Path(path).unlink(missing_ok=True)
        self.load_templates()
