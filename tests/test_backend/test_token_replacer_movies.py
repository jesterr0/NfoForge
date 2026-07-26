from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, TokenData
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.enums.media_type import MediaType
from src.enums.token_replacer import UnfilledTokenRemoval
from src.payloads.media_search import MediaSearchPayload


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


def test_title_tokens_use_first_guessit_title_when_list_shaped(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "src.backend.token_replacer.guessit",
        lambda *_args, **_kwargs: {"title": ["Primary Title", "Alternative"]},
    )
    replacer = TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string="{title_exact}",
        media_search_obj=MediaSearchPayload(media_type=MediaType.MOVIE),
        flatten=True,
        file_name_mode=True,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
    )

    assert replacer._title_exact(_td()) == "Primary Title"


def _movie_filename(token_string: str) -> str | None:
    return TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string=token_string,
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        flatten=True,
        file_name_mode=True,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
    ).get_output()


def test_empty_token_at_either_end_leaves_no_stray_separator() -> None:
    # _format_token_string collapses runs of dots before it appends the file
    # suffix, so it cannot see the doubled dot that a trailing empty token
    # creates. A leading empty token is worse than cosmetic: a name starting
    # with "." is a hidden file on Unix.
    #
    # {video_3d} is empty for this fixture, so each of these differs from the
    # control only by a token that contributes nothing.
    assert _movie_filename("{title_exact}") == "Movie.Name.mkv"
    assert _movie_filename("{title_exact}.{video_3d}") == "Movie.Name.mkv"
    assert _movie_filename("{video_3d}.{title_exact}") == "Movie.Name.mkv"
