"""The global title templates a user keeps, and what must hold of them.

This file used to police every tracker's packaged title default, opening
with the claim that they were "a *starting point*, not a lock -- every
tracker's title override is the user's to edit". That is the philosophy the
hardcoded entries reverse, and there are no per-tracker defaults left to
police.

What survives is the fallback: the global movie and series title templates
that decision 5 keeps editable, and which the seven trackers with no
composition of their own still render.
"""

from pathlib import Path

import pytest

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD as MOVIE_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD as MOVIE_SEARCH,
)
from src.config.config import ConfigManager
from src.config.tv_tokens import SUPPORTED_TVR_FORMATS, get_tvr_title_token
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from tests.test_config.config_tree import build_config_paths


def _config_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    return ConfigManager("test", build_config_paths(tmp_path))


def _render(token_string: str, release_group: str) -> str:
    output = TokenReplacer(
        media_input_obj=MOVIE_PAYLOAD,
        media_search_obj=MOVIE_SEARCH,
        token_string=token_string,
        colon_replace=ColonReplace.KEEP,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        override_tokens={"release_group": release_group},
    ).get_output()
    assert output is not None
    return output


def test_the_global_movie_template_is_shipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seven trackers render this, so an empty one would leave them with no
    # title at all and fall through to the release-name fallback.
    manager = _config_manager(tmp_path, monkeypatch)

    assert manager.defaults.movie.title_token.strip()


@pytest.mark.parametrize("episode_format", SUPPORTED_TVR_FORMATS)
def test_a_global_series_template_is_shipped_for_every_format(
    episode_format: EpisodeFormat,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _config_manager(tmp_path, monkeypatch)

    assert get_tvr_title_token(manager.defaults.series, episode_format).strip()


def test_the_global_movie_template_dangles_no_separator_without_a_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An untagged release must not end in a bare separator.

    The tag is written as an optional prefix so the hyphen leaves with the
    group rather than trailing after it.
    """
    manager = _config_manager(tmp_path, monkeypatch)

    rendered = _render(manager.defaults.movie.title_token, "")

    assert rendered
    assert not rendered.rstrip().endswith(("-", ".", "_"))


@pytest.mark.parametrize("episode_format", SUPPORTED_TVR_FORMATS)
def test_a_global_series_template_dangles_no_separator_without_a_group(
    episode_format: EpisodeFormat,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _config_manager(tmp_path, monkeypatch)
    token = get_tvr_title_token(manager.defaults.series, episode_format)

    rendered = _render(token, "")

    assert rendered
    assert not rendered.rstrip().endswith(("-", ".", "_"))
