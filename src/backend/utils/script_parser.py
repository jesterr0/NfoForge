import re

from src.packages.custom_types import CropValues, AdvancedResize
from src.payloads.script import ScriptValues
from src.backend.utils.crop_detect import parse_avs_data, parse_vpy_data


class ScriptParser:
    """Parses vpy/avs script files for any data we might need to know"""

    __slots__ = ("script", "data")

    def __init__(self, script: str) -> None:
        self.script = script
        self.data = ScriptValues()
        self.parse_script()

    def get_data(self) -> ScriptValues:
        return self.data

    def parse_script(self) -> None:
        if not self.script.strip():
            return

        for line in self.script.splitlines():
            if line.startswith("#"):
                continue

            if not self.data.crop_values:
                crop = self.parse_crop(line)
                if crop:
                    self.data.crop_values = crop

            if not self.data.advanced_resize:
                advanced_resize = self.parse_adv_resize(line)
                if advanced_resize:
                    self.data.advanced_resize = advanced_resize

            if self.data.all_set():
                break

    @staticmethod
    def parse_crop(data: str) -> CropValues | None:
        crop_data_vpy = re.search(r"core.std.Crop\(clip,\s(.+)\)", data)
        if crop_data_vpy:
            return parse_vpy_data(crop_data_vpy.group(1))

        crop_data_avs = re.search(r"Crop\((.+)\)", data)
        if crop_data_avs:
            return parse_avs_data(crop_data_avs.group(1))
        return None

    @staticmethod
    def parse_adv_resize(data: str) -> AdvancedResize | None:
        src_left = src_top = src_width = src_height = 0

        src_left_search = re.search(r"src_left\s?=(\s?\d*\.*\d*)?", data)
        if src_left_search and src_left_search.group(1):
            src_left = float(src_left_search.group(1))

        src_top_search = re.search(r"src_top\s?=(\s?\d*\.*\d*)?", data)
        if src_top_search and src_top_search.group(1):
            src_top = float(src_top_search.group(1))

        src_width_search = re.search(
            r"src_width\s?=\s?(?P<vpy>\bclip?\.?\bwidth?\s?-?\s?\d*\.*\d*)?\s?-?\s?(?P<avs>\d*\.*\d*)?",
            data,
        )
        if src_width_search:
            src_width_search = src_width_search.groupdict()
            src_width_vpy = src_width_search.get("vpy")
            src_width_avs = src_width_search.get("avs")
            if src_width_vpy:
                extract_w_numbers = re.search(r"\d+", str(src_width_vpy))
                if extract_w_numbers:
                    src_width = float(extract_w_numbers.group())
            elif src_width_avs:
                src_width = float(src_width_avs)

        src_height_search = re.search(
            r"src_height\s?=\s?(?P<vpy>\bclip?\.?\bheight?\s?-?\s?\d*\.*\d*)?\s?-?\s?(?P<avs>\d*\.*\d*)?",
            data,
        )
        if src_height_search:
            src_height_search = src_height_search.groupdict()
            src_height_vpy = src_height_search.get("vpy")
            src_height_avs = src_height_search.get("avs")
            if src_height_vpy:
                extract_h_numbers = re.search(r"\d+", str(src_height_vpy))
                if extract_h_numbers:
                    src_height = float(extract_h_numbers.group())
            elif src_height_avs:
                src_height = float(src_height_avs)

        if all(item == 0 for item in (src_left, src_top, src_width, src_height)):
            return None
        else:
            return AdvancedResize(src_left, src_top, src_width, src_height)
