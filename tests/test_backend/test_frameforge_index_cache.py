import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import pytest

from src.backend.images import FrameForgeImageGeneration
from src.backend.utils import frameforge_index_cache as cache_module
from src.backend.utils.frameforge_index_cache import FrameForgeIndexCache
from src.enums.cropping import Cropping
from src.enums.image_plugin import ImagePlugin
from src.enums.indexer import Indexer
from src.enums.subtitles import SubtitleAlignment


def _media_pair(tmp_path: Path, suffix: str = "") -> tuple[Path, Path, Path]:
    source_dir = tmp_path / "source"
    release_dir = tmp_path / "release"
    source_dir.mkdir(parents=True, exist_ok=True)
    release_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / f"Source{suffix}.mkv"
    encode = release_dir / f"Episode{suffix}.mkv"
    source.write_bytes(b"source")
    encode.write_bytes(b"encode")
    return source, encode, release_dir


def test_prepare_creates_private_placeholder_with_indexer_suffix(
    tmp_path: Path,
) -> None:
    _, encode, release_dir = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path / "work")

    lsmash = cache.prepare(encode, Indexer.LSMASH, release_dir)
    ffms2 = cache.prepare(encode, Indexer.FFMS2, release_dir)

    assert lsmash.path.suffix == ".lwi"
    assert ffms2.path.suffix == ".ffindex"
    assert lsmash.path.is_file()
    assert lsmash.path.stat().st_size == 0
    assert not lsmash.existed_before
    assert lsmash.path.is_relative_to(tmp_path / "work" / "frameforge_indexes")
    assert not lsmash.path.is_relative_to(release_dir)
    assert len(lsmash.path.name) <= 80


def test_populated_index_is_reused_without_manifest(tmp_path: Path) -> None:
    _, encode, release_dir = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path / "work")
    first = cache.prepare(encode, Indexer.LSMASH, release_dir)
    first.path.write_bytes(b"encode index")

    assert cache.mark_success(first)

    second = cache.prepare(encode, Indexer.LSMASH, release_dir)

    assert second.path == first.path
    assert second.existed_before
    assert second.path.read_bytes() == b"encode index"
    assert not list(second.cache_root.glob("manifest.json"))


def test_encode_path_and_indexer_create_distinct_cache_entries(
    tmp_path: Path,
) -> None:
    _, first_encode, release_dir = _media_pair(tmp_path, "1")
    _, second_encode, _ = _media_pair(tmp_path, "2")
    cache = FrameForgeIndexCache(tmp_path / "work")

    first = cache.prepare(first_encode, Indexer.LSMASH, release_dir)
    second = cache.prepare(second_encode, Indexer.LSMASH, release_dir)
    other_indexer = cache.prepare(first_encode, Indexer.FFMS2, release_dir)

    assert len({first.path, second.path, other_indexer.path}) == 3


def test_failed_new_index_is_removed_but_existing_index_is_preserved(
    tmp_path: Path,
) -> None:
    _, encode, release_dir = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path / "work")
    new_index = cache.prepare(encode, Indexer.LSMASH, release_dir)

    cache.discard_failed(new_index)

    assert not new_index.path.exists()

    existing = cache.prepare(encode, Indexer.LSMASH, release_dir)
    existing.path.write_bytes(b"known index")
    existing = cache.prepare(encode, Indexer.LSMASH, release_dir)
    cache.discard_failed(existing)

    assert existing.path.read_bytes() == b"known index"


def test_success_without_populated_index_removes_placeholder(tmp_path: Path) -> None:
    _, encode, release_dir = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path / "work")
    prepared = cache.prepare(encode, Indexer.LSMASH, release_dir)

    assert not cache.mark_success(prepared)
    assert not prepared.path.exists()


def test_cache_prunes_old_entries_to_fixed_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = FrameForgeIndexCache(tmp_path / "work")
    monkeypatch.setattr(FrameForgeIndexCache, "MAX_ENTRIES", 2)
    prepared_paths: list[Path] = []

    for index in range(3):
        _, encode, release_dir = _media_pair(tmp_path, str(index))
        prepared = cache.prepare(encode, Indexer.LSMASH, release_dir)
        prepared.path.write_bytes(f"index {index}".encode())
        assert cache.mark_success(prepared)
        prepared_paths.append(prepared.path)

    indexes = list(cache.cache_root.glob("*.lwi"))

    assert len(indexes) == 2
    assert prepared_paths[-1] in indexes


def test_unsafe_custom_cache_root_falls_back_outside_media_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, encode, release_dir = _media_pair(tmp_path)
    fallback_base = tmp_path / "per_user_data_dir"
    monkeypatch.setattr(
        cache_module.ConfigPaths,
        "default_working_dir",
        staticmethod(lambda ensure_exists=False: fallback_base),
    )
    cache = FrameForgeIndexCache(release_dir / "nfoforge_work")

    prepared = cache.prepare(encode, Indexer.LSMASH, release_dir)

    assert prepared.path.is_relative_to(fallback_base / "frameforge_indexes")
    assert not prepared.path.is_relative_to(release_dir)


def test_frameforge_command_uses_existing_private_encode_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, encode, release_dir = _media_pair(tmp_path)
    output_directory = tmp_path / "images"
    command: list[str] = []
    media_info = SimpleNamespace(
        video_tracks=[SimpleNamespace(other_hdr_format=None, width=1920, height=1080)]
    )

    def fake_run(self, args, _signal):
        command.extend(args)
        encode_index = Path(args[args.index("--encode-index-path") + 1])
        assert encode_index.is_file()
        assert encode_index.stat().st_size == 0
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
        index_cache_root=tmp_path / "work",
        protected_media_root=release_dir,
    )

    encode_index = Path(command[command.index("--encode-index-path") + 1])
    assert result == 0
    assert "--source-index-path" not in command
    assert encode_index.is_relative_to(tmp_path / "work" / "frameforge_indexes")
    assert not list(release_dir.glob("*.lwi"))
    assert not list(release_dir.glob("*.ffindex"))


def test_a_rewritten_encode_is_not_served_a_stale_index(tmp_path: Path) -> None:
    _, encode, release_dir = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path / "work")
    first = cache.prepare(encode, Indexer.LSMASH, release_dir)
    first.path.write_bytes(b"encode index")
    assert cache.mark_success(first)

    # Rewrite the encode and force its mtime unambiguously newer than the
    # index. Setting it explicitly rather than relying on wall-clock ordering
    # keeps this off filesystems with coarse timestamp resolution.
    encode.write_bytes(b"changed encode")
    index_mtime = first.path.stat().st_mtime_ns
    newer = index_mtime + 1_000_000_000
    os.utime(encode, ns=(newer, newer))

    second = cache.prepare(encode, Indexer.LSMASH, release_dir)

    assert second.existed_before is False


def test_an_untouched_encode_still_reuses_its_index(tmp_path: Path) -> None:
    # The staleness check must not defeat caching in the normal case.
    _, encode, release_dir = _media_pair(tmp_path)
    cache = FrameForgeIndexCache(tmp_path / "work")
    first = cache.prepare(encode, Indexer.LSMASH, release_dir)
    first.path.write_bytes(b"encode index")
    assert cache.mark_success(first)

    second = cache.prepare(encode, Indexer.LSMASH, release_dir)

    assert second.existed_before is True
    assert second.path.read_bytes() == b"encode index"


def test_prune_refuses_to_delete_through_a_symlink(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_bytes(b"do not delete")

    cache_root = tmp_path / "work" / "frameforge_indexes"
    cache_root.mkdir(parents=True)
    link = cache_root / "legacy-looking-entry"
    try:
        link.symlink_to(victim, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")

    FrameForgeIndexCache(tmp_path / "work").prune(cache_root)

    assert (victim / "precious.txt").exists()


def test_fallback_cache_root_is_not_in_shared_temp(tmp_path: Path) -> None:
    # The configured root sits inside the media tree, so the fallback fires.
    media_root = tmp_path / "media"
    media_root.mkdir()
    cache = FrameForgeIndexCache(media_root / "work")

    fallback = cache._safe_cache_root(media_root)

    assert tempfile.gettempdir() not in str(fallback)
    assert not fallback.is_relative_to(media_root)
