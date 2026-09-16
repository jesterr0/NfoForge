"""Coverage for the prompt shown when images do not reach their host.

The dialog is the only place a run can be steered past a partial image
failure, so what its buttons hand back is the whole of its contract.
"""

from src.backend.upload_retry import (
    IMAGE_UPLOAD_ATTEMPTS,
    ImageRetryAction,
    ImageUploadFailure,
)
from src.enums.image_host import ImageHost
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.image_retry_dialog import ImageRetryDialog
from src.packages.custom_types import ImageHostRef

PIXHOST = ImageHostRef(ImageHost.PIXHOST)
LENSDUMP = ImageHostRef(ImageHost.LENSDUMP)
IMGBB = ImageHostRef(ImageHost.IMAGE_BB)


def _failure(timeout: int = 60) -> ImageUploadFailure:
    return ImageUploadFailure(
        host=PIXHOST,
        trackers=(TrackerSelection.AITHER, TrackerSelection.HUNO),
        failed_positions=(3, 6, 11),
        total=12,
        attempt=1,
        automatic_attempts=IMAGE_UPLOAD_ATTEMPTS,
        timeout=timeout,
        message="3 of 12 image uploads failed for Pixhost (positions: 3, 6, 11)",
    )


def test_closing_the_dialog_untouched_cancels_the_run() -> None:
    """An unanswered prompt means cancel everywhere else in the run too."""
    dialog = ImageRetryDialog(_failure(), [LENSDUMP])

    assert dialog.results.action is ImageRetryAction.CANCEL
    assert dialog.results.host is None


def test_retry_alone_carries_no_timeout_override() -> None:
    """A spinbox left where it started is not a decision about the timeout."""
    dialog = ImageRetryDialog(_failure(), [LENSDUMP])

    dialog.retry_btn.click()

    assert dialog.results.action is ImageRetryAction.RETRY
    assert dialog.results.timeout is None


def test_raising_the_timeout_is_carried_with_the_retry() -> None:
    dialog = ImageRetryDialog(_failure(), [LENSDUMP])

    dialog.timeout_spin.setValue(180)
    dialog.retry_btn.click()

    assert dialog.results.action is ImageRetryAction.RETRY
    assert dialog.results.timeout == 180


def test_the_timeout_can_be_raised_past_the_settings_cap() -> None:
    """Settings caps at 120, which is the value that just failed.

    Answering "that timeout was not enough" with "you may not exceed that
    timeout" would make the control useless in the one case it exists for.
    """
    dialog = ImageRetryDialog(_failure(timeout=120), [LENSDUMP])

    dialog.timeout_spin.setValue(600)

    assert dialog.timeout_spin.value() == 600


def test_switching_names_the_host_it_was_pointed_at() -> None:
    dialog = ImageRetryDialog(_failure(), [LENSDUMP, IMGBB])

    dialog.host_combo.setCurrentIndex(1)
    dialog.switch_btn.click()

    assert dialog.results.action is ImageRetryAction.SWITCH_HOST
    assert dialog.results.host == IMGBB


def test_the_failing_host_is_not_offered_as_somewhere_else_to_send_them() -> None:
    dialog = ImageRetryDialog(_failure(), [PIXHOST, LENSDUMP])

    offered = {
        dialog.host_combo.itemData(index) for index in range(dialog.host_combo.count())
    }

    assert offered == {LENSDUMP}


def test_a_single_host_setup_cannot_switch_anywhere() -> None:
    """A dead control says "nowhere to go" more plainly than an empty list."""
    dialog = ImageRetryDialog(_failure(), [PIXHOST])

    assert not dialog.switch_btn.isEnabled()
    assert not dialog.host_combo.isEnabled()

    dialog.switch_btn.click()

    assert dialog.results.action is ImageRetryAction.CANCEL
