from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, TokenData
from src.backend.utils.audio_codecs import AudioCodecs
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.backend.utils.resolution import VideoResolutionAnalyzer
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


def test_audio_codec_reads_the_conventions_file_once_per_instance(monkeypatch) -> None:
    # Three tokens now share this value. Without the cache each one re-reads
    # and re-parses the conventions JSON on every occurrence in a template.
    calls: list[object] = []
    original = AudioCodecs.get_codec

    def counting_get_codec(self, mi_obj, json_path):
        calls.append(json_path)
        return original(self, mi_obj, json_path)

    monkeypatch.setattr(AudioCodecs, "get_codec", counting_get_codec)

    replacer = _movie_replacer()
    first = replacer._audio_codec(_td())
    second = replacer._audio_codec(_td())

    assert first == "TrueHD Atmos"
    assert second == "TrueHD Atmos"
    assert len(calls) == 1


def test_resolution_detection_is_cached_per_scan_mode(monkeypatch) -> None:
    calls: list[bool] = []

    def counting_get_resolution(self, remove_scan: bool = False) -> str:
        calls.append(remove_scan)
        return "1080" if remove_scan else "1080p"

    monkeypatch.setattr(
        VideoResolutionAnalyzer, "get_resolution", counting_get_resolution
    )

    replacer = _movie_replacer()
    assert replacer._detect_resolution(replacer.media_info_obj, True) == "1080"
    assert replacer._detect_resolution(replacer.media_info_obj, True) == "1080"
    assert replacer._detect_resolution(replacer.media_info_obj, False) == "1080p"
    assert replacer._detect_resolution(replacer.media_info_obj, False) == "1080p"

    assert calls == [True, False]


def test_resolution_cache_is_shared_across_replacers(monkeypatch) -> None:
    calls: list[bool] = []

    def counting_get_resolution(self, remove_scan: bool = False) -> str:
        calls.append(remove_scan)
        return "1080" if remove_scan else "1080p"

    monkeypatch.setattr(VideoResolutionAnalyzer, "get_resolution", counting_get_resolution)

    # TokenReplacer instances share the cache through their common payload;
    # callers do not need to thread a cache through every renderer call.
    EXAMPLE_MEDIA_INPUT_PAYLOAD.analysis_cache.clear()
    first = _movie_replacer()
    second = _movie_replacer()

    assert first._detect_resolution(first.media_info_obj, True) == "1080"
    assert second._detect_resolution(second.media_info_obj, True) == "1080"
    assert calls == [True]
    EXAMPLE_MEDIA_INPUT_PAYLOAD.analysis_cache.clear()


def test_audio_codec_tokens_split_atmos_out() -> None:
    replacer = _movie_replacer()

    assert replacer._audio_codec(_td()) == "TrueHD Atmos"
    assert replacer._audio_codec_no_atmos(_td()) == "TrueHD"
    assert replacer._atmos(_td()) == "Atmos"


def test_audio_codec_no_atmos_plus_atmos_reconstructs_audio_codec() -> None:
    # The property the whole design rests on: both new tokens read the same
    # resolved codec string, so they can never contradict {audio_codec}.
    replacer = _movie_replacer()

    rebuilt = f"{replacer._audio_codec_no_atmos(_td())} {replacer._atmos(_td())}"

    assert rebuilt.strip() == replacer._audio_codec(_td())


def test_audio_codec_tokens_resolve_through_the_token_string() -> None:
    # The direct-resolver tests above would still pass if the registry entry
    # or the dispatch branch were deleted; this one goes through get_output()
    # so it fails if the tokens stop being reachable.
    output = TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string="{audio_codec_no_atmos}.{atmos}",
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        flatten=True,
        file_name_mode=True,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
    ).get_output()

    assert output == "TrueHD.Atmos.mkv"


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
