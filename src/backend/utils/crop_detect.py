import re

from src.packages.custom_types import CropValues


def parse_scripts(script: str) -> CropValues:
    text_data = script.splitlines()
    if text_data:
        for data in text_data:
            if data.startswith("#"):
                continue

            crop_data_vpy = re.search(r"core.std.Crop\(clip,\s(.+)\)", data)
            if crop_data_vpy:
                return parse_vpy_data(crop_data_vpy.group(1))

            crop_data_avs = re.search(r"Crop\((.+)\)", data)
            if crop_data_avs:
                return parse_avs_data(crop_data_avs.group(1))

    return CropValues(0, 0, 0, 0)


def parse_vpy_data(crop_str: str) -> CropValues:
    left = 0
    right = 0
    top = 0
    bottom = 0

    if crop_str:
        if all(x in crop_str for x in ("top", "bottom", "left", "right")):
            get_left_crop = re.search(r"left\s?=\s?(\d+)?", crop_str)
            left = int(get_left_crop.group(1)) if get_left_crop else 0
            get_right_crop = re.search(r"right\s?=\s?(\d+)?", crop_str)
            right = int(get_right_crop.group(1)) if get_right_crop else 0
            get_top_crop = re.search(r"top\s?=\s?(\d+)?", crop_str)
            top = int(get_top_crop.group(1)) if get_top_crop else 0
            get_bottom_crop = re.search(r"bottom\s?=\s?(\d+)?", crop_str)
            bottom = int(get_bottom_crop.group(1)) if get_bottom_crop else 0
        else:
            split_data = crop_str.split(",")
            left = abs(int(split_data[0].strip()))
            right = abs(int(split_data[1].strip()))
            top = abs(int(split_data[2].strip()))
            bottom = abs(int(split_data[3].strip()))

    return CropValues(top, bottom, left, right)


def parse_avs_data(crop_str: str) -> CropValues:
    left = 0
    right = 0
    top = 0
    bottom = 0

    if crop_str:
        split_data = crop_str.split(",")
        left = abs(int(split_data[0].strip()))
        right = abs(int(split_data[2].strip()))
        top = abs(int(split_data[1].strip()))
        bottom = abs(int(split_data[3].strip()))

    return CropValues(top, bottom, left, right)
