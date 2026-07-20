from os import PathLike
from pathlib import Path

from src.backend.utils.working_dir import RUNTIME_DIR
from src.enums.media_type import MediaType

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
        """
        if not name and idx is None:
            raise ValueError(
                "You must supply 'name' or 'idx' arg when reading templates "
                "(This is likely caused due to no templates being configured for the current tracker)"
            )

        _path: Path | None = None

        if name:
            for key in self.templates.keys():
                if name == key:
                    _path = self.templates[key]
                    break
        elif not _path and (idx is not None and idx != -1):
            _path = tuple(self.templates.values())[idx]

        if _path:
            with open(_path, encoding="utf-8") as template:
                return template.read()
        return None

    def create_template(self, path: PathLike[str] | str, media_type: MediaType) -> Path:
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
        with open(path, "w", encoding="utf-8") as save_file:
            save_file.write(text)

    def delete_template(self, path: PathLike[str] | str) -> None:
        Path(path).unlink()
        self.load_templates()
