from pathlib import Path

import pytest

from src.backend.template_selector import (
    DEF_MV_TEMPLATE,
    DEF_SERIES_TEMPLATE,
    TemplateSelectorBackEnd,
)
from src.enums.media_type import MediaType


@pytest.mark.parametrize(
    ("media_type", "template_name", "expected"),
    (
        (MediaType.MOVIE, "movie_default.txt", DEF_MV_TEMPLATE),
        (MediaType.SERIES, "series_default.txt", DEF_SERIES_TEMPLATE),
    ),
)
def test_create_template_uses_new_default_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    media_type: MediaType,
    template_name: str,
    expected: str,
) -> None:
    monkeypatch.setattr("src.backend.template_selector.RUNTIME_DIR", tmp_path)

    backend = TemplateSelectorBackEnd()
    template_path = tmp_path / "templates" / template_name

    created_path = backend.create_template(template_path, media_type)
    written = template_path.read_text(encoding="utf-8")

    assert created_path == template_path
    assert written == expected
    assert backend.templates[template_path.stem] == template_path
    assert "movie_title" not in written
    assert "mi_video_bit_rate" not in written
    assert "title_exact" in written
    assert "video_bit_rate" in written
