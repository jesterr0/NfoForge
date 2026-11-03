from enum import StrEnum


class AutomationMode(StrEnum):
    """What a run does when it needs a decision nobody has made yet."""

    INTERACTIVE = "interactive"
    """Ask, and wait for the answer."""

    SAFE = "safe"
    """Stop and keep the job, waiting for input, so it can be answered later."""

    UNATTENDED = "unattended"
    """Fail the job. A run never guesses to get past a question."""


class JobState(StrEnum):
    """Where a job is in its life. Recorded in the job file."""

    QUEUED = "queued"
    """Configured and ready to run."""

    RUNNING = "running"

    WAITING_FOR_INPUT = "waiting_for_input"
    """Stopped at a decision; answering it resumes the job where it stopped."""

    FAILED = "failed"

    COMPLETE = "complete"
