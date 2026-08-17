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


def test_read_template_returns_none_when_file_missing_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a template can be deleted from disk (or by another open template editor
    # pointed at the same directory) after being listed but before being read;
    # this used to let FileNotFoundError escape instead of degrading to None
    monkeypatch.setattr("src.backend.template_selector.RUNTIME_DIR", tmp_path)
    backend = TemplateSelectorBackEnd()
    template_path = backend.create_template(
        tmp_path / "templates" / "ghost.txt", MediaType.MOVIE
    )
    template_path.unlink()

    assert backend.read_template(name="ghost") is None
    assert "ghost" not in backend.templates


def test_read_template_by_idx_returns_none_when_file_missing_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.backend.template_selector.RUNTIME_DIR", tmp_path)
    backend = TemplateSelectorBackEnd()
    template_path = backend.create_template(
        tmp_path / "templates" / "ghost.txt", MediaType.MOVIE
    )
    template_path.unlink()

    assert backend.read_template(idx=0) is None
    assert backend.templates == {}


def test_read_template_by_idx_out_of_range_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a stale index from a combo box that outgrew this cache (e.g. another
    # editor deleted entries) must degrade to None rather than IndexError
    monkeypatch.setattr("src.backend.template_selector.RUNTIME_DIR", tmp_path)
    backend = TemplateSelectorBackEnd()

    assert backend.read_template(idx=3) is None


def test_delete_template_is_idempotent_when_already_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # deleting through one template editor while another has the same
    # template queued for deletion must not raise on the second attempt
    monkeypatch.setattr("src.backend.template_selector.RUNTIME_DIR", tmp_path)
    backend = TemplateSelectorBackEnd()
    template_path = backend.create_template(
        tmp_path / "templates" / "gone.txt", MediaType.MOVIE
    )
    template_path.unlink()

    backend.delete_template(template_path)  # must not raise

    assert backend.templates == {}


def test_load_templates_tolerates_a_missing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the whole templates directory could be removed out from under the app
    # while it is running; listing it again must not raise
    monkeypatch.setattr("src.backend.template_selector.RUNTIME_DIR", tmp_path)
    backend = TemplateSelectorBackEnd()
    backend.template_dir.rmdir()

    assert backend.load_templates() == {}
