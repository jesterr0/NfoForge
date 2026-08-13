from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.overview_dialog import OverviewDialog

# characters Qt silently rewrites when text is pushed into its editors: a non
# breaking space becomes a plain space and CRLF/CR collapse to "\n". An NFO
# carrying any of them used to come back "changed" from an untouched dialog.
NORMALIZED_NFO = "line one here\r\nline two\rline three"


def test_untouched_dialog_returns_originals_verbatim() -> None:
    """Accepting without editing must not report or apply any change.

    This is the regression test for the process log claiming "Applying user
    edits from overview to trackers X" after the user opened the dialog and
    pressed OK without typing anything.
    """
    original: dict[TrackerSelection, dict[str, str | None]] = {
        TrackerSelection.BEYOND_HD: {"title": "Some Title", "nfo": NORMALIZED_NFO}
    }

    dialog = OverviewDialog(original)
    dialog.accept()

    results = dialog.get_results()
    assert results == original
    assert results[TrackerSelection.BEYOND_HD]["nfo"] == NORMALIZED_NFO


def test_user_edits_are_returned() -> None:
    original: dict[TrackerSelection, dict[str, str | None]] = {
        TrackerSelection.BEYOND_HD: {"title": "Some Title", "nfo": "original nfo"},
        TrackerSelection.TORRENT_LEECH: {"title": "Other Title", "nfo": "untouched"},
    }

    dialog = OverviewDialog(original)
    dialog.nfo_edits[TrackerSelection.BEYOND_HD].setPlainText("edited nfo")
    dialog.title_edits[TrackerSelection.BEYOND_HD].setText("Edited Title")
    dialog.accept()

    results = dialog.get_results()
    assert results[TrackerSelection.BEYOND_HD] == {
        "title": "Edited Title",
        "nfo": "edited nfo",
    }
    # an edit to one tracker must not mark the others as edited
    assert (
        results[TrackerSelection.TORRENT_LEECH]
        == original[TrackerSelection.TORRENT_LEECH]
    )


def test_tracker_without_nfo_is_kept() -> None:
    """A tracker with a title but no NFO template has no NFO editor."""
    original: dict[TrackerSelection, dict[str, str | None]] = {
        TrackerSelection.BEYOND_HD: {"title": "Some Title", "nfo": ""}
    }

    dialog = OverviewDialog(original)
    dialog.accept()

    assert dialog.get_results() == original


def test_tracker_without_title_is_kept() -> None:
    """A tracker with no generated title has no title editor."""
    original: dict[TrackerSelection, dict[str, str | None]] = {
        TrackerSelection.PASS_THE_POPCORN: {"title": None, "nfo": "some nfo"}
    }

    dialog = OverviewDialog(original)
    dialog.accept()

    results = dialog.get_results()
    assert results == original

    dialog_two = OverviewDialog(original)
    dialog_two.nfo_edits[TrackerSelection.PASS_THE_POPCORN].setPlainText("edited")
    dialog_two.accept()
    assert dialog_two.get_results() == {
        TrackerSelection.PASS_THE_POPCORN: {"title": None, "nfo": "edited"}
    }


def test_tracker_with_no_data_is_kept() -> None:
    """A tracker with neither title nor NFO builds no widgets at all."""
    original: dict[TrackerSelection, dict[str, str | None]] = {
        TrackerSelection.BEYOND_HD: {"title": "Some Title", "nfo": "some nfo"},
        TrackerSelection.REELFLIX: {},
    }

    dialog = OverviewDialog(original)
    dialog.accept()

    assert dialog.get_results() == original


def test_rejected_dialog_discards_edits() -> None:
    original: dict[TrackerSelection, dict[str, str | None]] = {
        TrackerSelection.BEYOND_HD: {"title": "Some Title", "nfo": "original nfo"}
    }

    dialog = OverviewDialog(original)
    dialog.nfo_edits[TrackerSelection.BEYOND_HD].setPlainText("edited nfo")
    dialog.reject()

    assert dialog.get_results() == original


def test_results_are_not_the_original_dicts() -> None:
    """Mutating the results must not write back into the original data."""
    original: dict[TrackerSelection, dict[str, str | None]] = {
        TrackerSelection.BEYOND_HD: {"title": "Some Title", "nfo": "original nfo"}
    }

    dialog = OverviewDialog(original)
    dialog.accept()

    results = dialog.get_results()
    results[TrackerSelection.BEYOND_HD]["nfo"] = "mutated"
    assert original[TrackerSelection.BEYOND_HD]["nfo"] == "original nfo"
