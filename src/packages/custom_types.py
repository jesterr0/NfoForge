from typing import NamedTuple
from src.enums.image_host import ImageHost, ImageSource

SubNames = NamedTuple("SubNames", [("source", str), ("encode", str)])
CropValues = NamedTuple(
    "CropValues", [("top", int), ("bottom", int), ("left", int), ("right", int)]
)
AdvancedResize = NamedTuple(
    "AdvancedResize",
    [
        ("src_left", float),
        ("src_top", float),
        ("src_width", float),
        ("src_height", float),
    ],
)
ImageUploadData = NamedTuple(
    "ImageUploadData", [("url", str | None), ("medium_url", str | None)]
)
ImageUploadFromTo = NamedTuple(
    "ImageUploadFromTo",
    [("img_from", ImageSource), ("img_to", ImageSource | ImageHost)],
)
