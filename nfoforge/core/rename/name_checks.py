"""Plugins' rules for a release's name, applied as the rename is confirmed.

The wizard's Rename page and the command line's rename stage both come
through here, with the names final and nothing on disk moved yet, so a rule
that blocks leaves the files as they were.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from nfoforge.plugins.api import ReleaseNameCheckRequest
from nfoforge.plugins.manager import PluginReleaseNameIssue

if TYPE_CHECKING:
    from nfoforge.config.config import ConfigManager
    from nfoforge.context.processing_context import ProcessingContext
    from nfoforge.core.rename.series import SeriesRenameTargets
    from nfoforge.payloads.media_inputs import MediaInputPayload


def release_name_issues(
    config: ConfigManager, context: ProcessingContext, names: Iterable[str]
) -> list[PluginReleaseNameIssue]:
    """Every enabled plugin's objections to `names`; none with plugins off."""
    checked = tuple(dict.fromkeys(name for name in names if name))
    if not config.settings.general.enable_plugins or not checked:
        return []
    return config.plugin_manager.run_release_name_checks(
        ReleaseNameCheckRequest(config=config, context=context, names=checked)
    )


def series_release_names(
    media_input: MediaInputPayload, targets: SeriesRenameTargets
) -> tuple[str, ...]:
    """A pack's names once renamed: its folders, then each episode.

    `targets` leaves out what does not move, and those names go out too: an
    episode already called `...PROPER...` is as much the release's name as
    one about to be.
    """
    names: list[str] = []
    input_path = media_input.input_path
    if input_path is not None and input_path.is_dir():
        names.append(targets.directories.get(input_path, input_path).name)
    names.extend(target.name for target in targets.directories.values())
    for media_file in media_input.file_list:
        path = Path(media_file)
        names.append(targets.files.get(path, path).stem)
    return tuple(dict.fromkeys(names))


def blocking_issues(issues: Sequence[PluginReleaseNameIssue]) -> list[str]:
    return [str(issue) for issue in issues if issue.blocks]


def warning_issues(issues: Sequence[PluginReleaseNameIssue]) -> list[str]:
    return [str(issue) for issue in issues if not issue.blocks]
