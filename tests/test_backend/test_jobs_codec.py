"""Round-trip coverage for saving and restoring a processing context."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pymediainfo import MediaInfo, Track
import pytest

from src.backend.jobs.assets import capture_mediainfo, read_job_asset
from src.backend.jobs.codec import (
    JobCodecError,
    context_from_dict,
    context_to_dict,
    filter_context_document,
    mediainfo_sources,
    mediainfo_xml,
    reselect_trackers,
)
from src.backend.jobs.store import load_job
from src.backend.utils.media_info_utils import (
    MinimalMediaInfo,
    clear_restored_mediainfo,
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
from tests.conftest import SourceLessBundle, write_sample_media


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


@pytest.fixture
def sample_media(tmp_path: Path) -> Path:
    return write_sample_media(tmp_path / "Example.Movie.2024.wav")


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
# the typed state a plugin leaves behind
# --------------------------------------------------------------------------
def _plugin_state(media: Path, mi: MediaInfo) -> dict[str, Any]:
    """The shape a season-pack ingest plugin actually stores.

    Keyed by `Path`, holding a `MediaInfo` per episode, a `Track` off that
    object inside an int-keyed audio map, plus enum, set and tuple values --
    none of which plain JSON accepts. Any one of them used to cost the whole
    `dynamic_data` key it sat under, which is how an entire episode map
    disappeared at save time without failing the save.

    The nested `Track` is not decoration: a plugin that maps audio tracks
    stores `source_mediainfo.tracks[n]` against each entry, and it is the value
    most easily left out of a test that hand-rolls this shape.
    """
    return {
        media: {
            "source_file": media.with_suffix(".source.wav"),
            "source_mediainfo": mi,
            "audio_track_map": {
                0: {"source_track_idx": 0, "media_info": mi.tracks[1]},
            },
            "flag": ImageHost.PIXHOST,
            "tags": {"x", "y"},
            "pair": (1, 2),
            "log_file": None,
        }
    }


def test_plugin_state_round_trips_with_its_types_intact(sample_media: Path) -> None:
    source = _new_context()
    _populate(source, sample_media)
    mi = source.media_input.require_mediainfo(sample_media)
    source.shared_data.dynamic_data["episodes"] = _plugin_state(sample_media, mi)

    document = context_to_dict(source)
    json.dumps(document)  # the whole point: this now survives JSON
    restored = _new_context()
    context_from_dict(document, restored)

    episodes = restored.shared_data.dynamic_data["episodes"]
    entry = episodes[sample_media]
    assert list(episodes) == [sample_media]
    assert isinstance(entry["source_file"], Path)
    assert isinstance(entry["source_mediainfo"], MediaInfo)
    assert entry["flag"] is ImageHost.PIXHOST
    assert entry["tags"] == {"x", "y"}
    assert entry["pair"] == (1, 2)
    assert entry["log_file"] is None

    mapped = entry["audio_track_map"][0]
    assert mapped["source_track_idx"] == 0
    # a Track comes back as the restored MediaInfo's own track, not a copy --
    # a detached one would answer questions about a file nothing else agrees on
    assert isinstance(mapped["media_info"], Track)
    assert mapped["media_info"] is entry["source_mediainfo"].tracks[1]
    assert mapped["media_info"].format == mi.tracks[1].format


def test_a_track_from_a_file_the_job_does_not_carry_costs_only_itself(
    tmp_path: Path, sample_media: Path
) -> None:
    """A hand-corrected audio mapping points at a file outside the release.

    `Track` has no reference back to its `MediaInfo`, so there is no dump to
    resolve it from and nothing to look up. Losing that one value is the
    accepted outcome; losing the mapping it sits in is not, which is what
    raising here would have cost.
    """
    outside = MediaInfo.parse(
        write_sample_media(tmp_path / "not-in-this-release.wav"),
        legacy_stream_display=True,
    )
    source = _new_context()
    _populate(source, sample_media)
    source.shared_data.dynamic_data["episodes"] = {
        "map": {0: {"manual": True, "media_info": outside.tracks[1]}}
    }

    restored = _new_context()
    context_from_dict(context_to_dict(source), restored)

    entry = restored.shared_data.dynamic_data["episodes"]["map"][0]
    assert entry["media_info"] is None
    assert entry["manual"] is True


def test_a_plugins_mediainfo_is_restored_from_its_own_stored_dump(
    tmp_path: Path, sample_media: Path
) -> None:
    """The reported failure: a per-episode MediaInfo only a plugin holds.

    It is not in `file_list_mediainfo`, so nothing captured a dump for it and
    the resumed run had nothing to rebuild it from -- which surfaced as the
    plugin failing to read an episode's bit rate.
    """
    job_directory = tmp_path / "jobs" / "job1"
    job_directory.mkdir(parents=True)
    episode_source = write_sample_media(tmp_path / "Episode.source.wav")

    source = _new_context()
    _populate(source, sample_media)
    source.shared_data.dynamic_data["episodes"] = {
        "s01e01": {
            "source_mediainfo": MediaInfo.parse(
                episode_source, legacy_stream_display=True
            )
        }
    }

    assets = capture_mediainfo(job_directory, list(mediainfo_sources(source)))
    document = context_to_dict(source, assets, {})
    sample_media.unlink()
    episode_source.unlink()

    restored = _new_context()
    context_from_dict(
        document, restored, lambda name: read_job_asset(job_directory, name)
    )

    recovered = restored.shared_data.dynamic_data["episodes"]["s01e01"][
        "source_mediainfo"
    ]
    assert isinstance(recovered, MediaInfo)
    assert recovered.general_tracks[0].overall_bit_rate


def test_a_shared_mediainfo_object_is_stored_once_and_shared_again(
    sample_media: Path,
) -> None:
    """A plugin holding the same object the file list holds must not duplicate it.

    Matching by identity is also what survives a rename: `file_list_mediainfo`
    is re-keyed to the new path while the object still names the old one, and
    the map has to win.
    """
    source = _new_context()
    _populate(source, sample_media)
    mi = source.media_input.require_mediainfo(sample_media)
    source.shared_data.dynamic_data["same"] = mi

    assert mediainfo_sources(source) == {sample_media: mi}

    restored = _new_context()
    context_from_dict(context_to_dict(source), restored)

    assert (
        restored.shared_data.dynamic_data["same"]
        is restored.media_input.file_list_mediainfo[sample_media]
    )


def test_a_value_outside_the_whitelist_still_drops_only_its_key(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)
    source.shared_data.dynamic_data["bad"] = {"nested": object()}
    source.shared_data.dynamic_data["good"] = {"nested": Path("keep.mkv")}

    document = context_to_dict(source)

    assert "bad" not in document["shared_data"]["dynamic_data"]
    restored = _new_context()
    context_from_dict(document, restored)
    assert restored.shared_data.dynamic_data["good"] == {"nested": Path("keep.mkv")}


def test_an_enum_this_build_no_longer_knows_degrades_to_none(
    sample_media: Path,
) -> None:
    """A plugin's own enum cannot be in the registry, and must not be fatal."""
    source = _new_context()
    _populate(source, sample_media)
    document = context_to_dict(source)
    document["shared_data"]["dynamic_data"]["gone"] = {
        "__nf__": "enum",
        "cls": "SomePluginEnum",
        "name": "WHATEVER",
    }

    restored = _new_context()
    context_from_dict(document, restored)

    assert restored.shared_data.dynamic_data["gone"] is None
    assert restored.shared_data.release_notes == "notes"


def test_a_key_named_like_an_envelope_does_not_become_one(
    sample_media: Path,
) -> None:
    """Plugin data holding `__nf__` must not be read back as a typed envelope."""
    source = _new_context()
    _populate(source, sample_media)
    source.shared_data.dynamic_data["raw"] = {"__nf__": "not an envelope", "n": 1}

    restored = _new_context()
    context_from_dict(context_to_dict(source), restored)

    assert restored.shared_data.dynamic_data["raw"] == {
        "__nf__": "not an envelope",
        "n": 1,
    }


# --------------------------------------------------------------------------
# rendering without the media
# --------------------------------------------------------------------------
def test_media_info_short_renders_from_a_restored_object(
    source_less_bundle: SourceLessBundle,
) -> None:
    """`{media_info_short}` was the last token still parsing the media file.

    Unlike `{media_info}` it is built from a `MediaInfo` object rather than
    from libmediainfo's text output, so a stored dump alone did not serve it
    and it fell through to `MediaInfo.parse` -- against a file a source-less
    run does not have.
    """
    job = load_job(source_less_bundle.directory)
    restored = _new_context()
    context_from_dict(
        job.context,
        restored,
        lambda name: read_job_asset(source_less_bundle.directory, name),
    )

    assert not source_less_bundle.media.exists()
    rendered = MinimalMediaInfo(source_less_bundle.media).get_minimal_mi_str()

    assert "General" in rendered
    assert "Audio #1" in rendered
    # and the token that already worked must go on working
    assert "General" in MinimalMediaInfo(source_less_bundle.media).get_full_mi_str()


def test_media_info_short_still_parses_when_nothing_was_restored(
    sample_media: Path,
) -> None:
    """A normal run has no cache to read, and must measure the file itself."""
    clear_restored_mediainfo()

    assert "General" in MinimalMediaInfo(sample_media).get_minimal_mi_str()


# --------------------------------------------------------------------------
# keeping an uncertain tracker's prepared work
# --------------------------------------------------------------------------
def _prepared(context: ProcessingContext) -> None:
    for tracker in (TrackerSelection.AITHER, TrackerSelection.HUNO):
        context.shared_data.tracker_release_data[tracker] = {
            "title": f"{tracker.name} title",
            "nfo": f"{tracker.name} nfo",
        }


def test_retained_data_survives_while_the_tracker_stays_unrunnable(
    sample_media: Path,
) -> None:
    """An uncertain tracker keeps everything except the ability to upload again."""
    source = _new_context()
    _populate(source, sample_media)
    _prepared(source)

    filtered = filter_context_document(
        context_to_dict(source),
        set(),
        retain_data_for={TrackerSelection.AITHER},
    )

    shared = filtered["shared_data"]
    assert shared["selected_trackers"] == []
    assert set(shared["tracker_release_data"]) == {TrackerSelection.AITHER.name}
    assert set(shared["tracker_image_hosts"]) == {TrackerSelection.AITHER.name}


def test_retained_data_restores_as_a_job_that_cannot_upload_it(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)
    _prepared(source)

    filtered = filter_context_document(
        context_to_dict(source),
        {TrackerSelection.HUNO},
        retain_data_for={TrackerSelection.AITHER},
    )
    restored = _new_context()
    context_from_dict(filtered, restored)

    assert restored.shared_data.selected_trackers == [TrackerSelection.HUNO]
    assert set(restored.shared_data.tracker_release_data) == {
        TrackerSelection.AITHER,
        TrackerSelection.HUNO,
    }


def test_reselecting_makes_a_retained_tracker_runnable_again(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)
    _prepared(source)
    filtered = filter_context_document(
        context_to_dict(source),
        set(),
        retain_data_for={TrackerSelection.AITHER},
    )

    reselected = reselect_trackers(filtered, [TrackerSelection.AITHER])

    restored = _new_context()
    context_from_dict(reselected, restored)
    assert restored.shared_data.selected_trackers == [TrackerSelection.AITHER]
    assert restored.shared_data.tracker_release_data[TrackerSelection.AITHER][
        "nfo"
    ] == ("AITHER nfo")
    assert restored.shared_data.is_prepared()


def test_reselecting_refuses_a_tracker_with_no_prepared_work(
    sample_media: Path,
) -> None:
    """Without a title and NFO there is nothing to put back, and selecting it
    would produce a "prepared" job that uploads a freshly rendered release
    nobody reviewed."""
    source = _new_context()
    _populate(source, sample_media)
    _prepared(source)
    narrowed = filter_context_document(context_to_dict(source), set())

    reselected = reselect_trackers(narrowed, [TrackerSelection.AITHER])

    assert reselected["shared_data"]["selected_trackers"] == []


def test_reselecting_does_not_duplicate_a_tracker_already_selected(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)
    _prepared(source)
    document = context_to_dict(source)

    reselected = reselect_trackers(document, [TrackerSelection.AITHER])

    assert (
        reselected["shared_data"]["selected_trackers"].count(
            TrackerSelection.AITHER.name
        )
        == 1
    )


def test_reselecting_does_not_mutate_the_original_document(
    sample_media: Path,
) -> None:
    source = _new_context()
    _populate(source, sample_media)
    _prepared(source)
    document = filter_context_document(
        context_to_dict(source), set(), retain_data_for={TrackerSelection.AITHER}
    )

    reselect_trackers(document, [TrackerSelection.AITHER])

    assert document["shared_data"]["selected_trackers"] == []


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


def test_an_unserializable_provider_payload_is_dropped_not_fatal() -> None:
    context = ProcessingContext()
    context.media_search.tmdb_data = {"ok": 1}
    context.media_search.tvdb_data = object()

    document = context_to_dict(context)

    assert document["media_search"]["tmdb_data"] == {"ok": 1}
    assert document["media_search"]["tvdb_data"] is None
    # the whole document must still survive a round trip through JSON
    json.dumps(document)
