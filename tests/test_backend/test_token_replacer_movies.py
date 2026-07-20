from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, TokenData
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.enums.token_replacer import UnfilledTokenRemoval


def _td() -> TokenData:
    # bare TokenData() leaves pre_token/post_token as None, which
    # _optional_user_input interpolates as the literal string "None" around
    # the value; tests asserting exact output need the empty-string variant.
    return TokenData(pre_token="", post_token="")


def _movie_replacer() -> TokenReplacer:
    # Mirrors the movies-management settings preview's TokenReplacer call
    # (MoviesManagementSettings._update_example), so the test exercises the
    # same path that runs when the Settings token preview renders on launch.
    return TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string="{frame_size}",
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        flatten=True,
        file_name_mode=True,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
    )


def test_frame_size_normalizes_imax_without_mutating_during_iteration() -> None:
    # The example movie filename parses to two editions
    # (["Director's Cut", "IMAX"]). _frame_size collapses any IMAX edition
    # to "IMAX", and must do so without mutating the set it iterates.
    #
    # A dev regression cleared/added to `edition_set` mid-loop, raising
    # "RuntimeError: Set changed size during iteration" whenever a non-IMAX
    # edition was visited before IMAX. Because set iteration order is
    # randomized per process, this crashed on roughly half of cold launches.
    #
    # Asserting the exact "IMAX" output fails deterministically on the buggy
    # code under every ordering: either it raises, or (when IMAX is visited
    # first) it returns the un-normalized "IMAX Director's Cut".
    replacer = _movie_replacer()

    editions = replacer.guess_name.get("edition")
    assert isinstance(editions, list)
    assert "IMAX" in editions
    assert any("imax" not in str(e).lower() for e in editions)

    assert replacer._frame_size(_td()) == "IMAX"
