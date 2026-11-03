"""Working out screenshot generation, and choosing screenshots without a viewer."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from pymediainfo import MediaInfo
import pytest

from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.screenshots.plan import (
    COMPARISON_DIR_NAME,
    SELECTED_DIR_NAME,
    CropSource,
    auto_select_screenshots,
    evenly_spaced,
    generate_screenshots,
    plan_screenshots,
    resolve_crop,
    screenshot_mode,
)
from nfoforge.enums.cropping import Cropping
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.screen_shot_mode import ScreenShotMode
from nfoforge.packages.custom_types import ComparisonPair
from nfoforge.payloads.media_inputs import MediaInputPayload

VPY_WITH_CROP = (
    "clip = core.lsmas.LWLibavSource(source)\n"
    "clip = core.std.Crop(clip, left=0, right=0, top=138, bottom=138)\n"
)


class _Track:
    height = 1080


class _MediaInfo:
    video_tracks = [_Track()]


def _settings(
    tmp_path: Path,
    *,
    mode: ScreenShotMode = ScreenShotMode.BASIC_SS_GEN,
    crop_mode: Cropping = Cropping.DISABLED,
) -> Any:
    return SimpleNamespace(
        screenshots=SimpleNamespace(
            mode=mode,
            crop_mode=crop_mode,
            count=6,
            trim_start=10,
            trim_end=5,
            subtitle_color="#fff",
            subtitle_outline_color="#000",
            subtitle_height_720=10,
            subtitle_height_1080=20,
            subtitle_height_2160=40,
            subtitle_alignment=None,
            comparison_subtitles=True,
            comparison_source_name="Source",
            comparison_encode_name="Encode",
            indexer=None,
            image_plugin=None,
        ),
        dependencies=SimpleNamespace(ffmpeg=tmp_path / "ffmpeg", frame_forge=None),
        general=SimpleNamespace(working_dir=tmp_path / "work-root"),
    )


def _context(
    tmp_path: Path, *, comparison: bool = False, script: Path | None = None
) -> ProcessingContext:
    encode = tmp_path / "Movie.2020.1080p.mkv"
    source = tmp_path / "Movie.2020.remux.mkv"
    encode.touch()
    source.touch()
    mediainfo = cast(MediaInfo, _MediaInfo())
    return ProcessingContext(
        media_input=MediaInputPayload(
            input_path=encode,
            media_type=MediaType.MOVIE,
            working_dir=tmp_path / "working",
            file_list=[encode],
            file_list_mediainfo={encode: mediainfo, source: mediainfo},
            comparison_pair=ComparisonPair(source=source, media=encode, script=script)
            if comparison
            else None,
        )
    )


@pytest.fixture
def different_resolutions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nfoforge.core.screenshots.plan.compare_resolutions", lambda *_: False
    )


# --------------------------------------------------------------------------
# mode and crop
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("configured", "comparison", "expected"),
    [
        (ScreenShotMode.ADV_SS_COMP, False, ScreenShotMode.BASIC_SS_GEN),
        (ScreenShotMode.ADV_SS_COMP, True, ScreenShotMode.ADV_SS_COMP),
        (ScreenShotMode.SIMPLE_SS_COMP, True, ScreenShotMode.SIMPLE_SS_COMP),
        (ScreenShotMode.BASIC_SS_GEN, True, ScreenShotMode.SIMPLE_SS_COMP),
    ],
)
def test_screenshot_mode(
    tmp_path: Path,
    configured: ScreenShotMode,
    comparison: bool,
    expected: ScreenShotMode,
) -> None:
    context = _context(tmp_path, comparison=comparison)

    assert screenshot_mode(context, _settings(tmp_path, mode=configured)) is expected


@pytest.mark.usefixtures("different_resolutions")
def test_a_script_with_crops_is_used_as_is(tmp_path: Path) -> None:
    script = tmp_path / "compare.vpy"
    script.write_text(VPY_WITH_CROP, encoding="utf-8")
    context = _context(tmp_path, comparison=True, script=script)
    settings = _settings(
        tmp_path, mode=ScreenShotMode.ADV_SS_COMP, crop_mode=Cropping.MANUAL
    )

    source, values = resolve_crop(context, settings)

    assert source is CropSource.SCRIPT
    assert values and values.crop_values and values.crop_values.top == 138


@pytest.mark.usefixtures("different_resolutions")
@pytest.mark.parametrize(
    ("crop_mode", "expected"),
    [
        (Cropping.MANUAL, CropSource.MANUAL),
        (Cropping.AUTO, CropSource.NONE),
        (Cropping.DISABLED, CropSource.NONE),
    ],
)
def test_without_a_script_only_manual_mode_asks(
    tmp_path: Path, crop_mode: Cropping, expected: CropSource
) -> None:
    context = _context(tmp_path, comparison=True)
    settings = _settings(tmp_path, mode=ScreenShotMode.ADV_SS_COMP, crop_mode=crop_mode)

    assert resolve_crop(context, settings) == (expected, None)


def test_matching_resolutions_need_no_crop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "nfoforge.core.screenshots.plan.compare_resolutions", lambda *_: True
    )
    context = _context(tmp_path, comparison=True)
    settings = _settings(
        tmp_path, mode=ScreenShotMode.ADV_SS_COMP, crop_mode=Cropping.MANUAL
    )

    assert resolve_crop(context, settings) == (CropSource.NONE, None)


# --------------------------------------------------------------------------
# the plan
# --------------------------------------------------------------------------
def test_a_basic_plan(tmp_path: Path) -> None:
    context = _context(tmp_path)

    plan = plan_screenshots(context, _settings(tmp_path))

    assert plan.mode is ScreenShotMode.BASIC_SS_GEN
    assert not plan.is_comparison
    assert plan.media_file == context.media_input.file_list[0]
    assert plan.source_file is None
    assert plan.sub_names is None
    assert plan.output_directory == tmp_path / "working" / "images"
    assert plan.total_images == 6
    assert plan.trim == (10, 5)
    assert plan.sub_size == 20
    # a single-file input protects the folder it lives in
    assert plan.protected_media_root == tmp_path


def test_a_comparison_plan_carries_both_files_and_labels(tmp_path: Path) -> None:
    context = _context(tmp_path, comparison=True)

    plan = plan_screenshots(
        context, _settings(tmp_path, mode=ScreenShotMode.SIMPLE_SS_COMP), re_sync=3
    )

    pair = context.media_input.comparison_pair
    assert pair is not None
    assert plan.is_comparison
    assert (plan.source_file, plan.media_file) == (pair.source, pair.media)
    assert plan.sub_names and plan.sub_names.source == "Source"
    assert plan.re_sync == 3


def test_planning_without_ffmpeg_fails(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.dependencies.ffmpeg = None

    with pytest.raises(RuntimeError, match="FFmpeg"):
        plan_screenshots(_context(tmp_path), settings)


def test_generation_dispatches_on_mode(tmp_path: Path) -> None:
    calls: list[str] = []
    backend = SimpleNamespace(
        basic_image_generation=lambda *_a, **_k: calls.append("basic") or 0,
        comparison_image_generation=lambda *_a, **_k: calls.append("simple") or 0,
    )
    progress = SimpleNamespace(emit=lambda *_: None)

    basic = plan_screenshots(_context(tmp_path), _settings(tmp_path))
    simple = plan_screenshots(
        _context(tmp_path, comparison=True),
        _settings(tmp_path, mode=ScreenShotMode.SIMPLE_SS_COMP),
    )
    assert generate_screenshots(basic, cast(Any, backend), progress) == 0
    assert generate_screenshots(simple, cast(Any, backend), progress) == 0

    assert calls == ["basic", "simple"]


def test_advanced_generation_without_frameforge_fails(tmp_path: Path) -> None:
    plan = plan_screenshots(
        _context(tmp_path, comparison=True),
        _settings(tmp_path, mode=ScreenShotMode.ADV_SS_COMP),
    )

    with pytest.raises(RuntimeError, match="FrameForge"):
        generate_screenshots(plan, cast(Any, None), SimpleNamespace(emit=print))


# --------------------------------------------------------------------------
# choosing without a viewer
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("total", "count", "expected"),
    [
        (10, 3, [0, 4, 9]),
        (10, 1, [5]),
        (3, 5, [0, 1, 2]),
        (5, 0, []),
        (0, 3, []),
    ],
)
def test_evenly_spaced(total: int, count: int, expected: list[int]) -> None:
    assert evenly_spaced(total, count) == expected


def _generated(directory: Path, names: list[str]) -> None:
    (directory / COMPARISON_DIR_NAME).mkdir(parents=True)
    for name in names:
        (directory / COMPARISON_DIR_NAME / name).touch()


def test_basic_auto_selection_spreads_across_the_release(tmp_path: Path) -> None:
    _generated(tmp_path, [f"{n:02d}_output.png" for n in range(1, 11)])

    chosen = auto_select_screenshots(tmp_path, comparison=False, maximum=3)

    assert [image.name for image in chosen] == [
        "01_output.png",
        "05_output.png",
        "10_output.png",
    ]
    assert all(image.parent == tmp_path / SELECTED_DIR_NAME for image in chosen)
    assert all(image.is_file() for image in chosen)
    assert len(list((tmp_path / COMPARISON_DIR_NAME).iterdir())) == 7


def test_comparison_auto_selection_never_splits_a_pair(tmp_path: Path) -> None:
    names = [
        f"{n:02d}{side}_{kind}.png"
        for n in range(1, 7)
        for side, kind in (("a", "source"), ("b", "encode"))
    ]
    _generated(tmp_path, names)

    # 5 images allowed means 2 whole pairs, not 2 pairs and half of a third
    chosen = auto_select_screenshots(tmp_path, comparison=True, maximum=5)

    assert [image.name for image in chosen] == [
        "01a_source.png",
        "01b_encode.png",
        "06a_source.png",
        "06b_encode.png",
    ]


def test_no_maximum_selects_everything(tmp_path: Path) -> None:
    _generated(tmp_path, ["01_output.png", "02_output.png"])

    chosen = auto_select_screenshots(tmp_path, comparison=False, maximum=0)

    assert len(chosen) == 2
