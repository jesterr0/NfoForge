from pathlib import Path

from src.frontend.custom_widgets.rename_preview_dialog import RenamePreviewDialog


def test_preview_shows_full_paths_when_file_parent_changes(tmp_path: Path) -> None:
    source_directory = tmp_path / "old"
    target_directory = tmp_path / "new"
    source = source_directory / "movie.mkv"
    target = target_directory / "renamed.mkv"

    dialog = RenamePreviewDialog()
    dialog.set_renames({source: target})

    preview = dialog.text_viewer.toPlainText()
    assert str(source) in preview
    assert str(target) in preview
