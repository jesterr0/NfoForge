from typing import Optional
from pymediainfo import MediaInfo, Track

from src.exceptions import MissingVideoTrackError, ResolutionMappingError
from src.logger.nfo_forge_logger import LOG


class VideoResolutionAnalyzer:
    RESOLUTIONS_WIDTH = (720, 854, 1024, 1280, 1920, 2560, 3840, 7680, 15360)
    RESOLUTIONS_HEIGHT = (480, 540, 576, 720, 1080, 1440, 2160, 4320, 8640)
    RESOLUTION_MAP = {
        (15360, 8640): "8640",
        (7680, 4320): "4320",
        (3840, 2160): "2160",
        (2560, 1440): "1440",
        (1920, 1080): "1080",
        (1920, 720): "1080",
        (1280, 720): "720",
        (1280, 540): "720",
        (1280, 480): "720",
        (1024, 576): "576",
        (1024, 384): "576",
        (960, 540): "540",
        (960, 360): "540",
        (854, 480): "480",
        (854, 320): "480",
        (720, 576): "576",
        (720, 540): "540",
        (720, 480): "480",
        (720, 270): "480",
    }

    def __init__(self, media_info_obj: MediaInfo):
        self.media_info_obj = media_info_obj

    def get_resolution(self) -> str:
        video_track = self._get_video_track()
        width = self._get_width(video_track)
        height = self._get_height(video_track)
        fps = self._get_fps(video_track)
        scan = self._get_scan(video_track)

        scan = "Progressive" if scan is None else scan
        scan = "p" if scan == "Progressive" or (fps and fps == "25.000") else "i"

        width = self._closest(self.RESOLUTIONS_WIDTH, width)
        height = self._closest(self.RESOLUTIONS_HEIGHT, height)
        return f"{self._mi_resolution(width, height)}{scan}"

    @staticmethod
    def _get_width(track: Track) -> int:
        if not track.width or track.width == 0:
            LOG.warning(LOG.LOG_SOURCE.BE, "Failed to determine video width")
            return 0
        return track.width

    @staticmethod
    def _get_height(track: Track) -> int:
        if not track.height or track.height == 0:
            LOG.warning(LOG.LOG_SOURCE.BE, "Failed to determine video height")
            return 0
        return track.height

    @staticmethod
    def _get_fps(track: Track) -> Optional[str]:
        if not track.frame_rate:
            LOG.warning(LOG.LOG_SOURCE.BE, "Failed to determine video frame rate")
        return track.frame_rate

    @staticmethod
    def _get_scan(track: Track) -> Optional[str]:
        if not track.scan_type:
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                "Video file contains no scan type, assuming Progressive",
            )
        return track.scan_type

    def _get_video_track(self) -> Track:
        if self.media_info_obj and self.media_info_obj.video_tracks:
            return self.media_info_obj.video_tracks[0]
        else:
            error = "Input has no video track"
            LOG.critical(LOG.LOG_SOURCE.BE, error)
            raise MissingVideoTrackError(error)

    # @staticmethod
    # def _closest(res_tuple: tuple, key: int) -> int:
    #     for each in res_tuple:
    #         if key <= each:
    #             return each
    #     return 0

    @staticmethod
    def _closest(res_tuple: tuple, key: int) -> int:
        return min((x for x in res_tuple if x >= key), default=0)

    def _mi_resolution(self, width: int, height: int) -> str:
        # Try to find the closest width in the map
        closest_width = self._closest(self.RESOLUTIONS_WIDTH, width)

        # Get the corresponding height for the closest width
        closest_height = self.RESOLUTION_MAP.get((closest_width, height))

        # If the exact height is not found, try to find the next highest available height
        if not closest_height:
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                f"Dimensions {closest_width}x{closest_height} not in resolution map, "
                "automatically detecting the next available height that matches width",
            )
            next_height = sorted(
                h
                for w, h in self.RESOLUTION_MAP.keys()
                if w == closest_width and h > height
            )
            if next_height:
                closest_height = self.RESOLUTION_MAP.get(
                    (closest_width, next_height[0])
                )

        if not closest_height:
            resolution_error_str = f"Cannot find a resolution for {width}x{height}"
            LOG.critical(LOG.LOG_SOURCE.BE, resolution_error_str)
            raise ResolutionMappingError(resolution_error_str)

        LOG.debug(
            LOG.LOG_SOURCE.BE,
            f"Detected approximate video resolution: {closest_width}x{closest_height}",
        )
        return closest_height
