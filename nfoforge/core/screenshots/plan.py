"""Everything screenshot generation needs, worked out from the run and settings.

The desktop Images page used to assemble these arguments across several
methods and hand them to a worker thread. Here they are one `ScreenshotPlan`,
which the page and a headless run both build and pass to
`generate_screenshots`. What stays with the caller is the interaction: the
page shows a crop dialog and an image viewer, a headless run uses
`auto_select_screenshots`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
import re
from typing import TYPE_CHECKING

from pymediainfo import MediaInfo

from nfoforge.backend.images import ImagesBackEnd
from nfoforge.backend.utils.images import compare_resolutions, determine_sub_size
from nfoforge.backend.utils.script_parser import ScriptParser
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.signals import ProgressSignal
from nfoforge.enums.cropping import Cropping
from nfoforge.enums.image_plugin import ImagePlugin
from nfoforge.enums.indexer import Indexer
from nfoforge.enums.screen_shot_mode import ScreenShotMode
from nfoforge.enums.subtitles import SubtitleAlignment
from nfoforge.packages.custom_types import SubNames
from nfoforge.payloads.script import ScriptValues

if TYPE_CHECKING:
    from nfoforge.config.models import AppConfig

COMPARISON_DIR_NAME = "img_comparison"
SELECTED_DIR_NAME = "img_selected"

# `01a_source.png` / `01b_encode.png` (FrameForge may append `__<frame>`):
# the number is what pairs a source frame with its encode frame.
_PAIR_NUMBER = re.compile(r"^(\d+)[ab]_")


class CropSource(Enum):
    """Where the crop for a comparison comes from."""

    NONE = auto()
    """Nothing to crop: same resolutions, no comparison, or cropping disabled."""
    SCRIPT = auto()
    """The comparison script describes the crop."""
    MANUAL = auto()
    """Someone has to enter it; the desktop app shows a crop dialog."""


@dataclass(frozen=True, slots=True)
class ScreenshotPlan:
    """The arguments of one screenshot generation run."""

    mode: ScreenShotMode
    media_file: Path
    media_mediainfo: MediaInfo
    source_file: Path | None
    source_mediainfo: MediaInfo | None
    output_directory: Path
    total_images: int
    trim: tuple[int, int]
    subtitle_color: str
    subtitle_outline_color: str
    sub_names: SubNames | None
    sub_size: int
    subtitle_alignment: SubtitleAlignment
    crop_mode: Cropping
    script_values: ScriptValues | None
    re_sync: int
    indexer: Indexer | None
    image_plugin: ImagePlugin | None
    ffmpeg_path: Path
    frame_forge_path: Path | None
    index_cache_root: Path | None
    protected_media_root: Path

    @property
    def is_comparison(self) -> bool:
        return self.mode is not ScreenShotMode.BASIC_SS_GEN


def screenshot_mode(context: ProcessingContext, settings: AppConfig) -> ScreenShotMode:
    """The mode generation actually runs in.

    Comparison modes need a comparison pair; without one the configured mode
    falls back to basic generation of the input.
    """
    if not context.media_input.comparison_pair:
        return ScreenShotMode.BASIC_SS_GEN
    if settings.screenshots.mode is ScreenShotMode.ADV_SS_COMP:
        return ScreenShotMode.ADV_SS_COMP
    return ScreenShotMode.SIMPLE_SS_COMP


def resolve_crop(
    context: ProcessingContext, settings: AppConfig
) -> tuple[CropSource, ScriptValues | None]:
    """Where a comparison's crop comes from, with the script's values if any.

    Only a comparison whose source and encode differ in resolution needs one.
    A comparison script is the source of truth for cropping, so when it carries
    usable values they are applied directly rather than asking for crops it
    already describes. Without that, manual crop mode asks.
    """
    crop_mode = settings.screenshots.crop_mode
    pair = context.media_input.comparison_pair
    if settings.screenshots.mode is ScreenShotMode.BASIC_SS_GEN or not pair:
        return CropSource.NONE, None

    mediainfo = context.media_input.file_list_mediainfo
    if not mediainfo:
        raise AttributeError("Failed to get data from comparison pair")
    if compare_resolutions(mediainfo[pair.source], mediainfo[pair.media]):
        return CropSource.NONE, None

    if crop_mode is not Cropping.DISABLED and pair.script:
        values = ScriptParser(pair.script.read_text(encoding="utf-8")).get_data()
        if not values.all_zeros():
            return CropSource.SCRIPT, values
    if crop_mode is Cropping.MANUAL:
        return CropSource.MANUAL, None
    return CropSource.NONE, None


def plan_screenshots(
    context: ProcessingContext,
    settings: AppConfig,
    *,
    script_values: ScriptValues | None = None,
    re_sync: int = 0,
) -> ScreenshotPlan:
    """Work out one generation run.

    Raises `FileNotFoundError`/`RuntimeError` when the media, the working
    directory or FFmpeg is missing, and `KeyError` when MediaInfo is missing
    for a file.
    """
    media_input = context.media_input
    media_input.require_existing_media_paths(include_comparison=True)
    if not media_input.file_list or not media_input.file_list_mediainfo:
        raise RuntimeError("No files detected in file_list or file_list_mediainfo")
    if not media_input.working_dir:
        raise FileNotFoundError(
            "Failed to locate path to 'working directory for media'"
        )
    ffmpeg = settings.dependencies.ffmpeg
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to generate screenshots")

    shots = settings.screenshots
    mediainfo = media_input.file_list_mediainfo
    pair = media_input.comparison_pair
    if pair:
        media_file, source_file = pair.media, pair.source
        source_mediainfo: MediaInfo | None = mediainfo[source_file]
        sub_names = (
            SubNames(shots.comparison_source_name, shots.comparison_encode_name)
            if shots.comparison_subtitles
            else None
        )
    else:
        media_file, source_file = media_input.file_list[0], None
        source_mediainfo = None
        sub_names = None
    media_mediainfo = mediainfo[media_file]

    input_path = media_input.require_input_path()
    return ScreenshotPlan(
        mode=screenshot_mode(context, settings),
        media_file=media_file,
        media_mediainfo=media_mediainfo,
        source_file=source_file,
        source_mediainfo=source_mediainfo,
        output_directory=media_input.working_dir / "images",
        total_images=shots.count,
        trim=(shots.trim_start, shots.trim_end),
        subtitle_color=shots.subtitle_color,
        subtitle_outline_color=shots.subtitle_outline_color,
        sub_names=sub_names,
        sub_size=determine_sub_size(
            media_mediainfo.video_tracks[0].height,
            shots.subtitle_height_720,
            shots.subtitle_height_1080,
            shots.subtitle_height_2160,
        ),
        subtitle_alignment=shots.subtitle_alignment,
        crop_mode=shots.crop_mode,
        script_values=script_values,
        re_sync=re_sync,
        indexer=shots.indexer,
        image_plugin=shots.image_plugin,
        ffmpeg_path=ffmpeg,
        frame_forge_path=settings.dependencies.frame_forge,
        index_cache_root=settings.general.working_dir,
        # the upload tree must stay free of FrameForge's private encode index
        protected_media_root=input_path if input_path.is_dir() else input_path.parent,
    )


def generate_screenshots(
    plan: ScreenshotPlan, backend: ImagesBackEnd, progress: ProgressSignal
) -> int:
    """Run the generation `plan` describes. Returns the backend's exit code."""
    crop_values = plan.script_values.crop_values if plan.script_values else None
    if plan.mode is ScreenShotMode.BASIC_SS_GEN:
        return backend.basic_image_generation(
            plan.media_file,
            plan.output_directory,
            plan.media_mediainfo,
            plan.total_images,
            plan.trim,
            plan.ffmpeg_path,
            progress,
        )

    if not plan.source_file or not plan.source_mediainfo:
        raise RuntimeError("A comparison needs a source file and its MediaInfo")
    if plan.mode is ScreenShotMode.SIMPLE_SS_COMP:
        return backend.comparison_image_generation(
            plan.source_file,
            plan.source_mediainfo,
            plan.media_file,
            plan.media_mediainfo,
            plan.output_directory,
            plan.total_images,
            plan.trim,
            plan.subtitle_color,
            plan.subtitle_outline_color,
            plan.sub_names,
            plan.sub_size,
            plan.crop_mode,
            crop_values,
            plan.ffmpeg_path,
            progress,
            plan.re_sync,
        )

    if not plan.indexer or not plan.image_plugin or not plan.frame_forge_path:
        raise RuntimeError(
            "An advanced comparison needs FrameForge, an indexer and an image plugin"
        )
    return backend.frame_forge_image_generation(
        plan.source_file,
        plan.source_mediainfo,
        plan.media_file,
        plan.media_mediainfo,
        plan.output_directory,
        plan.total_images,
        plan.trim,
        plan.subtitle_color,
        plan.subtitle_outline_color,
        plan.sub_names,
        plan.sub_size,
        plan.subtitle_alignment,
        plan.crop_mode,
        crop_values,
        plan.script_values.advanced_resize if plan.script_values else None,
        plan.re_sync,
        plan.indexer,
        plan.image_plugin,
        plan.frame_forge_path,
        plan.ffmpeg_path,
        progress,
        index_cache_root=plan.index_cache_root,
        protected_media_root=plan.protected_media_root,
    )


def auto_select_screenshots(
    output_directory: Path, *, comparison: bool, maximum: int
) -> list[Path]:
    """Choose screenshots without a viewer, the way a person picking would.

    Takes evenly spaced frames across the release, up to `maximum` images (0
    means no limit), and moves them into the selected folder exactly as the
    desktop viewer does. A comparison's source and encode frames count as two
    images and are always taken together, never split.

    Returns the selected images, sorted.
    """
    candidates = sorted((output_directory / COMPARISON_DIR_NAME).glob("*.png"))
    selected_dir = output_directory / SELECTED_DIR_NAME
    selected_dir.mkdir(parents=True, exist_ok=True)

    groups: list[list[Path]]
    if comparison:
        by_number: dict[int, list[Path]] = {}
        for image in candidates:
            match = _PAIR_NUMBER.match(image.name)
            if match:
                by_number.setdefault(int(match.group(1)), []).append(image)
        groups = [sorted(by_number[number]) for number in sorted(by_number)]
    else:
        groups = [[image] for image in candidates]

    size = 2 if comparison else 1
    wanted = len(groups) if maximum <= 0 else min(len(groups), maximum // size)

    selected: list[Path] = []
    for index in evenly_spaced(len(groups), wanted):
        for image in groups[index]:
            target = selected_dir / image.name
            image.rename(target)
            selected.append(target)
    return sorted(selected)


def evenly_spaced(total: int, count: int) -> list[int]:
    """`count` indices spread across `range(total)`, first and last included."""
    if count <= 0 or total <= 0:
        return []
    if count >= total:
        return list(range(total))
    if count == 1:
        return [total // 2]
    return [round(i * (total - 1) / (count - 1)) for i in range(count)]
