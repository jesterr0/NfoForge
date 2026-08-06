"""Round-trip coverage for saving and restoring a processing context."""

from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any
import wave

from pymediainfo import MediaInfo
import pytest

from src.backend.jobs.codec import (
    JobCodecError,
    context_from_dict,
    context_to_dict,
    filter_context_document,
    mediainfo_xml,
)
from src.context.factory import create_processing_context
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.enums.tmdb_genres import TMDBGenreIDsMovies
from src.enums.torrent_client import TorrentClientSelection
from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import (
    ComparisonPair,
    ImageUploadData,
    ImageUploadFromTo,
)
from src.plugins.api import MetadataMediaKind
from src.plugins.manager import PluginManager


def _config_payload() -> Any:
    return SimpleNamespace(
        templates=SimpleNamespace(
            trim_blocks=True,
            lstrip_blocks=False,
            newline_sequence="\r\n",
            keep_trailing_newline=True,
        ),
        general=SimpleNamespace(enable_plugins=False),
    )


def _new_context() -> ProcessingContext:
    return create_processing_context(_config_payload(), PluginManager())


def _write_sample_media(path: Path) -> Path:
    """Write a tiny real media file libmediainfo can actually parse.

    A synthesized WAV keeps this dependency-free -- no encoder needed -- while
    still exercising the real libmediainfo parse/dump path rather than a
    stubbed one.
    """
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(struct.pack("<" + "h" * 4800, *([0] * 4800)))
    return path


@pytest.fixture
def sample_media(tmp_path: Path) -> Path:
    return _write_sample_media(tmp_path / "Example.Movie.2024.wav")


def _populate(context: ProcessingContext, media: Path) -> None:
    media_input = context.media_input
    media_input.input_path = media
    media_input.media_type = MediaType.MOVIE
    media_input.working_dir = media.parent / "working"
    media_input.file_list.append(media)
    media_input.file_list_mediainfo[media] = MediaInfo.parse(
        media, legacy_stream_display=True
    )
    media_input.comparison_pair = ComparisonPair(source=media, media=media, script=None)
    media_input.series_episode_format = EpisodeFormat.DAILY_DATE

    media_search = context.media_search
    media_search.media_type = MediaType.MOVIE
    media_search.imdb_id = "tt1234567"
    media_search.tmdb_id = "603"
    media_search.tmdb_data = {"title": "Example", "genres": [{"name": "Action"}]}
    media_search.title = "Example"
    media_search.year = 2024
    media_search.genres.append(TMDBGenreIDsMovies.ACTION)
    media_search.genre_names = ("Action", "Drama")
    media_search.media_kind = MetadataMediaKind.MOVIE
    media_search.plugin_data["note"] = "kept"

    shared = context.shared_data
    shared.url_data.append(ImageUploadData(url="https://x/1", medium_url=None))
    shared.selected_trackers = [TrackerSelection.AITHER, TrackerSelection.HUNO]
    shared.loaded_images = [media.parent / "img1.png"]
    shared.generated_images = True
    shared.release_notes = "notes"
    shared.dynamic_data["edition_override"] = "Director's Cut"
    shared.tracker_image_hosts[TrackerSelection.AITHER] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.CHEVERETO_V3
    )
    shared.tracker_image_hosts[TrackerSelection.HUNO] = ImageUploadFromTo(
        ImageSource.URLS, ImageSource.URLS
    )

    context.torrent_client_options.save_path_overrides[
        TorrentClientSelection.QBITTORRENT
    ] = "/downloads"


def testmediainfo_xml_round_trips_every_field(sample_media: Path) -> None:
    reference = MediaInfo.parse(sample_media, legacy_stream_display=True)

    restored = MediaInfo(mediainfo_xml(sample_media))

    assert len(restored.tracks) == len(reference.tracks)
    assert restored.tracks, "round-tripped MediaInfo must not be empty"
    for reference_track, restored_track in zip(
        reference.tracks, restored.tracks, strict=False
    ):
        assert restored_track.to_data() == reference_track.to_data()


def test_mediainfo_capture_fails_loudly_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(JobCodecError):
        mediainfo_xml(tmp_path / "does-not-exist.mkv")


def test_context_round_trip_preserves_payloads(sample_media: Path) -> None:
    source = _new_context()
    _populate(source, sample_media)

    document = context_to_dict(source)
    restored = _new_context()
    context_from_dict(document, restored)

    media_input = restored.media_input
    assert media_input.input_path == sample_media
    assert media_input.media_type is MediaType.MOVIE
    assert media_input.working_dir == source.media_input.working_dir
    assert media_input.file_list == [sample_media]
    assert media_input.comparison_pair == source.media_input.comparison_pair
    assert media_input.series_episode_format is EpisodeFormat.DAILY_DATE

    media_search = restored.media_search
    assert media_search.imdb_id == "tt1234567"
    assert media_search.tmdb_id == "603"
    assert media_search.tmdb_data == source.media_search.tmdb_data
    assert media_search.title == "Example"
    assert media_search.year == 2024
    assert media_search.genres == [TMDBGenreIDsMovies.ACTION]
    assert media_search.genre_names == ("Action", "Drama")
    assert media_search.media_kind is MetadataMediaKind.MOVIE
    assert media_search.plugin_data == {"note": "kept"}

    shared = restored.shared_data
    assert shared.url_data == [ImageUploadData(url="https://x/1", medium_url=None)]
    assert shared.selected_trackers == [TrackerSelection.AITHER, TrackerSelection.HUNO]
    assert shared.loaded_images == [sample_media.parent / "img1.png"]
    assert shared.generated_images is True
    assert shared.is_comparison_images is False
    assert shared.release_notes == "notes"
    assert shared.dynamic_data == {"edition_override": "Director's Cut"}
    assert shared.tracker_image_hosts == source.shared_data.tracker_image_hosts

    assert restored.torrent_client_options.save_path_overrides == {
        TorrentClientSelection.QBITTORRENT: "/downloads"
    }


def test_unused_output_fields_are_not_serialized(sample_media: Path) -> None:
    """`generated_torrents`/`uploaded_images` are never written by a real run.

    Nothing in `process_trackers()` populates them, so storing them only ever
    persisted empty dicts while implying a job carried per-tracker output
    state. Keep them out of the document so nothing comes to depend on them.
    """
    source = _new_context()
    _populate(source, sample_media)
    source.generated_torrents["Aither"] = sample_media.parent / "a.torrent"

    document = context_to_dict(source)

    assert "generated_torrents" not in document
    assert "uploaded_images" not in document


def test_document_without_the_old_output_keys_decodes(sample_media: Path) -> None:
    source = _new_context()
    _populate(source, sample_media)
    document = context_to_dict(source)

    restored = _new_context()
    context_from_dict(document, restored)

    assert restored.generated_torrents == {}
    assert restored.uploaded_images == {}


def test_round_trip_restores_usable_mediainfo(sample_media: Path) -> None:
    source = _new_context()
    _populate(source, sample_media)
    document = context_to_dict(source)

    restored = _new_context()
    context_from_dict(document, restored)

    reference = source.media_input.require_mediainfo(sample_media)
    round_tripped = restored.media_input.require_mediainfo(sample_media)

    assert [track.track_type for track in round_tripped.tracks] == [
        track.track_type for track in reference.tracks
    ]
    for reference_track, restored_track in zip(
        reference.tracks, round_tripped.tracks, strict=False
    ):
        assert restored_track.to_data() == reference_track.to_data()


def test_round_trip_does_not_need_the_media_file_present(
    sample_media: Path,
) -> None:
    """Restoring must not re-read the media, so a moved file still loads."""
    source = _new_context()
    _populate(source, sample_media)
    document = context_to_dict(source)
    sample_media.unlink()

    restored = _new_context()
    context_from_dict(document, restored)

    assert restored.media_input.require_mediainfo(sample_media).tracks


def test_restore_keeps_jinja_globals_pointing_at_live_payloads(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)
    document = context_to_dict(source)

    restored = _new_context()
    context_from_dict(document, restored)

    globals_ = restored.jinja_engine.environment.globals
    assert globals_["nf_shared_data"] is restored.shared_data
    assert globals_["nf_media_search_payload"] is restored.media_search
    assert globals_["nf_media_input_payload"] is restored.media_input
    assert globals_["nf_media_search_payload"].title == "Example"
    assert globals_["nf_shared_data"].release_notes == "notes"


def test_restore_clears_state_left_over_from_a_previous_run(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)
    document = context_to_dict(source)

    restored = _new_context()
    restored.shared_data.release_notes = "stale"
    restored.shared_data.dynamic_data["stale"] = True
    restored.media_input.file_list.append(Path("stale.mkv"))
    context_from_dict(document, restored)

    assert restored.shared_data.release_notes == "notes"
    assert "stale" not in restored.shared_data.dynamic_data
    assert Path("stale.mkv") not in restored.media_input.file_list


def test_non_serializable_dynamic_data_is_dropped_not_fatal(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)
    source.shared_data.dynamic_data["bad"] = object()

    document = context_to_dict(source)

    assert "bad" not in document["shared_data"]["dynamic_data"]
    assert document["shared_data"]["dynamic_data"]["edition_override"] == (
        "Director's Cut"
    )


def test_missing_section_is_rejected() -> None:
    with pytest.raises(JobCodecError):
        context_from_dict({"media_input": {}}, _new_context())


# --------------------------------------------------------------------------
# narrowing a job to the trackers that still need uploading
# --------------------------------------------------------------------------
def test_filtering_keeps_only_the_requested_trackers(sample_media: Path) -> None:
    """The duplicate-upload guard: a deferred job must drop what already went.

    Rather than marking completed trackers as done and trusting resume to skip
    them, they are removed outright -- so there is no code path by which a
    resumed job could upload them again.
    """
    source = _new_context()
    _populate(source, sample_media)

    filtered = filter_context_document(context_to_dict(source), {TrackerSelection.HUNO})

    shared = filtered["shared_data"]
    assert shared["selected_trackers"] == [TrackerSelection.HUNO.name]
    assert list(shared["tracker_image_hosts"]) == [TrackerSelection.HUNO.name]


def test_filtering_restores_as_a_job_with_only_those_trackers(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)

    filtered = filter_context_document(context_to_dict(source), {TrackerSelection.HUNO})
    restored = _new_context()
    context_from_dict(filtered, restored)

    assert restored.shared_data.selected_trackers == [TrackerSelection.HUNO]
    assert set(restored.shared_data.tracker_image_hosts) == {TrackerSelection.HUNO}
    # everything not tracker-scoped must survive untouched
    assert restored.media_input.input_path == sample_media
    assert restored.media_search.title == "Example"


def test_filtering_does_not_mutate_the_original_document(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)
    document = context_to_dict(source)

    filter_context_document(document, {TrackerSelection.HUNO})

    assert len(document["shared_data"]["tracker_image_hosts"]) == 2
    assert len(document["shared_data"]["selected_trackers"]) == 2


def test_filtering_to_nothing_yields_an_empty_tracker_set(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)

    filtered = filter_context_document(context_to_dict(source), set())

    assert filtered["shared_data"]["selected_trackers"] == []
    assert filtered["shared_data"]["tracker_image_hosts"] == {}
