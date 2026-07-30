from pathlib import Path
from types import SimpleNamespace

from src.backend.images import FrameForgeImageGeneration
from src.backend.utils.frameforge_index_cache import (
    FrameForgeIndexCache,
    FrameForgeIndexPaths,
)
from src.enums.cropping import Cropping
from src.enums.image_plugin import ImagePlugin
from src.enums.indexer import Indexer
from src.enums.subtitles import SubtitleAlignment


def _media_pair(tmp_path: Path, suffix: str = "") -> tuple[Path, Path]:
    media_dir = tmp_path / "release" / "S01"
    media_dir.mkdir(parents=True, exist_ok=True)
    source = media_dir / f"Source{suffix}.mkv"
    encode = media_dir / f"Episode{suffix}.mkv"
    source.write_bytes(b"source")
    encode.write_bytes(b"encode")
    return source, encode


def _commit_entry(
    cache: FrameForgeIndexCache, source: Path, encode: Path, indexer: Indexer
) -> FrameForgeIndexPaths:
    paths = cache.prepare(source, encode, indexer, cache_source=True)
    assert paths.source_index is not None
    paths.source_index.write_bytes(b"source index")
    paths.encode_index.write_bytes(b"encode index")
    assert cache.mark_success(paths, source, encode, indexer)
    return paths


def test_cache_uses_safe_short_paths_and_indexer_suffixes(tmp_path: Path) -> None:
    source, encode = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path)

    lsmash = cache.prepare(source, encode, Indexer.LSMASH, cache_source=True)
    ffms2 = cache.prepare(source, encode, Indexer.FFMS2, cache_source=True)

    assert lsmash.source_index is not None
    assert ffms2.source_index is not None
    assert lsmash.source_index.suffix == ".lwi"
    assert lsmash.encode_index.suffix == ".lwi"
    assert ffms2.source_index.suffix == ".ffindex"
    assert ffms2.encode_index.suffix == ".ffindex"
    assert lsmash.entry_dir.is_relative_to(tmp_path / "frameforge_indexes")
    assert not lsmash.entry_dir.is_relative_to(source.parent)
    assert len(lsmash.entry_dir.name) <= 80


def test_matching_manifest_reuses_indexes(tmp_path: Path) -> None:
    source, encode = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path)

    first = cache.prepare(source, encode, Indexer.LSMASH)
    assert first.source_index is None
    first.encode_index.write_bytes(b"encode index")
    assert cache.mark_success(first, source, encode, Indexer.LSMASH)

    second = cache.prepare(source, encode, Indexer.LSMASH)

    assert second == first
    assert second.manifest.exists()
    assert second.source_index is None
    assert second.encode_index.read_bytes() == b"encode index"


def test_changed_input_invalidates_cached_indexes(tmp_path: Path) -> None:
    source, encode = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path)
    _commit_entry(cache, source, encode, Indexer.LSMASH)

    encode.write_bytes(b"changed encode")
    refreshed = cache.prepare(source, encode, Indexer.LSMASH, cache_source=True)

    assert refreshed.entry_dir.exists()
    assert not refreshed.manifest.exists()
    assert refreshed.source_index is not None
    assert not refreshed.source_index.exists()
    assert not refreshed.encode_index.exists()


def test_failed_uncommitted_entry_is_removed(tmp_path: Path) -> None:
    source, encode = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path)
    paths = cache.prepare(source, encode, Indexer.LSMASH)
    paths.encode_index.write_bytes(b"partial")

    cache.discard_uncommitted(paths)

    assert not paths.entry_dir.exists()


def test_cache_prunes_old_entries_to_fixed_limit(tmp_path: Path) -> None:
    cache = FrameForgeIndexCache(tmp_path)
    for index in range(cache.MAX_ENTRIES + 1):
        source, encode = _media_pair(tmp_path, suffix=str(index))
        _commit_entry(cache, source, encode, Indexer.LSMASH)

    entries = [entry for entry in cache.cache_root.iterdir() if entry.is_dir()]

    assert len(entries) == cache.MAX_ENTRIES


def test_cache_pruning_keeps_active_entry_when_it_is_old(
    tmp_path: Path, monkeypatch
) -> None:
    cache = FrameForgeIndexCache(tmp_path)
    committed = []
    for index in range(3):
        source, encode = _media_pair(tmp_path, suffix=f"active{index}")
        committed.append(_commit_entry(cache, source, encode, Indexer.LSMASH))

    monkeypatch.setattr(FrameForgeIndexCache, "MAX_ENTRIES", 2)
    cache.prune(active_entry=committed[0].entry_dir)

    entries = [entry for entry in cache.cache_root.iterdir() if entry.is_dir()]

    assert len(entries) == 2
    assert committed[0].entry_dir.exists()


def test_frameforge_command_uses_cache_index_paths(tmp_path: Path, monkeypatch) -> None:
    source, encode = _media_pair(tmp_path)
    output_directory = tmp_path / "images"
    command: list[str] = []
    media_info = SimpleNamespace(
        video_tracks=[SimpleNamespace(other_hdr_format=None, width=1920, height=1080)]
    )

    def fake_run(self, args, _signal):
        command.extend(args)
        encode_index = Path(args[args.index("--encode-index-path") + 1])
        encode_index.write_bytes(b"encode index")
        return 0

    monkeypatch.setattr(FrameForgeImageGeneration, "run_frame_forge_command", fake_run)

    result = FrameForgeImageGeneration().frame_forge_image_generation(
        source_input=source,
        source_file_mi_obj=media_info,  # type: ignore
        media_input=encode,
        media_file_mi_obj=media_info,  # type: ignore
        output_directory=output_directory,
        total_images=12,
        trim=(12, 12),
        subtitle_color="#ffffff",
        subtitle_outline_color="#000000",
        sub_names=None,
        sub_size=24,
        subtitle_alignment=SubtitleAlignment.CENTER_CENTER,
        crop_mode=Cropping.DISABLED,
        crop_values=None,
        advanced_resize=None,
        re_sync=0,
        indexer=Indexer.LSMASH,
        image_plugin=ImagePlugin.FPNG,
        frame_forge_path=tmp_path / "FrameForge.exe",
        ffmpeg_path=None,
        signal=object(),  # type: ignore
        index_cache_root=tmp_path,
    )

    encode_index = Path(command[command.index("--encode-index-path") + 1])
    assert result == 0
    assert "--source-index-path" not in command
    assert encode_index.is_relative_to(tmp_path / "frameforge_indexes")
    assert not list(source.parent.glob("*.lwi"))
    assert not list(source.parent.glob("*.ffindex"))


def test_source_cache_is_seeded_from_existing_sidecar_without_modifying_it(
    tmp_path: Path,
) -> None:
    source, encode = _media_pair(tmp_path)
    source_sidecar = Path(f"{source}.lwi")
    source_sidecar.write_bytes(b"existing source index")
    cache = FrameForgeIndexCache(tmp_path)

    paths = cache.prepare(source, encode, Indexer.LSMASH, cache_source=True)

    assert paths.source_index is not None
    assert paths.source_index.read_bytes() == b"existing source index"
    assert source_sidecar.read_bytes() == b"existing source index"
    assert paths.source_index != source_sidecar


def test_frameforge_command_can_pin_source_index_inside_upload_tree(
    tmp_path: Path, monkeypatch
) -> None:
    source, encode = _media_pair(tmp_path)
    output_directory = tmp_path / "images"
    command: list[str] = []
    media_info = SimpleNamespace(
        video_tracks=[SimpleNamespace(other_hdr_format=None, width=1920, height=1080)]
    )

    def fake_run(self, args, _signal):
        command.extend(args)
        source_index = Path(args[args.index("--source-index-path") + 1])
        encode_index = Path(args[args.index("--encode-index-path") + 1])
        source_index.write_bytes(b"source index")
        encode_index.write_bytes(b"encode index")
        return 0

    monkeypatch.setattr(FrameForgeImageGeneration, "run_frame_forge_command", fake_run)

    result = FrameForgeImageGeneration().frame_forge_image_generation(
        source_input=source,
        source_file_mi_obj=media_info,  # type: ignore
        media_input=encode,
        media_file_mi_obj=media_info,  # type: ignore
        output_directory=output_directory,
        total_images=12,
        trim=(12, 12),
        subtitle_color="#ffffff",
        subtitle_outline_color="#000000",
        sub_names=None,
        sub_size=24,
        subtitle_alignment=SubtitleAlignment.CENTER_CENTER,
        crop_mode=Cropping.DISABLED,
        crop_values=None,
        advanced_resize=None,
        re_sync=0,
        indexer=Indexer.LSMASH,
        image_plugin=ImagePlugin.FPNG,
        frame_forge_path=tmp_path / "FrameForge.exe",
        ffmpeg_path=None,
        signal=object(),  # type: ignore
        index_cache_root=tmp_path,
        cache_source_index=True,
    )

    source_index = Path(command[command.index("--source-index-path") + 1])
    encode_index = Path(command[command.index("--encode-index-path") + 1])
    assert result == 0
    assert source_index.is_relative_to(tmp_path / "frameforge_indexes")
    assert encode_index.is_relative_to(tmp_path / "frameforge_indexes")
