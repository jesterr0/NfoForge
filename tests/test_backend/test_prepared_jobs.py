"""Coverage for preparing a job and resuming a prepared one.

A prepared job must not regenerate its titles/NFOs and must not stop to ask
anything -- that silence is the precondition for running jobs from a queue.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

import src.backend.process as process_module
from src.backend.process import ProcessBackEnd
from src.context.processing_context import ProcessingContext
from src.enums.tracker_selection import TrackerSelection
from src.enums.upload_process import RunPhase


def _tracker_info() -> Any:
    return SimpleNamespace(
        upload_enabled=True,
        nfo_template="default",
        announce_url="https://tracker.test/announce",
        source="TEST",
        comments=None,
        max_piece_size=None,
    )


def _backend(monkeypatch: pytest.MonkeyPatch) -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    info = _tracker_info()
    backend.config = cast(
        Any,
        SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(
                    timeout=60,
                    enable_mkbrr=False,
                    enable_plugins=False,
                    enable_prompt_overview=True,
                    releasers_name="tester",
                ),
                trackers=SimpleNamespace(
                    by_selection=lambda: {TrackerSelection.AITHER: info}
                ),
                torrent_clients=SimpleNamespace(
                    qbittorrent=SimpleNamespace(enabled=False)
                ),
                dependencies=SimpleNamespace(mkbrr=None),
                user_tokens=SimpleNamespace(tokens={}),
                global_management=SimpleNamespace(
                    title_clean_rules=[], video_dynamic_range=None
                ),
                series=SimpleNamespace(multi_episode_style=None),
            )
        ),
    )
    backend.template_selector_be = cast(
        Any,
        SimpleNamespace(
            load_templates=lambda: {"default": Path("default.txt")},
            read_template=lambda **_k: "{{ prompt_group }}",
        ),
    )
    monkeypatch.setattr(
        backend, "handle_images_for_trackers", lambda *_a, **_k: {}, raising=False
    )
    monkeypatch.setattr(
        backend, "determine_max_piece_size", lambda *_a, **_k: None, raising=False
    )
    monkeypatch.setattr(
        backend, "disconnect_from_clients", lambda *_a, **_k: None, raising=False
    )
    return cast(ProcessBackEnd, backend)


def _context(tmp_path: Path) -> ProcessingContext:
    context = ProcessingContext()
    context.media_input.input_path = tmp_path / "media.mkv"
    context.media_input.working_dir = tmp_path
    # the real flow creates each tracker's output dir when building the paths
    (tmp_path / "aither").mkdir(parents=True, exist_ok=True)
    # carrying a base torrent puts every tracker on the clone path, which is
    # what a prepared job does and keeps these tests off real hashing
    base = tmp_path / "base.torrent"
    base.write_bytes(b"d8:announce")
    context.shared_data.base_torrent = base
    return context


@pytest.fixture(autouse=True)
def _stub_torrent_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_module, "clone_torrent", lambda **_k: MagicMock())
    monkeypatch.setattr(
        process_module, "write_torrent", lambda **_k: Path("out.torrent")
    )


@pytest.fixture
def generating(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the unprepared path run without standing up the whole config tree.

    These tests are about *whether* generation and its prompts happen, not about
    how an NFO renders, so title/NFO rendering is stubbed out.
    """
    monkeypatch.setattr(
        process_module,
        "TokenReplacer",
        lambda **_k: SimpleNamespace(get_output=lambda: "generated nfo"),
    )


def _kwargs(context: ProcessingContext, tmp_path: Path, **overrides: Any) -> dict:
    base = {
        "process_dict": {"Aither": {"path": tmp_path / "aither" / "release.torrent"}},
        "queued_status_update": MagicMock(),
        "queued_text_update": MagicMock(),
        "queued_text_update_replace_last_line": MagicMock(),
        "progress_bar_cb": MagicMock(),
        "caught_error": MagicMock(),
        "context": context,
    }
    base.update(overrides)
    return base


def _prepare(context: ProcessingContext) -> None:
    context.shared_data.tracker_release_data[TrackerSelection.AITHER] = {
        "title": "Frozen Title",
        "nfo": "frozen nfo body",
    }


# --------------------------------------------------------------------------
# a prepared job asks nothing and regenerates nothing
# --------------------------------------------------------------------------
def test_a_prepared_job_never_prompts_for_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-asking on every resume is what would block an unattended queue."""
    context = _context(tmp_path)
    _prepare(context)
    token_prompt = MagicMock(return_value={"prompt_group": "x"})
    backend = _backend(monkeypatch)

    backend.process_trackers(
        **_kwargs(context, tmp_path, token_prompt_cb=token_prompt),
        phase=RunPhase.PREPARE,
    )

    token_prompt.assert_not_called()


def test_a_prepared_job_never_opens_the_overview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    _prepare(context)
    overview = MagicMock(return_value=None)
    backend = _backend(monkeypatch)

    backend.process_trackers(
        **_kwargs(context, tmp_path, overview_cb=overview), phase=RunPhase.PREPARE
    )

    overview.assert_not_called()


def test_a_prepared_job_keeps_its_frozen_nfo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frozen wins: a since-edited template must not rewrite what was prepared."""
    context = _context(tmp_path)
    _prepare(context)
    backend = _backend(monkeypatch)

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    written = (tmp_path / "aither" / "release.nfo").read_text(encoding="utf-8")
    assert written == "frozen nfo body"
    assert context.shared_data.tracker_release_data[TrackerSelection.AITHER] == {
        "title": "Frozen Title",
        "nfo": "frozen nfo body",
    }


def test_an_unprepared_job_still_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generating: None
) -> None:
    """The skip must be driven by carried data, not by always being off."""
    context = _context(tmp_path)
    token_prompt = MagicMock(return_value={"prompt_group": "x"})
    backend = _backend(monkeypatch)
    monkeypatch.setattr(
        backend, "generate_tracker_title", lambda **_k: "Generated", raising=False
    )
    monkeypatch.setattr(
        process_module, "get_prompt_tokens", lambda _t: ["prompt_group"]
    )

    backend.process_trackers(
        **_kwargs(context, tmp_path, token_prompt_cb=token_prompt),
        phase=RunPhase.PREPARE,
    )

    token_prompt.assert_called_once()


# --------------------------------------------------------------------------
# preparing records what a save needs, and publishes nothing
# --------------------------------------------------------------------------
def test_preparing_never_uploads_or_injects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: prepare stops one step short of publishing."""
    context = _context(tmp_path)
    _prepare(context)
    backend = _backend(monkeypatch)
    upload = MagicMock()
    inject = MagicMock()
    monkeypatch.setattr(backend, "_upload_tracker_with_retry", upload, raising=False)
    monkeypatch.setattr(backend, "_inject_with_user_retry", inject, raising=False)

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    upload.assert_not_called()
    inject.assert_not_called()


def test_preparing_still_writes_the_torrent_and_nfo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    _prepare(context)
    backend = _backend(monkeypatch)

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    assert (tmp_path / "aither" / "release.nfo").is_file()


def test_generation_records_release_data_for_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generating: None
) -> None:
    """Without this, a save right after a run would still be unprepared."""
    context = _context(tmp_path)
    backend = _backend(monkeypatch)
    monkeypatch.setattr(
        backend, "generate_tracker_title", lambda **_k: "Generated", raising=False
    )
    monkeypatch.setattr(process_module, "get_prompt_tokens", lambda _t: [])

    assert not context.shared_data.is_prepared()
    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    assert context.shared_data.is_prepared()
    assert TrackerSelection.AITHER in context.shared_data.tracker_release_data


def test_generation_records_prompt_answers_for_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generating: None
) -> None:
    context = _context(tmp_path)
    backend = _backend(monkeypatch)
    monkeypatch.setattr(
        backend, "generate_tracker_title", lambda **_k: "Generated", raising=False
    )
    monkeypatch.setattr(
        process_module, "get_prompt_tokens", lambda _t: ["prompt_group"]
    )

    backend.process_trackers(
        **_kwargs(
            context,
            tmp_path,
            token_prompt_cb=lambda _tokens: {"prompt_group": "answered"},
        ),
        phase=RunPhase.PREPARE,
    )

    assert context.shared_data.prompt_token_answers == {"prompt_group": "answered"}


def test_generation_records_template_fingerprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generating: None
) -> None:
    context = _context(tmp_path)
    backend = _backend(monkeypatch)
    monkeypatch.setattr(
        backend, "generate_tracker_title", lambda **_k: "Generated", raising=False
    )
    monkeypatch.setattr(process_module, "get_prompt_tokens", lambda _t: [])

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    assert "default" in context.shared_data.template_fingerprints
