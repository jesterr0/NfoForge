import shutil
from pathlib import Path
from pymediainfo import MediaInfo
from typing import Tuple, Union
from src.exceptions import MediaFrameCountError
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import CropValues


# def calculate_start_time(total_frames: int, start_percentage: int, fps: float) -> str:
#     start_frame = int(total_frames * start_percentage / 100)
#     start_time_seconds = start_frame / fps

#     hours, remainder = divmod(start_time_seconds, 3600)
#     minutes, seconds = divmod(remainder, 60)

#     return "{:02}:{:02}:{:06.3f}".format(int(hours), int(minutes), seconds)


def determine_ffmpeg_trimmed_frames(
    trim: tuple[int, int], total_frames: int, frame_rate: float
) -> tuple[int, str]:
    # trim start/end
    start_trim = trim[0]
    end_trim = trim[1]
    if start_trim + end_trim > 60:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            "Screenshot video trim levels are greater than 60%, defaulting to 20 for start/end",
        )
        start_trim = end_trim = 30
    start_frame = int(total_frames * (start_trim / 100))
    end_frame = int(total_frames * (1 - (end_trim / 100)))

    # get remaining frames in the middle range
    available_frames = end_frame - start_frame

    # calculate start time
    start_time = str(start_frame / frame_rate)

    return available_frames, start_time


def generate_progress(line: str, total_images: int) -> float | None:
    try:
        get_frame = int(line.split()[0].split("=")[1])
        if get_frame >= 1:
            return (get_frame / total_images) * 100
        return None
    except ValueError:
        return 0


def get_ffmpeg_tone_map_str() -> str:
    return (
        ",zscale=tin=smpte2084:min=bt2020nc:pin=bt2020:rin=tv:t=smpte2084"
        ":m=bt2020nc:p=bt2020:r=tv,zscale=t=linear:npl=100,"
        "format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=2.000:peak=0.000"
        ",zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
    )


def get_total_frames(mi_obj: MediaInfo) -> int:
    total_frames = mi_obj.general_tracks[0].frame_count
    if total_frames:
        return int(total_frames)
    else:
        raise MediaFrameCountError("Failed to determine media file frame count")


def get_frame_rate(mi_obj: MediaInfo) -> float:
    frame_rate = mi_obj.general_tracks[0].frame_rate
    if frame_rate:
        return float(frame_rate)
    return 23.976


def create_directories(
    output_dir: Path, sync_dir: bool = False
) -> Union[Tuple[Path, Path], Tuple[Path, Path, Path]]:
    """
    Creates 2 directories and returns them in a tuple if sync_dir = False
    Creates 3 directories and returns them in a tuple if sync_dir = True

    Args:
        output_dir (Path): Base directory for the desired directories.
        sync_dir (bool, optional): Creates 'sync' direct ory. Defaults to False.

    Returns:
        Union[Tuple[Path, Path], Tuple[Path, Path, Path]]
    """
    img_comparison = output_dir / "img_comparison"
    if img_comparison.exists():
        shutil.rmtree(img_comparison)
    img_comparison.mkdir(parents=True)

    img_selected = output_dir / "img_selected"
    if img_selected.exists():
        shutil.rmtree(img_selected)
    img_selected.mkdir(parents=True)

    if sync_dir:
        sync_directory = output_dir / "sync"
        if sync_directory.exists():
            shutil.rmtree(sync_directory)
        sync_directory.mkdir(parents=True)
        return img_comparison, img_selected, sync_directory

    return img_comparison, img_selected


def compare_res(v1w: int, v1h: int, v2w: int, v2h: int) -> bool:
    """Returns False if video resolutions are not identical by direct pixel count"""
    if v1w != v2w or v1h != v2h:
        return False
    return True


def compare_resolutions(v1_mi_obj: MediaInfo, v2_mi_obj: MediaInfo) -> bool:
    """
    Returns False if video resolutions are not identical by parsing MediaInfo objects.
    """
    v1w = v1_mi_obj.video_tracks[0].width
    v1h = v1_mi_obj.video_tracks[0].height
    v2w = v2_mi_obj.video_tracks[0].width
    v2h = v2_mi_obj.video_tracks[0].height

    return compare_res(v1w, v1h, v2w, v2h)


def vapoursynth_to_ffmpeg_crop(
    vapoursynth_crop: CropValues, source_width: int, source_height: int
) -> str:
    """
    Converts VapourSynth crop to a FFMPEG crop string

    Args:
        vapoursynth_crop (CropValues): CropValues class with top, bottom, left, and right.
        source_width (int): Width of video resolution.
        source_height (int): Height of video resolution.

    Returns:
        str: FFMPEG compliant crop string
    """
    t, b, lf, r = vapoursynth_crop
    cropped_width = source_width - lf - r
    cropped_height = source_height - t - b
    x = lf
    y = t

    return f"crop={cropped_width}:{cropped_height}:{x}:{y}"


def determine_sub_size(height: int, h720: int, h1080: int, h2160: int) -> int | None:
    """
    Takes source height and compares it to pixels returning the first option
    that it falls under.

    Args:
        height (int): Media file video height.
        h720 (int): Configuration for 720.
        h1080 (int): Configuration for 1080.
        h2160 (int): Configuration for 2170.

    Returns:
        int: Correct configuration based on resolution.
    """
    if height <= 720:
        return h720
    elif height <= 1080:
        return h1080
    elif height <= 2160:
        return h2160
