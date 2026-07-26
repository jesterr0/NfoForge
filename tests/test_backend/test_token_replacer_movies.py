from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, TokenData
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.enums.media_type import MediaType
from src.enums.token_replacer import UnfilledTokenRemoval
from src.nf_jinja2 import Jinja2TemplateEngine
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


def test_media_type_token_renders_movie() -> None:
    output = TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string="{{ media_type }}",
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        jinja_engine=Jinja2TemplateEngine(),
    ).get_output()

    assert output == "Movie"


def test_media_type_token_drives_the_movie_branch_of_a_conditional() -> None:
    # The shape the docs tell users to write. Asserting on the rendered branch
    # rather than on the bare value means a change to what {media_type}
    # returns breaks a test that looks like a real template.
    output = TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string='{% if media_type == "Series" %}series{% else %}movie{% endif %}',
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        jinja_engine=Jinja2TemplateEngine(),
    ).get_output()

    assert output == "movie"


def test_is_anime_token_renders_for_an_anime_film() -> None:
    # AniList is queried on Animation genre plus Japanese original language,
    # with no media type condition, so anime films resolve too.
    output = TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string="{{ is_anime }}",
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.MOVIE, anilist_id="123"
        ),
        jinja_engine=Jinja2TemplateEngine(),
    ).get_output()

    assert output == "Anime"
