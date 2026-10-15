"""A small, real release for tests that save and restore jobs.

The media is a tiny WAV file, because MediaInfo has to be able to parse it:
saving a job captures MediaInfo for every input file.
"""

from pathlib import Path
import struct
import wave

from pymediainfo import MediaInfo

from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.image_host import ImageHost, ImageSource
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.packages.custom_types import ImageHostRef, ImageUploadFromTo


def write_sample_media(directory: Path) -> Path:
    path = directory / "Example.Movie.2024.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(struct.pack("<" + "h" * 2400, *([0] * 2400)))
    return path


def populate_context(context: ProcessingContext, media: Path) -> None:
    """A movie run for `media`, going to Aither with one screenshot."""
    media_input = context.media_input
    media_input.input_path = media
    media_input.media_type = MediaType.MOVIE
    media_input.working_dir = media.parent / "working"
    media_input.file_list.append(media)
    media_input.file_list_mediainfo[media] = MediaInfo.parse(  # pyright: ignore[reportArgumentType]
        media, legacy_stream_display=True
    )

    context.media_search.media_type = MediaType.MOVIE
    context.media_search.title = "Example"
    context.media_search.year = 2024

    shared = context.shared_data
    shared.selected_trackers = [TrackerSelection.AITHER]
    shared.loaded_images = [media.parent / "img1.png"]
    shared.generated_images = True
    shared.tracker_image_hosts[TrackerSelection.AITHER] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHostRef(ImageHost.CHEVERETO_V3)
    )
