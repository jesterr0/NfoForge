"""Unit coverage for the 5 UNIT3D trackers added alongside HDBits: Blutopia,
SeedPool, UTP, Yu-scene, and FearNoPeer. Each is a thin parametrization of
the shared Unit3dBaseUploader/Unit3dBaseSearch pair (src/backend/trackers/
unit3d_base.py) -- these tests lock in the per-site category/type/
resolution ID mapping, UTP's narrower resolution support, and Blutopia's
mod_queue_opt_in field (the one place these 5 aren't all identical)."""

from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest.mock import patch

from pymediainfo import MediaInfo
import pytest

from src.backend.trackers.blutopia import BlutopiaUploader, blu_uploader
from src.backend.trackers.fearnopeer import FearNoPeerUploader, fnp_uploader
from src.backend.trackers.seedpool import SeedPoolUploader, sp_uploader
from src.backend.trackers.unit3d_base import Unit3dBaseUploader
from src.backend.trackers.utp import UTPUploader, utp_uploader
from src.backend.trackers.yuscene import YuSceneUploader, yus_uploader
from src.enums.media_type import MediaType
from src.enums.trackers.blutopia import (
    BlutopiaCategory,
    BlutopiaResolution,
    BlutopiaType,
)
from src.enums.trackers.fearnopeer import FearNoPeerType
from src.enums.trackers.seedpool import SeedPoolType
from src.enums.trackers.utp import UTPResolution, UTPType
from src.enums.trackers.yuscene import YuSceneType
from src.exceptions import TrackerError
from src.payloads.media_search import MediaSearchPayload


def _uploader(
    uploader_cls: Callable[..., Unit3dBaseUploader],
    tmp_path: Path,
    filename: str,
    media_type: MediaType = MediaType.MOVIE,
) -> Unit3dBaseUploader:
    return uploader_cls(
        media_type=media_type,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=tmp_path / filename,
        mediainfo_obj=cast(MediaInfo, object()),
    )


def _mediainfo_obj() -> MediaInfo:
    """A real (if minimal) 1080p MediaInfo object -- needed for anything
    touching resolution/standard-definition detection, unlike category/type
    detection above which is filename-only and tolerates a bare object()."""
    return MediaInfo(
        """<Mediainfo><File>
        <track type="General"><Duration>60000</Duration><File_size>1000</File_size></track>
        <track type="Video"><Width>1920</Width><Height>1080</Height><Scan_type>Progressive</Scan_type><Frame_rate>24.000</Frame_rate><Format>AVC</Format></track>
        <track type="Audio"><Format>AC-3</Format><Channel_s>2</Channel_s><Language>en</Language></track>
        </File></Mediainfo>"""
    )


def _uploader_with_real_mediainfo(
    uploader_cls: Callable[..., Unit3dBaseUploader],
    tmp_path: Path,
    filename: str,
    media_type: MediaType = MediaType.MOVIE,
) -> Unit3dBaseUploader:
    input_path = tmp_path / filename
    input_path.write_bytes(b"placeholder")
    return uploader_cls(
        media_type=media_type,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=input_path,
        mediainfo_obj=_mediainfo_obj(),
    )


@pytest.mark.parametrize(
    ("uploader_cls", "expected"),
    [
        (BlutopiaUploader, BlutopiaCategory.MOVIE.value),
        (SeedPoolUploader, "1"),
        (UTPUploader, "1"),
        (YuSceneUploader, "1"),
        (FearNoPeerUploader, "1"),
    ],
)
def test_movie_category_id(
    uploader_cls: type[Unit3dBaseUploader], expected: str, tmp_path: Path
) -> None:
    uploader = _uploader(uploader_cls, tmp_path, "Example.Movie.2026.1080p.WEB-DL.mkv")
    assert uploader._get_category_id() == expected


@pytest.mark.parametrize(
    ("uploader_cls", "filename", "expected"),
    [
        (
            BlutopiaUploader,
            "Example.Movie.2026.1080p.WEB-DL.H264.mkv",
            BlutopiaType.WEBDL.value,
        ),
        (
            BlutopiaUploader,
            "Example.Movie.2026.1080p.BluRay.REMUX.AVC.mkv",
            BlutopiaType.REMUX.value,
        ),
        (
            SeedPoolUploader,
            "Example.Movie.2026.1080p.WEB-DL.H264.mkv",
            SeedPoolType.WEBDL.value,
        ),
        (
            UTPUploader,
            "Example.Movie.2026.1080p.WEB-DL.H264.mkv",
            UTPType.WEBDL.value,
        ),
        (
            YuSceneUploader,
            "Example.Movie.2026.1080p.BluRay.REMUX.AVC.mkv",
            YuSceneType.REMUX.value,
        ),
        (
            FearNoPeerUploader,
            "Example.Movie.2026.1080p.HDTV.H264.mkv",
            FearNoPeerType.HDTV.value,
        ),
    ],
)
def test_type_id_mapping(
    uploader_cls: type[Unit3dBaseUploader],
    filename: str,
    expected: str,
    tmp_path: Path,
) -> None:
    uploader = _uploader(uploader_cls, tmp_path, filename)
    assert uploader._get_type_id() == expected


def test_utp_supports_narrower_resolution_range_than_the_others(
    tmp_path: Path,
) -> None:
    """UTP only ranks 1080i and above; 480p correctly has no mapping."""
    uploader = _uploader_with_real_mediainfo(
        UTPUploader, tmp_path, "Example.Movie.2026.1080p.WEB-DL.H264.mkv"
    )
    assert uploader._get_resolution_id() == UTPResolution.RES_1080P.value

    below_utp_range = _uploader_with_real_mediainfo(
        UTPUploader, tmp_path, "Example.Movie.2026.480p.WEB-DL.H264.mkv"
    )
    with pytest.raises(TrackerError, match="Resolution ID"):
        below_utp_range._get_resolution_id()


def test_seedpool_supports_the_full_resolution_range(tmp_path: Path) -> None:
    """The other 4 (unlike UTP) support down to 480i, matching Aither/etc."""
    uploader = _uploader_with_real_mediainfo(
        SeedPoolUploader, tmp_path, "Example.Movie.2026.480p.WEB-DL.H264.mkv"
    )
    assert uploader._get_resolution_id() == "8"


def test_blutopia_1440p_and_1080p_share_the_same_resolution_id(
    tmp_path: Path,
) -> None:
    """Blutopia's own ID table maps 1440p and 1080p to the same tier (2);
    NfoForge doesn't detect 1440p from a filename at all (no tracker does),
    so both resolve via the 1080p path -- this documents the source data,
    not a NfoForge behavior difference from the other 4 trackers."""
    uploader = _uploader_with_real_mediainfo(
        BlutopiaUploader, tmp_path, "Example.Movie.2026.1080p.WEB-DL.H264.mkv"
    )
    assert uploader._get_resolution_id() == BlutopiaResolution.RES_1080P.value == "2"


def test_blutopia_mod_queue_opt_in_reaches_the_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # _standard_definition() reads mediainfo width/height as ints, which the
    # raw-XML MediaInfo() constructor returns as strings -- same workaround
    # test_tracker_series_support.py's Unit3dBaseUploader payload tests use.
    monkeypatch.setattr(BlutopiaUploader, "_standard_definition", lambda self: False)
    uploader = _uploader_with_real_mediainfo(
        BlutopiaUploader, tmp_path, "Example.Movie.2026.1080p.WEB-DL.H264.mkv"
    )

    payload = uploader._build_upload_payload(
        tracker_title=None,
        opt_in_to_mod_queue=True,
    )

    assert payload["mod_queue_opt_in"] == 1


@pytest.mark.parametrize(
    "uploader_cls",
    [SeedPoolUploader, UTPUploader, YuSceneUploader, FearNoPeerUploader],
)
def test_only_blutopia_and_lst_and_shareisland_get_mod_queue_field(
    uploader_cls: type[Unit3dBaseUploader],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other 4 have no mod-queue field on their own tracker, so passing
    opt_in_to_mod_queue must be a silent no-op rather than sending a field
    the site doesn't have."""
    monkeypatch.setattr(uploader_cls, "_standard_definition", lambda self: False)
    uploader = _uploader_with_real_mediainfo(
        uploader_cls, tmp_path, "Example.Movie.2026.1080p.WEB-DL.H264.mkv"
    )

    payload = uploader._build_upload_payload(
        tracker_title=None,
        opt_in_to_mod_queue=True,
    )

    assert "mod_queue_opt_in" not in payload
    assert "opt_in_to_mod_queue" not in payload


def test_supplied_tracker_title_is_formatted_in_the_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A title the user edited in the overview dialog goes through
    generate_release_title too, rather than reaching the tracker verbatim --
    the dialog tells the user required formatting is applied automatically,
    and TorrentLeech already re-applied it at upload time."""
    monkeypatch.setattr(BlutopiaUploader, "_standard_definition", lambda self: False)
    uploader = _uploader_with_real_mediainfo(
        BlutopiaUploader, tmp_path, "Example.Movie.2026.1080p.WEB-DL.H264.mkv"
    )

    payload = uploader._build_upload_payload(
        tracker_title="Example.Movie.2026.1080p.WEB-DL.AAC.2.0.H.264-GRP",
    )

    # separators converted, audio channel layout kept intact
    assert payload["name"] == "Example Movie 2026 1080p WEB-DL AAC 2.0 H 264-GRP"


@pytest.mark.parametrize(
    ("wrapper", "uploader_cls_path"),
    [
        (blu_uploader, "src.backend.trackers.blutopia.BlutopiaUploader.upload"),
        (sp_uploader, "src.backend.trackers.seedpool.SeedPoolUploader.upload"),
        (utp_uploader, "src.backend.trackers.utp.UTPUploader.upload"),
        (yus_uploader, "src.backend.trackers.yuscene.YuSceneUploader.upload"),
        (
            fnp_uploader,
            "src.backend.trackers.fearnopeer.FearNoPeerUploader.upload",
        ),
    ],
)
def test_wrapper_forwards_personal_release_to_upload(
    wrapper: Callable[..., bool | None],
    uploader_cls_path: str,
    tmp_path: Path,
) -> None:
    """Guards against the DarkPeers-shaped gap this session found and fixed
    (personal_release configured in the UI but the wrapper function never
    accepted/forwarded it to .upload(), so it silently never reached the
    tracker) recurring for any of these 5."""
    kwargs: dict[str, object] = {
        "media_type": MediaType.MOVIE,
        "api_key": "api-key",
        "torrent_file": tmp_path / "upload.torrent",
        "input_path": tmp_path / "Example.Movie.2026.1080p.WEB-DL.H264.mkv",
        "tracker_title": "Example Movie 2026",
        "nfo": "",
        "internal": False,
        "anonymous": False,
        "personal_release": True,
        "mediainfo_obj": cast(MediaInfo, object()),
        "media_search_payload": MediaSearchPayload(),
    }
    if wrapper is blu_uploader:
        kwargs["opt_in_to_mod_queue"] = True

    with patch(uploader_cls_path, return_value=True) as upload:
        wrapper(**kwargs)

    assert upload.call_args.kwargs["personal_release"] is True
    if wrapper is blu_uploader:
        assert upload.call_args.kwargs["opt_in_to_mod_queue"] is True
