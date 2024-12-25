from os import getpid
from psutil import (
    Process as PProcess,
    NoSuchProcess as PNoSuchProcess,
    TimeoutExpired as PTimeOutExpired,
)


def kill_child_processes() -> None:
    """Use psutil to properly terminate and kill all child processes"""
    try:
        current_process = PProcess(getpid())
        children = current_process.children(recursive=True)
        if not children:
            return
        for child in children:
            try:
                child.terminate()
                child.wait(timeout=2)
            except PNoSuchProcess:
                continue
            except PTimeOutExpired:
                child.kill()
    except PNoSuchProcess:
        pass
