from collections import Counter
from os import PathLike
from pathlib import Path
import platform
import re
import subprocess


class CropDetect:
    """Utilizes FFMPEG cropdetect filter to detect the crop needed from a source file"""

    def __init__(
        self, ffmpeg: Path, file_input: PathLike[str], segments: int, frames: int
    ) -> None:
        self.ffmpeg = Path(ffmpeg)
        self.file_input = Path(file_input)
        self.segments = segments
        self.frames = frames
        self.result = self._detect_crop()

    def _detect_crop(self) -> str | None:
        crop_segments = self._detect_crop_in_segments()
        largest_common_crop = self._get_largest_common_crop_params(crop_segments)
        crop = self._convert_raw_to_crop_params(largest_common_crop)
        return crop

    def _detect_crop_in_segments(self) -> list:
        crop_params_list = self._run_crop_detect(
            self.file_input, self.segments * self.frames
        )
        return crop_params_list

    def _run_crop_detect(self, input_video, num_frames) -> list[str]:
        command = (
            str(self.ffmpeg),
            "-i",
            input_video,
            "-vf",
            f"select='not(mod(n,{num_frames}))',cropdetect=round=2",
            "-frames:v",
            str(num_frames),
            "-f",
            "null",
            "-",
            "-hide_banner",
        )

        result = subprocess.run(
            command,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
            if platform.system() == "Windows"
            else 0,
        )
        output = result.stderr

        return re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", output)

    def get_result(self) -> str | None:
        return self.result

    def _convert_raw_to_crop_params(self, raw_crop: str | None) -> str | None:
        if not raw_crop:
            return
        width, height, x, y = map(int, raw_crop)
        # ensure even values for video encoding compatibility
        width = self._round_up_to_even(width)
        height = self._round_up_to_even(height)
        x = self._round_up_to_even(x)
        y = self._round_up_to_even(y)
        return f"crop={width}:{height}:{x}:{y}"

    @staticmethod
    def _get_largest_common_crop_params(crop_params_list: list) -> str | None:
        # count the occurrences of each crop parameter set
        counter = Counter(crop_params_list)

        # get the most common crops (sorted by frequency)
        most_common_crops = counter.most_common()

        # track the largest common crop
        largest_common_crop = None

        for crop, freq in most_common_crops:
            # if no largest crop has been selected yet or if the current crop is larger
            if largest_common_crop is None:
                largest_common_crop = crop
            else:
                # compare the sizes of the crops (width and height) and choose the largest
                current_width, current_height, _current_x, _current_y = map(
                    int, largest_common_crop
                )
                new_width, new_height, _new_x, _new_y = map(int, crop)

                # if the current crop has a larger area, replace the largest_common_crop
                if (new_width * new_height) > (current_width * current_height):
                    largest_common_crop = crop

        return largest_common_crop

    @staticmethod
    def _round_up_to_even(value: int) -> int:
        return value if value % 2 == 0 else value + 1
