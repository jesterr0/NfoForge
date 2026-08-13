"""Quality bar for the packaged per-tracker title defaults.

These defaults are now a *starting point*, not a lock -- every tracker's title
override is the user's to edit (see title_override_support.py). That makes
them more important, not less: they are what a fresh profile uploads with, and
what the schema 5 -> 6 migration puts back onto profiles that never got to
choose. A default that renders a malformed title ships that title to whoever
did not think to look.

This file checks they are well formed. `test_tracker_naming_rules.py` checks
that the four trackers whose rules were audited match those rules exactly.
"""

from dataclasses import replace
from pathlib import Path
import re

import pytest

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD as MOVIE_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD as MOVIE_SEARCH_PAYLOAD,
)
from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD as SERIES_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD as SERIES_SEARCH_PAYLOAD,
)
from src.config.config import ConfigManager
from src.config.tv_tokens import SUPPORTED_TVR_FORMATS
from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.enums.tracker_selection import TrackerSelection
from src.payloads.trackers import TrackerInfo
from tests.test_config.config_tree import build_config_paths

# Carries the punctuation these trackers name uploads after: a colon, a
# hyphen, an apostrophe and an ampersand. The packaged title-clean rules
# strip all four, so any one of them surviving proves the packaged token no
# longer reads those rules.
PUNCTUATED_TITLE = "Alice & Bob: A Placeholder's Tale - Part One"


def _config_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    """Load the packaged default config through the real loader.

    Reading the TOML directly would mean duplicating the TrackerSelection ->
    section-name mapping that lives in src/config/operations.py. Going
    through ConfigManager tests the values as the app actually sees them.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    return ConfigManager("test", build_config_paths(tmp_path))


def _ships_movie_title(packaged: TrackerInfo) -> bool:
    """Does the packaged default supply a movie title?

    Both forms count: a token, or a character rule with no token, which leaves
    the user's global movie template to supply the wording.
    """
    return bool(
        packaged.mvr_title_override_enabled
        and (
            packaged.mvr_title_token_override.strip() or packaged.mvr_title_replace_map
        )
    )


def _ships_series_title(packaged: TrackerInfo, episode_format: EpisodeFormat) -> bool:
    entry = (packaged.tvr_title_overrides or {}).get(episode_format)
    return bool(entry and entry.enabled and (entry.token.strip() or entry.replace_map))


def test_series_defaults_are_all_or_nothing_per_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tracker either ships a series title for every supported episode
    format or for none of them.

    A partially filled tracker is the dangerous state: Standard uploads get
    the packaged format while Daily and Anime fall through to the global
    series template, with nothing to signal the inconsistency.
    """
    manager = _config_manager(tmp_path, monkeypatch)
    packaged = manager.defaults.trackers.by_selection()

    for tracker in TrackerSelection:
        shipped = {
            fmt
            for fmt in SUPPORTED_TVR_FORMATS
            if _ships_series_title(packaged[tracker], fmt)
        }
        assert shipped in (set(), set(SUPPORTED_TVR_FORMATS)), (
            f"{tracker} ships a series title for {sorted(map(str, shipped))} "
            f"but not for {sorted(map(str, set(SUPPORTED_TVR_FORMATS) - shipped))}; "
            "series defaults must cover every format or none"
        )


def test_the_audited_trackers_ship_a_title_for_both_media_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aither, LST and BeyondHD had their naming rules audited for both movies
    and series, so both must be seeded. ReelFliX is movie-only.

    Deliberately narrow: this pins the intended outcome of that work and is
    expected to need editing if a tracker's rules change. The invariant above
    is the one that generalizes.
    """
    manager = _config_manager(tmp_path, monkeypatch)
    packaged = manager.defaults.trackers.by_selection()

    for tracker in (
        TrackerSelection.AITHER,
        TrackerSelection.LST,
        TrackerSelection.BEYOND_HD,
    ):
        assert _ships_movie_title(packaged[tracker]), f"{tracker} ships no movie title"
        for fmt in SUPPORTED_TVR_FORMATS:
            assert _ships_series_title(packaged[tracker], fmt), (
                f"{tracker} ships no series title for {fmt}"
            )

    assert _ships_movie_title(packaged[TrackerSelection.REELFLIX])


def _render_title(
    token: str,
    colon_replace: ColonReplace,
    media_type: MediaType,
    title_clean_rules: list[tuple[str, str]],
    override_tokens: dict[str, str] | None = None,
) -> str | None:
    """Render a packaged token the way generate_tracker_title renders it.

    Built on the same example payloads the settings preview uses, so every
    token in these templates resolves against realistic mediainfo instead of
    a stub that half of them would crash on.
    """
    if media_type is MediaType.SERIES:
        media_input = SERIES_INPUT_PAYLOAD
        search = SERIES_SEARCH_PAYLOAD
        series_kwargs: dict[str, object] = {"season_number": 1, "episode_number": 1}
    else:
        media_input = MOVIE_INPUT_PAYLOAD
        search = MOVIE_SEARCH_PAYLOAD
        series_kwargs = {}

    return TokenReplacer(
        media_input_obj=media_input,
        media_search_obj=replace(search, title=PUNCTUATED_TITLE),
        token_string=token,
        colon_replace=colon_replace,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        parse_filename_attributes=True,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        # Passed live by generate_tracker_title, so a packaged token that
        # reads these renders differently per user.
        title_clean_rules=title_clean_rules,
        override_tokens=override_tokens,
        **series_kwargs,
    ).get_output()


# A separator left stranded once a token resolves to nothing: "- )" before a
# closing bracket, or a title trailing off in "-" / "- ".
_DANGLING_SEPARATOR = re.compile(r"-\s*\)|\(\s*-|-\s*$")


def test_no_packaged_title_dangles_a_separator_without_a_release_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A separator has to belong to the token it separates.

    Written as `{:opt=-:release_group}` the hyphen is part of the token and
    disappears with it, but written as a literal it survives an untagged
    release and ships a stranded "- )". HUNO's movie title did exactly that.
    """
    manager = _config_manager(tmp_path, monkeypatch)
    packaged = manager.defaults.trackers.by_selection()
    no_group = {"release_group": ""}
    checked = 0

    for tracker in TrackerSelection:
        info = packaged[tracker]
        tokens: list[tuple[str, str, ColonReplace, MediaType]] = []
        if info.mvr_title_token_override.strip():
            tokens.append(
                (
                    "movie",
                    info.mvr_title_token_override,
                    info.mvr_title_colon_replace,
                    MediaType.MOVIE,
                )
            )
        tokens.extend(
            (str(fmt), entry.token, entry.colon_replace, MediaType.SERIES)
            for fmt, entry in (info.tvr_title_overrides or {}).items()
            if entry.token.strip()
        )

        for label, token, colon_replace, media_type in tokens:
            rendered = _render_title(
                token,
                colon_replace,
                media_type,
                manager.settings.global_management.title_clean_rules,
                override_tokens=no_group,
            )
            assert rendered is not None
            checked += 1
            assert not _DANGLING_SEPARATOR.search(rendered.strip()), (
                f"{tracker}'s {label} title strands a separator when the "
                f"release has no group: {rendered.strip()!r}"
            )

    assert checked, "no packaged titles were rendered, so nothing was checked"


def test_packaged_movie_titles_keep_source_punctuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aither, LST and ReelFliX name uploads after the database title, so the
    punctuation in that title has to survive.

    These templates used to open with ``{title_clean}``, which runs the
    global, user-editable clean rules -- and the packaged rule set replaces
    every non-alphanumeric character with a space. Feeding those same rules
    in here is the point of the test: it fails again the moment a packaged
    token starts reading them.
    """
    manager = _config_manager(tmp_path, monkeypatch)
    packaged = manager.defaults.trackers.by_selection()
    clean_rules = manager.defaults.global_management.title_clean_rules

    for tracker in (
        TrackerSelection.AITHER,
        TrackerSelection.LST,
        TrackerSelection.REELFLIX,
    ):
        info = packaged[tracker]
        rendered = _render_title(
            info.mvr_title_token_override,
            info.mvr_title_colon_replace,
            MediaType.MOVIE,
            clean_rules,
        )
        assert rendered is not None
        assert rendered.startswith(PUNCTUATED_TITLE), (
            f"{tracker} rendered '{rendered}', which drops punctuation from "
            f"'{PUNCTUATED_TITLE}'"
        )


def test_packaged_series_titles_keep_source_punctuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The series templates carry the same guarantee as the movie one.

    Without this a series name would render one way for a movie upload and
    another for an episode on the same tracker.
    """
    manager = _config_manager(tmp_path, monkeypatch)
    packaged = manager.defaults.trackers.by_selection()
    clean_rules = manager.defaults.global_management.title_clean_rules

    for tracker in (TrackerSelection.AITHER, TrackerSelection.LST):
        overrides = packaged[tracker].tvr_title_overrides or {}
        for fmt in SUPPORTED_TVR_FORMATS:
            entry = overrides[fmt]
            rendered = _render_title(
                entry.token,
                entry.colon_replace,
                MediaType.SERIES,
                clean_rules,
            )
            assert rendered is not None
            assert rendered.startswith(PUNCTUATED_TITLE), (
                f"{tracker} rendered '{rendered}' for {fmt}, which drops "
                f"punctuation from '{PUNCTUATED_TITLE}'"
            )
