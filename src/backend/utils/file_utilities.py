from datetime import datetime
from os import PathLike, startfile
from pathlib import Path
from platform import system
from subprocess import run
from typing import Iterable


def find_largest_file_in_directory(
    directory: PathLike[str], extensions: Iterable, recursive: bool = False
) -> Path | None:
    largest_file = None
    largest_size = 0

    recurse = r"**\*" if recursive else "*"

    for item in Path(directory).glob(recurse):
        if item.is_file():
            if item.suffix in extensions and item.stat().st_size > largest_size:
                largest_size = item.stat().st_size
                largest_file = item

    return largest_file


def generate_unique_date_name(
    file_name: str, max_len: int = 25, date_format: str = "%m.%d.%Y_%I.%M.%S"
) -> str:
    """Generate unique names based on file name and current date"""
    return f"{file_name[: max_len + 1]}_{datetime.now().strftime(date_format)}"


def open_explorer(path: Path) -> None:
    """Multi platform way to open explorer at X path"""
    cur_platform = system()
    # windows
    if cur_platform == "Windows":
        startfile(str(path))
    # mac
    elif cur_platform == "Darwin":
        run(["open", str(path.as_posix())])
    # Linux and others
    else:
        run(["xdg-open", str(path.as_posix())])
