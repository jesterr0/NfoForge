"""The base torrent belongs to no tracker.

A run hashes once and stamps that base for every tracker. Before this, the base
*was* the first tracker's own artifact -- and for a UNIT3D tracker, upload
replaces that file in place with the server's rewritten copy
(`Unit3dBaseUploader._download_uploaded_torrent`), inside the same loop
iteration, before the next tracker clones. Every later tracker therefore cloned
from a torrent a tracker's server had edited, which shipped one tracker's
announce, source, comment and `created by` to another tracker's users.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from torf import Torrent

import src.backend.process as process_module
from src.backend.process import ProcessBackEnd
from src.backend.torrents import BASE_TORRENT_SUFFIX, generate_torrent
from src.backend.torrents.torrent import NFO_FORGE_CREATOR
from src.context.processing_context import ProcessingContext
from src.enums.tracker_selection import TrackerSelection
from src.enums.upload_process import RunPhase

_TRACKERS = {
    TrackerSelection.AITHER: SimpleNamespace(
        upload_enabled=True,
        nfo_template="default",
        announce_url="https://aither.invalid/AITHERKEY/announce",
        source="Aither",
        comments="Uploaded to Aither",
    ),
    TrackerSelection.LST: SimpleNamespace(
        upload_enabled=True,
        nfo_template="default",
        announce_url="https://lst.invalid/LSTKEY/announce",
        source="LST.GG",
        comments=None,
    ),
}


def _backend(monkeypatch: pytest.MonkeyPatch) -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        Any,
        SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(
                    timeout=60,
                    enable_plugins=False,
                    enable_prompt_overview=False,
                    releasers_name="tester",
                ),
                trackers=SimpleNamespace(by_selection=lambda: _TRACKERS),
                torrent_clients=SimpleNamespace(
                    qbittorrent=SimpleNamespace(enabled=False)
                ),
                dependencies=SimpleNamespace(mkbrr=None, enable_mkbrr=False),
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
            read_template=lambda **_k: "nfo",
        ),
    )
    monkeypatch.setattr(
        backend, "handle_images_for_trackers", lambda *_a, **_k: {}, raising=False
    )
    monkeypatch.setattr(
        backend, "disconnect_from_clients", lambda *_a, **_k: None, raising=False
    )
    # A prepared job rebuilds its title from the tracker's rules, so the title
    # path runs even though these tests carry finished release data. They are
    # about torrent isolation, so it renders to the value already stored.
    monkeypatch.setattr(
        backend, "generate_tracker_title", lambda **_k: "Release Title", raising=False
    )
    return cast(ProcessBackEnd, backend)


def _context(tmp_path: Path) -> ProcessingContext:
    context = ProcessingContext()
    media = tmp_path / "release.mkv"
    media.write_bytes(b"media payload")
    context.media_input.input_path = media
    context.media_input.working_dir = tmp_path
    for tracker in _TRACKERS:
        (tmp_path / str(tracker).lower()).mkdir(parents=True, exist_ok=True)
    for tracker in _TRACKERS:
        context.shared_data.tracker_release_data[tracker] = {
            "title": "Release Title",
            "nfo": "nfo body",
        }
    return context


def _tracker_paths(tmp_path: Path) -> dict[TrackerSelection, Path]:
    return {
        tracker: tmp_path / str(tracker).lower() / "release.torrent"
        for tracker in _TRACKERS
    }


def _kwargs(context: ProcessingContext, tmp_path: Path) -> dict[str, Any]:
    paths = _tracker_paths(tmp_path)
    return {
        "process_dict": {
            str(tracker): {"path": path} for tracker, path in paths.items()
        },
        "queued_status_update": MagicMock(),
        "queued_text_update": MagicMock(),
        "queued_text_update_replace_last_line": MagicMock(),
        "progress_bar_cb": MagicMock(),
        "caught_error": MagicMock(),
        "context": context,
    }


def _base_path(tmp_path: Path) -> Path:
    return tmp_path / f"release{BASE_TORRENT_SUFFIX}"


# --------------------------------------------------------------------------
def test_the_base_is_written_outside_every_tracker_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It must not be any tracker's artifact, and it must not be reachable by
    the `*/<stem>.torrent` glob a saved job uses to find its clone source."""
    context = _context(tmp_path)
    backend = _backend(monkeypatch)

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    base = _base_path(tmp_path)
    assert base.is_file()
    assert base not in set(_tracker_paths(tmp_path).values())
    assert base.parent == tmp_path
    assert not list(tmp_path.glob(f"*/{base.name}"))


def test_the_base_carries_no_tracker_identity_after_a_full_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    backend = _backend(monkeypatch)

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    base = Torrent.read(_base_path(tmp_path))
    assert "announce" not in base.metainfo
    assert "announce-list" not in base.metainfo
    assert "comment" not in base.metainfo
    assert "source" not in base.metainfo["info"]


def test_the_first_tracker_gets_a_stamped_clone_like_every_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no longer a privileged first tracker whose own file becomes the
    base -- that asymmetry is what the aliasing bug rested on."""
    context = _context(tmp_path)
    backend = _backend(monkeypatch)
    cloned_from: list[Path] = []
    real_clone = process_module.clone_torrent

    def recording_clone(**kwargs: Any) -> Any:
        cloned_from.append(kwargs["base_torrent_file"])
        return real_clone(**kwargs)

    monkeypatch.setattr(process_module, "clone_torrent", recording_clone)

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    assert len(cloned_from) == len(_TRACKERS)
    assert set(cloned_from) == {_base_path(tmp_path)}


def test_every_tracker_gets_only_its_own_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    backend = _backend(monkeypatch)

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    paths = _tracker_paths(tmp_path)
    aither = Torrent.read(paths[TrackerSelection.AITHER])
    lst = Torrent.read(paths[TrackerSelection.LST])

    assert aither.trackers == [["https://aither.invalid/AITHERKEY/announce"]]
    assert aither.metainfo["info"]["source"] == "Aither"  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert aither.comment == "Uploaded to Aither"

    assert lst.trackers == [["https://lst.invalid/LSTKEY/announce"]]
    assert lst.metainfo["info"]["source"] == "LST.GG"  # pyright: ignore[reportTypedDictNotRequiredAccess]
    # LST configures no comment, so it must not inherit Aither's
    assert lst.comment is None
    assert "comment" not in lst.metainfo


def test_a_tracker_rewriting_its_own_torrent_cannot_reach_the_next_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression test for the reported bug.

    Stands in for the UNIT3D redownload: the moment a tracker's torrent is
    written, its server replaces it in place with an edited copy. Before the
    neutral base, that file *was* the clone source, so the next tracker
    inherited the edit -- observed in the wild as ReelFliX shipping
    "Edited by LST.GG. Edited by ReelFliX" and TorrentLeech shipping
    "Edited by LST.GG" with no edit of its own.
    """
    context = _context(tmp_path)
    backend = _backend(monkeypatch)
    tracker_dirs = {tmp_path / str(tracker).lower() for tracker in _TRACKERS}
    real_write = process_module.write_torrent

    def server_rewriting_write(torrent_instance: Any, torrent_path: Path) -> Path:
        written = real_write(torrent_instance, torrent_path)
        if written.parent in tracker_dirs:
            rewritten = Torrent.read(written)
            rewritten.metainfo["announce"] = "https://server.invalid/STAMPED/announce"
            rewritten.metainfo["info"]["source"] = "SERVER"
            rewritten.comment = "Rewritten by the tracker"
            rewritten.metainfo["created by"] = (
                f"{rewritten.metainfo.get('created by')}. Edited by SERVER"
            )
            real_write(Torrent.copy(rewritten), written)
        return written

    monkeypatch.setattr(process_module, "write_torrent", server_rewriting_write)

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    # the base is untouched by any tracker's rewrite
    base = Torrent.read(_base_path(tmp_path))
    assert "announce" not in base.metainfo
    assert "source" not in base.metainfo["info"]
    assert base.metainfo["created by"] == NFO_FORGE_CREATOR

    # and the run's own logs prove every tracker cloned from it: each tracker
    # file carries exactly one "Edited by", its own, with no inherited chain
    for path in _tracker_paths(tmp_path).values():
        stamped = Torrent.read(path)
        assert stamped.metainfo["created by"].count("Edited by") == 1


def test_a_carried_base_is_neutralized_into_the_run_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resumed job must leave a base where a re-save can find it, and that
    copy must be free of the tracker identity a legacy base carries."""
    context = _context(tmp_path)
    carried = tmp_path / "job" / "base.torrent"
    carried.parent.mkdir()
    legacy = generate_torrent(
        path=context.media_input.require_input_path(),
        piece_exponent=16,
        cb=lambda *_a: None,
    )
    legacy.metainfo["announce"] = "https://legacy.invalid/OLDKEY/announce"
    legacy.metainfo["info"]["source"] = "Legacy"
    legacy.metainfo["created by"] = "mkbrr/1.24.0. Edited by LST.GG"
    legacy.write(carried, overwrite=True)
    context.shared_data.base_torrent = carried

    backend = _backend(monkeypatch)
    hashed = MagicMock(side_effect=AssertionError("must not re-hash"))
    monkeypatch.setattr(process_module, "generate_torrent", hashed)

    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    base = _base_path(tmp_path)
    assert base.is_file()
    neutralized = Torrent.read(base)
    assert "announce" not in neutralized.metainfo
    assert "source" not in neutralized.metainfo["info"]
    assert neutralized.metainfo["created by"] == NFO_FORGE_CREATOR
    # the job's own copy is never mutated
    assert Torrent.read(carried).metainfo["announce"]


def test_an_unreadable_carried_base_falls_back_to_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Better to spend the hash than to stamp from a base we could not confirm
    is free of another tracker's identity."""
    context = _context(tmp_path)
    carried = tmp_path / "job" / "base.torrent"
    carried.parent.mkdir()
    carried.write_bytes(b"not a torrent")
    context.shared_data.base_torrent = carried

    backend = _backend(monkeypatch)
    backend.process_trackers(**_kwargs(context, tmp_path), phase=RunPhase.PREPARE)

    base = Torrent.read(_base_path(tmp_path))
    assert "announce" not in base.metainfo
    assert base.metainfo["created by"] == NFO_FORGE_CREATOR
