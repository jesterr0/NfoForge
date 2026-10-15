"""What `nfoforge` exits with, so scripts can tell the outcomes apart."""

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    """Everything asked for was done."""

    FAILED = 1
    """Something went wrong. The run may have got partway."""

    USAGE = 2
    """The command line itself was wrong (argparse's own code)."""

    REFUSED = 3
    """The run stopped at a question nobody answered, having published nothing.
    Running it again stops in the same place; the message names the option
    that answers it."""

    WAITING = 4
    """Safe mode: the run was saved as a job waiting for input. Answer it with
    `nfoforge jobs answer`."""

    PARTIAL = 5
    """The run finished, but at least one tracker did not upload."""
