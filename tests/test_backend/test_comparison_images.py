from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from src.backend import images as images_module
from src.backend.images import (
    COMPARISON_FONT_PATH,
    ComparisonImageGeneration,
    _build_drawtext_filter,
)
from src.backend.utils import subprocess_flags
from src.backend.utils.working_dir import RUNTIME_DIR
from src.enums.cropping import Cropping


class SignalSpy:
    def __init__(self) -> None:
        self.messages: list[tuple[str, float]] = []

    def emit(self, message: str, progress: float) -> None:
        self.messages.append((message, progress))


def test_drawtext_filter_escapes_filter_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        images_module,
        "COMPARISON_FONT_PATH",
        Path("C:/Program Files/O'Brien/Montserrat-Medium.ttf"),
    )

    result = _build_drawtext_filter(
        text="Director's Cut: 100% \\ Source",
        font_size=21,
        font_color="#f5c70a",
        border_color="#000000",
        x="(w-text_w)/2",
        y="10",
    )

    assert "fontfile='C\\:/Program Files/O'\\''Brien/Montserrat-Medium.ttf'" in result
    assert "text='Director'\\''s Cut\\: 100% \\\\ Source'" in result
    assert "expansion=none" in result
    assert "x=(w-text_w)/2:y=10" in result


def test_drawtext_filter_parses_with_bundled_ffmpeg() -> None:
    ffmpeg = RUNTIME_DIR / "apps" / "ffmpeg" / "ffmpeg.exe"
    if not ffmpeg.is_file():
        pytest.skip("Bundled FFmpeg is not available")

    drawtext_filter = _build_drawtext_filter(
        text="Director's Cut: 100%",
        font_size=21,
        font_color="#f5c70a",
        border_color="#000000",
        x="(w-text_w)/2",
        y="10",
    )
    result = subprocess.run(  # noqa: S603 - list argv, no shell; ffmpeg path is the configured binary
        [
            str(ffmpeg),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:d=0.1",
            "-vf",
            f"crop=320:160:0:0,scale=320:180,{drawtext_filter}",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr


def test_drawtext_validation_reports_missing_font(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generator = ComparisonImageGeneration()
    monkeypatch.setattr(images_module, "COMPARISON_FONT_PATH", tmp_path / "missing.ttf")

    with pytest.raises(FileNotFoundError, match="overlay font is missing"):
        generator._validate_drawtext_support(Path("ffmpeg"))


def test_drawtext_validation_reports_unsupported_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = ComparisonImageGeneration()
    monkeypatch.setattr(generator, "check_draw_text", lambda _path: False)

    with pytest.raises(RuntimeError, match="does not support the drawtext filter"):
        generator._validate_drawtext_support(Path("ffmpeg"))


def test_required_frame_failure_is_actionable_and_fail_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def failed_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess([], 1, "", "invalid filter")

    monkeypatch.setattr(subprocess_flags.platform, "system", lambda: "Windows")
    monkeypatch.setattr(images_module.subprocess, "run", failed_run)

    with pytest.raises(
        RuntimeError,
        match="required sync frame 5042: invalid filter",
    ):
        ComparisonImageGeneration._run_required_frame_command(
            ["ffmpeg"], frame_kind="sync", frame_number=5042
        )

    assert calls == 1


def test_incomplete_main_comparison_skips_sync_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generator = ComparisonImageGeneration()
    media_info = SimpleNamespace(
        video_tracks=[SimpleNamespace(width=1920, height=1080)]
    )
    results = iter((0, 1))
    sync_called = False

    monkeypatch.setattr(
        images_module,
        "create_directories",
        lambda *_args, **_kwargs: (
            tmp_path / "comparison",
            tmp_path / "selected",
            tmp_path / "sync",
        ),
    )
    monkeypatch.setattr(generator, "_validate_drawtext_support", lambda _path: None)
    monkeypatch.setattr(images_module, "get_frame_rate", lambda _mi: 24.0)
    monkeypatch.setattr(
        generator, "generate_comp_frames", lambda **_kwargs: next(results)
    )

    def record_sync(**_kwargs: Any) -> None:
        nonlocal sync_called
        sync_called = True

    monkeypatch.setattr(generator, "generate_sync_frames", record_sync)

    result = generator.comparison_image_generation(
        source_input=tmp_path / "source.mkv",
        source_file_mi_obj=media_info,  # type: ignore[arg-type]
        media_input=tmp_path / "encode.mkv",
        media_file_mi_obj=media_info,  # type: ignore[arg-type]
        output_directory=tmp_path / "images",
        total_images=6,
        trim=(12, 12),
        subtitle_color="#ffffff",
        subtitle_outline_color="#000000",
        sub_names=None,
        sub_size=16,
        crop_mode=Cropping.DISABLED,
        crop_values=None,
        ffmpeg_path=tmp_path / "ffmpeg.exe",
        signal=SignalSpy(),  # type: ignore[arg-type]
    )

    assert result == 1
    assert not sync_called


def test_sync_failure_does_not_emit_false_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generator = ComparisonImageGeneration()
    signal = SignalSpy()
    media_info = SimpleNamespace(video_tracks=[SimpleNamespace()])
    img_sync = tmp_path / "img_sync"
    img_sync.mkdir()

    monkeypatch.setattr(images_module, "get_total_frames", lambda _mi: 1000)
    monkeypatch.setattr(
        images_module,
        "determine_ffmpeg_trimmed_frames",
        lambda **_kwargs: (500, "0"),
    )
    monkeypatch.setattr(images_module.random, "choice", lambda values: values[0])

    def fail_reference(**_kwargs: Any) -> None:
        raise RuntimeError("reference failed")

    monkeypatch.setattr(generator, "_generate_reference_frames", fail_reference)

    with pytest.raises(RuntimeError, match="reference failed"):
        generator.generate_sync_frames(
            source_input=tmp_path / "source.mkv",
            media_input=tmp_path / "encode.mkv",
            media_file_mi_obj=media_info,  # type: ignore[arg-type]
            img_sync=img_sync,
            total_images=6,
            trim=(12, 12),
            random_offset=0,
            frame_rate=24.0,
            subtitle_color="#ffffff",
            subtitle_outline_color="#000000",
            sub_size=16,
            ffmpeg_path=tmp_path / "ffmpeg.exe",
            signal=signal,  # type: ignore[arg-type]
        )

    assert all(
        message != "Sync frame generation completed" for message, _ in signal.messages
    )


def test_required_comparison_font_exists() -> None:
    assert COMPARISON_FONT_PATH.is_file()
