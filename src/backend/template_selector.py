from os import PathLike
from pathlib import Path

from src.backend.utils.working_dir import RUNTIME_DIR

DEFAULT_TEMPLATE = """\
Info
Title:                  : {{ movie_title }} {{ release_year_parentheses }}
Format Profile          : {{ format_profile }}
Resolution              : {{ resolution }}
Average Bitrate         : {{ mi_video_bit_rate }}
{% if releasers_name %}
Encoder                 : {{ releasers_name }}
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

    def __init__(self):
        self.template_dir = RUNTIME_DIR / "templates"
        self.template_dir.mkdir(exist_ok=True, parents=True)
        self.templates = {}

    def load_templates(self) -> dict[str, str]:
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
            with open(_path, "r", encoding="utf-8") as template:
                return template.read()

    def create_template(self, path: PathLike[str] | str) -> Path:
        with open(path, "w", encoding="utf-8") as new_template:
            new_template.write(self.get_default_template())
        self.load_templates()
        return Path(path)

    def save_template(self, path: PathLike[str] | str, text: str) -> None:
        with open(path, "w", encoding="utf-8") as save_file:
            save_file.write(text)

    def delete_template(self, path: PathLike[str] | str) -> None:
        Path(path).unlink()
        self.load_templates()

    def get_default_template(self) -> str:
        return DEFAULT_TEMPLATE
