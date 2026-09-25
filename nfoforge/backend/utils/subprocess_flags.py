import platform
import subprocess


def get_subprocess_creation_flags(*, new_process_group: bool = False) -> int:
    """Return Windows-only subprocess flags without breaking other platforms.

    The constants are not exposed by :mod:`subprocess` on POSIX.  Keeping the
    lookup here also makes code that is tested with a mocked platform robust:
    a simulated Windows platform must not make a Linux interpreter access a
    missing attribute.
    """
    if platform.system() != "Windows":
        return 0

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if new_process_group:
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return flags
