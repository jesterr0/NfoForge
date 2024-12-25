from os import PathLike
from pathlib import Path
from typing import Iterable


def find_largest_file_in_directory(
    directory: PathLike[str], extensions: Iterable, recursive: bool = False
) -> Path:
    largest_file = None
    largest_size = 0

    recursive = "**\*" if recursive else "*"

    for item in Path(directory).glob(recursive):
        if item.is_file():
            if item.suffix in extensions and item.stat().st_size > largest_size:
                largest_size = item.stat().st_size
                largest_file = item

    return largest_file
