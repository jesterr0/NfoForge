"""Screenshots of a disc are spread over its feature, clip by clip."""

from dataclasses import replace
from pathlib import Path
import random
from typing import Any

from pymediainfo import MediaInfo
import pytest

from nfoforge.core.disc import (
    Disc,
    FrameTarget,
    choose_playlist,
    detect_disc,
    disc_frame_targets,
)
from nfoforge.core.screenshots.plan import ScreenshotPlan, generate_screenshots
from nfoforge.enums.cropping import Cropping
from nfoforge.enums.screen_shot_mode import ScreenShotMode
from nfoforge.enums.subtitles import SubtitleAlignment
from tests.disc_helpers import make_bluray, make_dvd


def _bluray(root: Path) -> Disc:
    # one playlist over three clips: 600s, 1200s, 1800s
    make_bluray(
        root,
        {"00800": [("00001", 0, 600), ("00002", 0, 1200), ("00003", 0, 1800)]},
        {"00001": 100, "00002": 200, "00003": 300},
    )
    disc = detect_disc(root)
    assert disc is not None
    choose_playlist(disc)
    return disc


def test_shots_are_spread_over_every_clip_of_a_bluray(tmp_path: Path) -> None:
    disc = _bluray(tmp_path / "disc")
    stream = disc.root / "BDMV" / "STREAM"

    # no trim and no jitter: shots at 0, 1200, 2400 and 3600 seconds in
    targets = disc_frame_targets(disc, 4, (0, 0), rng=_no_jitter())

    assert targets == [
        FrameTarget(stream / "00001.m2ts", 0.0),
        FrameTarget(stream / "00002.m2ts", 600.0),
        FrameTarget(stream / "00003.m2ts", 600.0),
        # the very end is pulled back off the clip's last keyframe
        FrameTarget(stream / "00003.m2ts", 1798.0),
    ]


def test_trim_keeps_shots_off_the_start_and_end(tmp_path: Path) -> None:
    disc = _bluray(tmp_path / "disc")
    targets = disc_frame_targets(disc, 2, (10, 10), rng=_no_jitter())
    # 10% of 3600s is 360s in; 90% is 3240s, i.e. 1440s into the last clip
    assert [(t.path.name.lower(), t.seconds) for t in targets] == [
        ("00001.m2ts", 360.0),
        ("00003.m2ts", 1440.0),
    ]


def test_dvd_runtime_is_shared_out_over_its_vobs_by_size(tmp_path: Path) -> None:
    disc = detect_disc(make_dvd(tmp_path / "dvd", {"01": [5, 100, 300]}, ifos=False))
    assert disc is not None
    choose_playlist(disc)

    # no IFO runtime, so the caller's is used; the menu VOB plays no part
    targets = disc_frame_targets(disc, 3, (0, 0), feature_seconds=400, rng=_no_jitter())

    assert [(t.path.name.lower(), t.seconds) for t in targets] == [
        ("vts_01_1.vob", 0.0),
        ("vts_01_2.vob", 100.0),
        ("vts_01_2.vob", 298.0),
    ]
    with pytest.raises(ValueError, match="length of the feature"):
        disc_frame_targets(disc, 3, (0, 0))


def _no_jitter() -> random.Random:
    rng = random.Random()  # noqa: S311 - no randomness is used
    rng.uniform = lambda _a, _b: 0.0  # type: ignore[method-assign]
    return rng


def _mediainfo(video: str = "<Format>AVC</Format>") -> MediaInfo:
    return MediaInfo(
        f"""<Mediainfo><File>
        <track type="General"><Duration>3600000</Duration></track>
        <track type="Video">{video}<Width>1920</Width><Height>1080</Height></track>
        </File></Mediainfo>"""
    )


def _plan(disc: Disc, mediainfo: MediaInfo, tmp_path: Path) -> ScreenshotPlan:
    primary = disc.primary_media_file()
    assert primary is not None
    return ScreenshotPlan(
        mode=ScreenShotMode.BASIC_SS_GEN,
        media_file=primary,
        media_mediainfo=mediainfo,
        source_file=None,
        source_mediainfo=None,
        output_directory=tmp_path / "images",
        total_images=3,
        trim=(10, 10),
        subtitle_color="",
        subtitle_outline_color="",
        sub_names=None,
        sub_size=0,
        subtitle_alignment=next(iter(SubtitleAlignment)),
        crop_mode=Cropping.DISABLED,
        script_values=None,
        re_sync=0,
        indexer=None,
        image_plugin=None,
        ffmpeg_path=Path("ffmpeg"),
        frame_forge_path=None,
        index_cache_root=None,
        protected_media_root=disc.root,
        disc=disc,
    )


class _Backend:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def disc_image_generation(self, targets: Any, *args: Any, **kwargs: Any) -> int:
        self.calls.append({"targets": targets, **kwargs})
        return 0


class _Progress:
    def emit(self, *_args: Any) -> None:
        pass


@pytest.mark.parametrize(
    ("video", "keyframe_only"),
    [
        ("<Format>AVC</Format>", False),
        ("<Format>VC-1</Format>", True),
        (
            "<Format>HEVC</Format><HDR_Format>SMPTE ST 2086</HDR_Format>"
            "<HDR_Format>SMPTE ST 2086, HDR10 compatible</HDR_Format>",
            True,
        ),
    ],
)
def test_a_disc_plan_shoots_the_feature_whatever_mode_is_set(
    tmp_path: Path, video: str, keyframe_only: bool
) -> None:
    disc = _bluray(tmp_path / "disc")
    backend = _Backend()
    plan = _plan(disc, _mediainfo(video), tmp_path)
    # an advanced comparison configured in the profile cannot apply to a disc
    plan = replace(plan, mode=ScreenShotMode.ADV_SS_COMP)

    assert generate_screenshots(plan, backend, _Progress()) == 0  # type: ignore[arg-type]

    (call,) = backend.calls
    assert len(call["targets"]) == 3
    assert {path.name.lower() for path, _ in call["targets"]} >= {
        "00001.m2ts",
        "00003.m2ts",
    }
    assert call["keyframe_only"] is keyframe_only
    assert call["square_pixels"] is False


def test_a_dvd_is_stretched_to_square_pixels(tmp_path: Path) -> None:
    disc = detect_disc(make_dvd(tmp_path / "dvd", {"01": [5, 100, 300]}, ifos=False))
    assert disc is not None
    choose_playlist(disc)
    backend = _Backend()

    generate_screenshots(_plan(disc, _mediainfo(), tmp_path), backend, _Progress())  # type: ignore[arg-type]

    assert backend.calls[0]["square_pixels"] is True


def test_frames_are_taken_from_each_clip_with_the_disc_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nfoforge.backend import images

    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> Any:
        commands.append(command)
        assert "creationflags" in kwargs
        return type("Done", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(images.subprocess, "run", run)
    clips = [tmp_path / "00001.m2ts", tmp_path / "00002.m2ts"]

    result = images.ImagesBackEnd.disc_image_generation(
        [(clips[0], 61.5), (clips[1], 3725.25)],
        tmp_path / "images",
        _mediainfo(),
        Path("ffmpeg"),
        _Progress(),  # type: ignore[arg-type]
        keyframe_only=True,
        square_pixels=True,
    )

    assert result == 0
    first, second = commands
    assert first[1:5] == ["-noaccurate_seek", "-ss", "00:01:01.500", "-i"]
    assert first[5] == str(clips[0])
    assert second[3:6] == ["01:02:05.250", "-i", str(clips[1])]
    assert first[first.index("-vf") + 1] == "scale=trunc(iw*sar/2)*2:ih,setsar=1"
    assert Path(first[first.index("-y") + 1]).name == "01_output.png"
    assert Path(second[second.index("-y") + 1]).name == "02_output.png"
