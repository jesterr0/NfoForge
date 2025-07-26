from pathlib import Path
import re
import shutil
from typing import Tuple, Union

from pymediainfo import MediaInfo

from src.enums.tracker_selection import TrackerSelection
from src.enums.url_type import URLType
from src.exceptions import MediaFrameCountError, URLFormattingError
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import CropValues, ImageUploadData


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
        sync_directory = output_dir / "img_sync"
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


def ffmpeg_crop_to_crop_values(ffmpeg_crop: str, source_width: int, source_height: int):
    """
    Converts an FFmpeg crop string (crop=width:height:x:y) to CropValues (top, bottom, left, right).

    Args:
        ffmpeg_crop (str): FFmpeg crop string in the format 'crop=width:height:x:y'.
        source_width (int): Original video width.
        source_height (int): Original video height.

    Returns:
        tuple: (top, bottom, left, right) crop values for VapourSynth.
    """
    _, params = ffmpeg_crop.split("=")
    cropped_width, cropped_height, x, y = map(int, params.split(":"))

    left = x
    right = source_width - cropped_width - left
    top = y
    bottom = source_height - cropped_height - top

    return CropValues(top=top, bottom=bottom, left=left, right=right)


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


def extract_images_from_str(
    img_str: str,
) -> tuple[list[str], list[str], list[ImageUploadData]]:
    """
    Extracts images from a string in two categories:
    - Full/linked images (tuple of full image URL and optional link URL)
    - Standalone images (just the image URL)

    Returns:
    - A tuple containing:
        - List of tuples [(full_image, link)] for linked images
        - List of standalone image URLs
        - List of ImageUploadData objects
    """
    # extract linked images (HTML format)
    linked_images = re.findall(
        r'<a href="(https?://[^\s"]+\.(?:png|jpg|jpeg)?[^"\s]*)".*?<img src="(https?://[^\s"]+\.(?:png|jpg|jpeg))"',
        img_str,
        re.IGNORECASE | re.DOTALL,
    )

    # extract linked images from BBCode [url=...] containing [img]...[/img]
    linked_images += re.findall(
        r"\[url=(https?://[^\s\[\]]+\.(?:png|jpg|jpeg)?[^\s\[\]]*)\]\s*\[img.*?\](https?://[^\s\[\]]+\.(?:png|jpg|jpeg))\[/img\]\s*\[/url\]",
        img_str,
        re.IGNORECASE,
    )

    # extract standalone BBCode images
    standalone_images = re.findall(
        r"\[img.*?\](https?://[^\s\[\]]+\.(?:png|jpg|jpeg))\[/img\]",
        img_str,
        re.IGNORECASE,
    )

    # extract direct image URLs outside of BBCode or HTML anchor tags
    standalone_images += re.findall(
        r'(?<!href=")(?<!src=")(?<!\[url=)(?<!\[img\])'
        r'(https?://[^\s\[\]<>"]+\.(?:png|jpg|jpeg))',
        img_str,
        re.IGNORECASE,
    )

    # remove duplicates and maintain order for standalone images
    standalone_images = list(dict.fromkeys(standalone_images))

    # load ImageUploadData objects
    img_url_data_objs = []
    for full_img, thumb_img in linked_images:
        img_url_data_objs.append(ImageUploadData(url=full_img, medium_url=thumb_img))

    if not img_url_data_objs:
        for single_img in standalone_images:
            img_url_data_objs.append(ImageUploadData(url=single_img, medium_url=None))

    return linked_images, standalone_images, img_url_data_objs


def format_image_data_to_str(
    tracker: TrackerSelection,
    data: dict[int, ImageUploadData],
    url_type: URLType,
    columns: int,
    column_space: int,
    row_space: int,
    strict: bool = False,
) -> str:
    """
    Formats a dictionary of image upload data into a structured string using BBCode or HTML.

    Args:
        tracker (TrackerSelection): TrackerSelection.
        data (dict[int, ImageUploadData]): Dictionary mapping indices to ImageUploadData objects.
        url_type (URLType): The format type (BBCode or HTML).
        columns (int): Number of images per row.
        column_space (int): Number of spaces between columns.
        row_space (int): Number of newlines between rows.
        strict (bool): Throws an error if no URL data when set to True.

    Returns:
        str: The formatted string containing the images in the requested format.

    Raises:
        AttributeError: If no valid URLs are found.
    """
    urls = []

    for item in data.values():
        if item.url:
            img_url = item.medium_url if item.medium_url else item.url

            # we can force image layouts for trackers if needed here
            if tracker is TrackerSelection.PASS_THE_POPCORN:
                urls.append(f"[img]{img_url}[/img]")
            # default formatting
            else:
                if url_type == URLType.BBCODE:
                    urls.append(f"[url={item.url}][img]{img_url}[/img][/url]")
                elif url_type == URLType.HTML:
                    urls.append(f'<a href="{item.url}"><img src="{img_url}"></a>')

    if not urls:
        if strict:
            raise URLFormattingError("Invalid URL data")
        return ""

    # handle positional formatting
    column_spacing = " " * column_space
    row_spacing = "\n" * (row_space + 1)

    formatted_rows = []
    for i in range(0, len(urls), columns):
        row = column_spacing.join(urls[i : i + columns])
        formatted_rows.append(row)

    formatted_text = row_spacing.join(formatted_rows)
    return formatted_text


def format_image_data_to_comparison(data: dict[int, ImageUploadData]) -> str:
    """
    Formats images in a comparison format.
    ```
    img_source1 img_encode1
    img_source2 img_encode2
    img_source3 img_encode3
    ```

    Args:
        data (dict[int, ImageUploadData]): Dictionary mapping indices to ImageUploadData objects.
    """
    COLUMNS = 2

    urls = []

    for item in data.values():
        if item.url:
            img_url = item.medium_url if item.medium_url else item.url
            urls.append(img_url)

    if not urls:
        return ""

    # handle positional formatting
    column_spacing = " "
    row_spacing = "\n"

    formatted_rows = []
    for i in range(0, len(urls), COLUMNS):
        row = column_spacing.join(urls[i : i + COLUMNS])
        formatted_rows.append(row)

    formatted_text = row_spacing.join(formatted_rows)
    return formatted_text


def get_parity_images(
    data: dict[int, ImageUploadData], even: bool = True
) -> list[ImageUploadData]:
    """
    Return a list of image objects from a dictionary, filtered by even or odd index.

    Args:
        data (dict[int, ImageUploadData]):
            Dictionary of images, where keys are integer indices.
        even (bool, optional):
            If True, select even-indexed images (default). If False, select odd-indexed images.

    Returns:
        list[ImageUploadData]:
            List of ImageUploadData objects.
    """
    parity = 0 if even else 1
    return [item for idx, item in data.items() if idx % 2 == parity]


def get_parity_images_to_str(
    data: dict[int, ImageUploadData], even: bool = True
) -> list[str]:
    """
    Return a list of images strings from a dictionary, filtered by even or odd index.

    Args:
        data (dict[int, ImageUploadData]):
            Dictionary of images, where keys are integer indices.
        even (bool, optional):
            If True, select even-indexed images (default). If False, select odd-indexed images.

    Returns:
        list[str]:
            If True, return a list of image URLs (preferring medium_url if available, else url).
    """
    parity = 0 if even else 1
    return [
        item.medium_url if item.medium_url else item.url
        for idx, item in data.items()
        if idx % 2 == parity and item.url
    ]
