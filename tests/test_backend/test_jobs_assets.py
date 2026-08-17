"""Coverage for the files a job copies in so it stops depending on `processing/`."""

import os
from pathlib import Path
import struct
import wave

from pymediainfo import MediaInfo
import pytest
from torf import Torrent

from src.backend.jobs.assets import (
    JobAssetError,
    MediaFingerprint,
    archived_base_is_valid,
    base_torrent_path,
    base_torrent_snapshot,
    capture_mediainfo,
    copy_base_torrent,
    copy_images,
    fingerprint_files,
    fingerprints_match,
    read_job_asset,
    torrent_content_files,
)
from src.backend.utils.media_info_utils import (
    MinimalMediaInfo,
    cache_full_mi_str,
    clear_full_mi_str_cache,
)


@pytest.fixture(autouse=True)
def _clear_mi_cache() -> None:
    clear_full_mi_str_cache()


@pytest.fixture
def sample_media(tmp_path: Path) -> Path:
    path = tmp_path / "Example.Movie.2024.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(struct.pack("<" + "h" * 2400, *([0] * 2400)))
    return path


@pytest.fixture
def job_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "jobs" / "abc123"
    directory.mkdir(parents=True)
    return directory


# --------------------------------------------------------------------------
# screenshots
# --------------------------------------------------------------------------
def test_images_are_copied_so_cleanup_cannot_reach_them(
    tmp_path: Path, job_directory: Path
) -> None:
    processing = tmp_path / "processing" / "run" / "images"
    processing.mkdir(parents=True)
    first = processing / "a.png"
    first.write_bytes(b"first")
    second = processing / "b.png"
    second.write_bytes(b"second")

    copied = copy_images(job_directory, [first, second])

    assert [path.read_bytes() for path in copied] == [b"first", b"second"]
    assert all(job_directory in path.parents for path in copied)
    # the originals being destroyed must not affect the job's copies
    first.unlink()
    second.unlink()
    assert [path.read_bytes() for path in copied] == [b"first", b"second"]


def test_same_named_images_from_different_folders_both_survive(
    tmp_path: Path, job_directory: Path
) -> None:
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "shot.png").write_bytes(b"first")
    (second_dir / "shot.png").write_bytes(b"second")

    copied = copy_images(
        job_directory, [first_dir / "shot.png", second_dir / "shot.png"]
    )

    assert len(copied) == 2
    assert {path.read_bytes() for path in copied} == {b"first", b"second"}


def test_a_missing_image_is_skipped_rather_than_failing_the_save(
    tmp_path: Path, job_directory: Path
) -> None:
    present = tmp_path / "there.png"
    present.write_bytes(b"x")

    copied = copy_images(job_directory, [present, tmp_path / "gone.png"])

    assert len(copied) == 1


def test_no_images_creates_nothing(job_directory: Path) -> None:
    assert copy_images(job_directory, []) == []


def test_archived_base_validates_without_the_source(
    tmp_path: Path, job_directory: Path
) -> None:
    media = tmp_path / "release.bin"
    media.write_bytes(b"archive payload")
    torrent = Torrent(path=media, private=True)
    torrent.generate()
    base = job_directory / "base.torrent"
    torrent.write(base)
    snapshot = base_torrent_snapshot(base)

    media.unlink()

    assert snapshot["mode"] == "singlefile"
    assert snapshot["content_size"] == len(b"archive payload")
    assert archived_base_is_valid(base, snapshot)


def test_archived_base_rejects_tampering(tmp_path: Path, job_directory: Path) -> None:
    media = tmp_path / "release.bin"
    media.write_bytes(b"archive payload")
    torrent = Torrent(path=media, private=True)
    torrent.generate()
    base = job_directory / "base.torrent"
    torrent.write(base)
    snapshot = base_torrent_snapshot(base)

    base.write_bytes(base.read_bytes() + b"tampered")

    assert not archived_base_is_valid(base, snapshot)


# --------------------------------------------------------------------------
# mediainfo
# --------------------------------------------------------------------------
def test_mediainfo_is_stored_as_both_xml_and_text(
    job_directory: Path, sample_media: Path
) -> None:
    captured = capture_mediainfo(job_directory, [sample_media])

    names = captured[sample_media]
    xml = read_job_asset(job_directory, names["xml"])
    text = read_job_asset(job_directory, names["text"])

    assert xml and "<track" in xml
    assert text and "General" in text


def test_stored_xml_rebuilds_the_object_without_the_media(
    job_directory: Path, sample_media: Path
) -> None:
    reference = MediaInfo.parse(sample_media, legacy_stream_display=True)
    captured = capture_mediainfo(job_directory, [sample_media])
    sample_media.unlink()

    xml = read_job_asset(job_directory, captured[Path(str(sample_media))]["xml"])
    assert xml is not None
    restored = MediaInfo(xml)

    assert [track.to_data() for track in restored.tracks] == [
        track.to_data() for track in reference.tracks
    ]


def test_cached_text_means_the_media_is_never_re_read(
    job_directory: Path, sample_media: Path
) -> None:
    """The text dump is what trackers are sent and cannot be derived from XML.

    Caching it is the whole reason a resumed job stops calling MediaInfo.parse.
    """
    captured = capture_mediainfo(job_directory, [sample_media])
    text = read_job_asset(job_directory, captured[sample_media]["text"])
    assert text is not None
    expected = MinimalMediaInfo(sample_media).get_full_mi_str()

    cache_full_mi_str(sample_media, text)
    sample_media.unlink()

    assert MinimalMediaInfo(sample_media).get_full_mi_str() == expected


def test_cache_is_cleared_between_jobs(job_directory: Path, sample_media: Path) -> None:
    cache_full_mi_str(sample_media, "stale dump")
    clear_full_mi_str_cache()

    # falls back to reading the (still present) file rather than serving stale
    assert MinimalMediaInfo(sample_media).get_full_mi_str() != "stale dump"


def test_capturing_a_missing_file_fails_loudly(
    job_directory: Path, tmp_path: Path
) -> None:
    with pytest.raises(JobAssetError):
        capture_mediainfo(job_directory, [tmp_path / "nope.mkv"])


def test_reading_an_absent_asset_returns_none(job_directory: Path) -> None:
    assert read_job_asset(job_directory, "missing.xml") is None


# --------------------------------------------------------------------------
# base torrent + fingerprint
# --------------------------------------------------------------------------
def test_base_torrent_is_copied_and_found(tmp_path: Path, job_directory: Path) -> None:
    torrent = tmp_path / "release.torrent"
    torrent.write_bytes(b"d8:announce")

    copy_base_torrent(job_directory, torrent)

    stored = base_torrent_path(job_directory)
    assert stored is not None
    assert stored.read_bytes() == b"d8:announce"


def test_no_base_torrent_reports_none(job_directory: Path) -> None:
    assert base_torrent_path(job_directory) is None


def test_fingerprint_detects_a_changed_media_file(sample_media: Path) -> None:
    """Guards against cloning a torrent whose piece hashes no longer match."""
    fingerprint = MediaFingerprint.of(sample_media)
    assert fingerprint.matches(sample_media)

    sample_media.write_bytes(b"completely different content")

    assert not fingerprint.matches(sample_media)


def test_fingerprint_detects_a_changed_mtime_at_the_same_size(tmp_path: Path) -> None:
    """Isolates the mtime half of the comparison: the test above changes size
    too, so it alone would still pass with mtime comparison dropped."""
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"same length")
    fingerprint = MediaFingerprint.of(media)

    media.write_bytes(b"still same!")  # same byte count, different content
    bumped = fingerprint.mtime_ns + 1_000_000_000
    os.utime(media, ns=(bumped, bumped))

    assert media.stat().st_size == fingerprint.size
    assert not fingerprint.matches(media)


def test_fingerprint_of_a_missing_file_never_matches(tmp_path: Path) -> None:
    fingerprint = MediaFingerprint(size=1, mtime_ns=1)

    assert not fingerprint.matches(tmp_path / "gone.mkv")


def test_fingerprint_round_trips(sample_media: Path) -> None:
    fingerprint = MediaFingerprint.of(sample_media)

    assert MediaFingerprint.from_dict(fingerprint.to_dict()) == fingerprint
    assert MediaFingerprint.from_dict({"size": "nope"}) is None
    assert MediaFingerprint.from_dict(None) is None


def test_torrent_content_files_walks_a_directory(tmp_path: Path) -> None:
    pack = tmp_path / "Pack.S01"
    (pack / "sub").mkdir(parents=True)
    (pack / "e01.mkv").write_bytes(b"a")
    (pack / "sub" / "e02.mkv").write_bytes(b"b")

    assert torrent_content_files(pack) == [
        pack / "e01.mkv",
        pack / "sub" / "e02.mkv",
    ]


def test_torrent_content_files_of_a_single_file_is_that_file(tmp_path: Path) -> None:
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"a")

    assert torrent_content_files(media) == [media]


def test_fingerprints_match_an_unchanged_pack(tmp_path: Path) -> None:
    pack = tmp_path / "Pack.S01"
    pack.mkdir()
    (pack / "e01.mkv").write_bytes(b"a")
    (pack / "e02.mkv").write_bytes(b"bb")

    stored = fingerprint_files(torrent_content_files(pack))

    assert fingerprints_match(stored, pack) is True


def test_a_changed_second_file_invalidates_the_pack(tmp_path: Path) -> None:
    """The whole point: episode 1 alone cannot vouch for the torrent."""
    pack = tmp_path / "Pack.S01"
    pack.mkdir()
    (pack / "e01.mkv").write_bytes(b"a")
    (pack / "e02.mkv").write_bytes(b"bb")
    stored = fingerprint_files(torrent_content_files(pack))

    (pack / "e02.mkv").write_bytes(b"changed")

    assert fingerprints_match(stored, pack) is False


def test_an_added_file_invalidates_the_pack(tmp_path: Path) -> None:
    pack = tmp_path / "Pack.S01"
    pack.mkdir()
    (pack / "e01.mkv").write_bytes(b"a")
    stored = fingerprint_files(torrent_content_files(pack))

    (pack / "e02.mkv").write_bytes(b"b")

    assert fingerprints_match(stored, pack) is False


def test_a_removed_file_invalidates_the_pack(tmp_path: Path) -> None:
    pack = tmp_path / "Pack.S01"
    pack.mkdir()
    (pack / "e01.mkv").write_bytes(b"a")
    (pack / "e02.mkv").write_bytes(b"b")
    stored = fingerprint_files(torrent_content_files(pack))

    (pack / "e02.mkv").unlink()

    assert fingerprints_match(stored, pack) is False


def test_an_empty_record_never_matches(tmp_path: Path) -> None:
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"a")

    assert fingerprints_match({}, media) is False
    assert fingerprints_match(None, media) is False
