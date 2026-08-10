"""A REQUIRED tracker must actually enforce something.

REQUIRED locks the user out of the title override and makes the packaged
default govern (see generate_tracker_title in src/backend/process.py). If
that packaged default enforces nothing, the lock is config that does
nothing: the user loses control and gains no guarantee in exchange.

What gets enforced varies by tracker, and both forms count. Aither, LST and
ReelFliX enforce a token. MoreThanTV and TorrentLeech ship an empty token --
so the user's global movie template supplies the wording -- and enforce a
character rule instead: MTV rewrites spaces to dots, TorrentLeech does the
reverse.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.backend.trackers.title_format_policy import (
    TRACKER_TITLE_FORMAT_POLICY,
    TitleFormatPolicy,
)
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
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.enums.tracker_selection import TrackerSelection
from tests.test_config.config_tree import build_config_paths

# Carries the punctuation these trackers name uploads after: a colon, a
# hyphen, an apostrophe and an ampersand. The packaged title-clean rules
# strip all four, so any one of them surviving proves the enforced token no
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


def test_required_trackers_enforce_something(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _config_manager(tmp_path, monkeypatch)
    packaged = manager.defaults.trackers.by_selection()

    for tracker, policy in TRACKER_TITLE_FORMAT_POLICY.items():
        if policy is not TitleFormatPolicy.REQUIRED:
            continue
        info = packaged[tracker]
        assert info.mvr_title_override_enabled, (
            f"{tracker} is REQUIRED but its packaged override is disabled, "
            "so the lock enforces nothing"
        )
        assert info.mvr_title_token_override.strip() or info.mvr_title_replace_map, (
            f"{tracker} is REQUIRED but ships neither a title token nor a "
            "replace rule, so the lock enforces nothing"
        )


def test_series_title_enforcement_is_all_or_nothing_per_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tracker either enforces a series title for every supported episode
    format or for none of them.

    A partially filled tracker is the dangerous state: Standard uploads get
    the enforced format while Daily and Anime fall through to the global
    series template, with nothing to signal the inconsistency. Framed as a
    per-tracker invariant rather than a list of which trackers enforce
    series titles, so a tracker gaining or losing series enforcement needs
    no edit here.
    """
    manager = _config_manager(tmp_path, monkeypatch)
    packaged = manager.defaults.trackers.by_selection()

    for tracker in TRACKER_TITLE_FORMAT_POLICY:
        overrides = packaged[tracker].tvr_title_overrides or {}
        enforced = {
            fmt
            for fmt in SUPPORTED_TVR_FORMATS
            if (entry := overrides.get(fmt)) is not None
            and entry.enabled
            and entry.token.strip()
        }
        assert enforced in (set(), set(SUPPORTED_TVR_FORMATS)), (
            f"{tracker} enforces a series title for {sorted(map(str, enforced))} "
            f"but not for {sorted(map(str, set(SUPPORTED_TVR_FORMATS) - enforced))}; "
            "series enforcement must cover every format or none"
        )


def test_aither_and_lst_enforce_a_series_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two trackers this change targets actually ship what it promises.

    Deliberately narrow: this pins the intended outcome of this change, and
    is expected to need editing if either tracker's rules change. The
    invariant above is the one that generalizes.
    """
    manager = _config_manager(tmp_path, monkeypatch)
    packaged = manager.defaults.trackers.by_selection()

    for tracker in (TrackerSelection.AITHER, TrackerSelection.LST):
        overrides = packaged[tracker].tvr_title_overrides or {}
        for fmt in SUPPORTED_TVR_FORMATS:
            entry = overrides.get(fmt)
            assert entry is not None and entry.enabled and entry.token.strip(), (
                f"{tracker} ships no enforced series title for {fmt}"
            )


def _render_title(
    token: str,
    colon_replace: ColonReplace,
    media_type: MediaType,
    title_clean_rules: list[tuple[str, str]],
) -> str | None:
    """Render an enforced token the way generate_tracker_title renders it.

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
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        # Passed live by generate_tracker_title whatever the policy says, so
        # an enforced token that reads these is not really enforced.
        title_clean_rules=title_clean_rules,
        **series_kwargs,
    ).get_output()


def test_enforced_movie_title_keeps_source_punctuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aither, LST and ReelFliX name uploads after the database title, so the
    punctuation in that title has to survive.

    These templates used to open with ``{title_clean}``, which runs the
    global, user-editable clean rules -- and the packaged rule set replaces
    every non-alphanumeric character with a space. Feeding those same rules
    in here is the point of the test: it fails again the moment an enforced
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


def test_enforced_series_title_keeps_source_punctuation(
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
