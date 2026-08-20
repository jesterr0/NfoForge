from pathlib import Path
from unittest.mock import Mock

from pymediainfo import MediaInfo
import pytest

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, TokenData
from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_MEDIAINFO_OBJ,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.nf_jinja2 import Jinja2TemplateEngine
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


def _td() -> TokenData:
    # bare TokenData() has pre_token/post_token = None, which
    # _optional_user_input happily f-string-interpolates as the literal
    # string "None" around the value; tests asserting exact output need the
    # empty-string variant instead.
    return TokenData(pre_token="", post_token="")


def _media_info(width: int, height: int) -> MediaInfo:
    return MediaInfo(
        f"""<Mediainfo><File>
        <track type="General"><Duration>60000</Duration><File_size>1000</File_size></track>
        <track type="Video"><Width>{width}</Width><Height>{height}</Height><Scan_type>Progressive</Scan_type><Frame_rate>24.000</Frame_rate><Format>AVC</Format></track>
        <track type="Audio"><Format>AC-3</Format><Channel_s>2</Channel_s><Language>en</Language></track>
        </File></Mediainfo>"""
    )


def test_active_file_drives_file_specific_tokens_in_series_pack() -> None:
    first_file = Path("Show.S01E01.1080p.WEB-DL.DDP5.1.H.264-GRP.mkv")
    second_file = Path("Show.S01E02.REPACK.720p.WEB-DL.DD2.0.H.264-OTHER.mkv")
    payload = MediaInputPayload(
        input_path=Path("Show.S01"),
        media_type=MediaType.SERIES,
        file_list=[first_file, second_file],
        file_list_mediainfo={
            first_file: _media_info(1920, 1080),
            second_file: _media_info(1280, 720),
        },
    )

    def render(active_file: Path) -> str | None:
        return TokenReplacer(
            media_input_obj=payload,
            media_search_obj=MediaSearchPayload(media_type=MediaType.SERIES),
            token_string="{resolution}|{release_group}|{re_release}|{original_filename}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
            colon_replace=ColonReplace.REPLACE_WITH_DASH,
            flatten=True,
            file_name_mode=False,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            parse_filename_attributes=True,
            season_number=1,
            active_file=active_file,
        ).get_output()

    assert render(first_file) == f"1080p|GRP||{first_file.stem}"
    assert render(second_file) == f"720p|OTHER|REPACK|{second_file.stem}"


def _series_replacer(token: str) -> TokenReplacer:
    file_path = Path("Show.S01E02.mkv")
    return TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 1,
                    "episode": 2,
                    "episode_name": "Selected Order Title",
                    "episode_data": {
                        "seasonNumber": 1,
                        "number": 2,
                        "absoluteNumber": 22,
                        "name": "Selected Order Title",
                        "aired": "2024-02-03",
                    },
                }
            },
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            tvdb_data={
                "firstAired": "2019-04-01",
                "episodes": [
                    {
                        "seasonNumber": 1,
                        "number": 2,
                        "absoluteNumber": 2,
                        "name": "Default Order Title",
                        "aired": "2020-01-02",
                    }
                ],
            },
        ),
        token_string=token,
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=1,
        episode_number=2,
    )


def _series_search_replacer(
    tmdb_data: dict | None = None, tvdb_data: dict | None = None
) -> TokenReplacer:
    file_path = Path("Show.S01E02.mkv")
    return TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            tmdb_data=tmdb_data,
            tvdb_data=tvdb_data,
        ),
        token_string="",
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=1,
        episode_number=2,
    )


def _series_replacer_from_example(token: str) -> TokenReplacer:
    """Mirrors the series-management settings preview's TokenReplacer call
    (`_update_example` in
    src/frontend/stacked_windows/settings/series_management.py):
    EXAMPLE_MEDIA_INPUT_PAYLOAD/EXAMPLE_SEARCH_PAYLOAD, season 1 episode 1,
    flattened, no jinja engine, and no series_episode_map beyond the one
    baked into the fixture itself."""
    return TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string=token,
        jinja_engine=None,
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=1,
        episode_number=1,
    )


def test_example_series_payload_renders_episode_tokens() -> None:
    # Regression test for the series-management settings preview: it feeds
    # EXAMPLE_SEARCH_PAYLOAD/EXAMPLE_MEDIA_INPUT_PAYLOAD into TokenReplacer
    # with no live series_episode_map lookups beyond the fixture's own, so
    # every episode-derived token must resolve to a non-empty value straight
    # from the fixture data. Previously tvdb_data nested everything under a
    # "series" key that production never produces, so these all rendered
    # blank.
    replacer = _series_replacer_from_example("{episode_title} {air_date}")

    assert replacer._episode_title(_td()) == "Some episode name 1"
    assert replacer._air_date(_td()) == "2013-12-02"

    output = replacer.get_output()
    assert output == "Some episode name 1 2013-12-02"


def _series_replacer_with_special() -> TokenReplacer:
    file_path = Path("Show.S00E05.mkv")
    return TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 0,
                    "episode": 5,
                    "episode_name": "Special Episode",
                    "episode_data": {
                        "seasonNumber": 0,
                        "number": 5,
                        "name": "Special Episode",
                        "aired": "2024-05-01",
                    },
                }
            },
        ),
        media_search_obj=MediaSearchPayload(media_type=MediaType.SERIES),
        token_string="{episode_metadata}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=0,
        episode_number=5,
    )


def test_episode_metadata_includes_season_zero_label() -> None:
    replacer = _series_replacer_with_special()
    out = replacer._episode_metadata(token_data=TokenData())

    assert "Season 00" in out
    assert "Episode 05" in out


def test_episode_tokens_prefer_selected_series_mapping() -> None:
    output = _series_replacer(
        "{episode_title_exact} {episode_air_date} {episode_number_absolute}"
    ).get_output()

    assert output == "Selected Order Title 2024-02-03 22"


def _series_replacer_with_episode_name(name: str | None) -> TokenReplacer:
    """Selected-mapping episode data with a caller-supplied ``name``, so
    episode-title placeholder handling can be exercised directly without
    needing a TVDB fallback lookup."""
    file_path = Path("Show.S01E02.mkv")
    return TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 1,
                    "episode": 2,
                    "episode_name": name,
                    "episode_data": {
                        "seasonNumber": 1,
                        "number": 2,
                        "name": name,
                        "aired": "2024-02-03",
                    },
                }
            },
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            # _verify_series_info() short-circuits to "" when tvdb_data is
            # falsy; the selected mapping above still takes priority over
            # this in _get_selected_episode_data, so its content is unused.
            tvdb_data={"firstAired": "2019-01-01"},
        ),
        token_string="",
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=1,
        episode_number=2,
    )


@pytest.mark.parametrize("placeholder_name", ["TBA", "tba", "Episode 12", "Episode12"])
def test_episode_title_tokens_blank_tvdb_placeholder_names(
    placeholder_name: str,
) -> None:
    # TVDB commonly returns placeholder episode names like "TBA" or
    # "Episode 12" for just-aired or unlisted-title episodes; these should
    # render as empty rather than landing in output verbatim.
    replacer = _series_replacer_with_episode_name(placeholder_name)

    assert replacer._episode_title(_td()) == ""
    assert replacer._episode_title_clean(_td()) == ""
    assert replacer._episode_title_exact(_td()) == ""


@pytest.mark.parametrize(
    "real_name", ["The Beginning", "Episode of Care", "TBA Confidential"]
)
def test_episode_title_tokens_keep_titles_resembling_placeholders(
    real_name: str,
) -> None:
    # Real titles that merely resemble the placeholder patterns (extra
    # words, no anchoring match) must not be blanked.
    replacer = _series_replacer_with_episode_name(real_name)

    assert replacer._episode_title(_td()) == real_name
    assert replacer._episode_title_clean(_td()) == real_name
    assert replacer._episode_title_exact(_td()) == real_name


def test_episode_title_tokens_none_name_stays_empty_no_crash() -> None:
    # A manually-mapped episode with no TVDB match synthesizes
    # episode_data["name"] = None; that must stay empty, not crash.
    replacer = _series_replacer_with_episode_name(None)

    assert replacer._episode_title(_td()) == ""
    assert replacer._episode_title_clean(_td()) == ""
    assert replacer._episode_title_exact(_td()) == ""


def test_episode_title_exact_strips_filesystem_hostile_characters() -> None:
    replacer = _series_replacer_with_episode_name("Who Are You: Part 1/2")

    output = replacer._episode_title_exact(_td())

    assert ":" not in output
    assert "/" not in output
    # Separators become a space, matching `_title_formatting_standard`, so
    # "Part 1/2" reads as "Part 1 2" rather than running together as "Part 12".
    assert output == "Who Are You Part 1 2"


def test_episode_title_exact_preserves_non_ascii() -> None:
    # `_title_formatting_standard` also unidecodes; the exact variant must not,
    # or it stops being exact.
    replacer = _series_replacer_with_episode_name("Kimi no Na wa。")

    assert "。" in replacer._episode_title_exact(_td())


def _span_replacer(token: str, *, file_name_mode: bool = False) -> TokenReplacer:
    """A file covering S01E01-E03, mapped to episode 1 with a real title."""
    file_path = Path("Show.S01E01-E03.mkv")
    return TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 1,
                    "episode": 1,
                    "episode_end": 3,
                    "episode_name": "Pilot",
                    "episode_data": {
                        "seasonNumber": 1,
                        "number": 1,
                        "name": "Pilot",
                        "aired": "2024-01-01",
                    },
                }
            },
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            tvdb_data={
                "episodes": [
                    {
                        "seasonNumber": 1,
                        "number": 1,
                        "name": "Pilot",
                        "aired": "2024-01-01",
                    }
                ]
            },
        ),
        token_string=token,
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=file_name_mode,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=1,
        episode_number=1,
    )


@pytest.mark.parametrize(
    "token",
    ["{episode_title}", "{episode_title_clean}", "{episode_title_exact}"],
)
def test_episode_title_tokens_blank_for_a_multi_episode_span(token: str) -> None:
    # A file covering S01E01-E03 has no single episode title. Naming it
    # after episode 1 asserts that one episode's title describes all three.
    assert _span_replacer(token).get_output() == ""


@pytest.mark.parametrize(
    "token",
    ["{episode_title}", "{episode_title_clean}", "{episode_title_exact}"],
)
@pytest.mark.parametrize(
    ("file_name_mode", "expected"),
    [(False, "Show S01E01-03 1080p"), (True, "Show.S01E01-03.1080p.mkv")],
)
def test_multi_episode_span_drops_the_title_from_a_whole_template(
    token: str, file_name_mode: bool, expected: str
) -> None:
    # Both output modes, because the handlers are shared: file_name_mode
    # selects only the final formatting stage, not token resolution.
    #
    # A whole template rather than the bare token: in file_name_mode a name
    # that resolves to nothing at all is rejected and get_output() returns
    # None, so a bare-token assertion would pass without proving the
    # surrounding components survived. This asserts the designator still
    # renders E01-03 and no stray separator is left where the title was.
    output = _span_replacer(
        f"Show S{{season_number|zfill(2)}}E{{episode_number|zfill(2)}} {token} 1080p",
        file_name_mode=file_name_mode,
    ).get_output()

    assert output == expected


@pytest.mark.parametrize(
    "token",
    ["{episode_title}", "{episode_title_clean}", "{episode_title_exact}"],
)
def test_episode_title_tokens_keep_the_title_for_a_single_episode(
    token: str,
) -> None:
    # The guard for the span check: a normal single-episode file is
    # untouched. _series_replacer maps S01E02 with no episode_end.
    assert _series_replacer(token).get_output() == "Selected Order Title"


@pytest.mark.parametrize(
    "token",
    ["{episode_title}", "{episode_title_clean}", "{episode_title_exact}"],
)
def test_episode_title_tokens_stay_blank_for_a_season_pack(token: str) -> None:
    # Already correct today and must not regress while adding the span
    # check: _verify_series_info needs an episode number and a pack has none.
    file_path = Path("Show.S01.mkv")
    replacer = TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            tvdb_data={"episodes": [{"seasonNumber": 1, "number": 1, "name": "Pilot"}]},
        ),
        token_string=token,
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=1,
    )

    assert replacer.get_output() == ""


def test_span_predicate_is_shared_by_episode_number_and_episode_title() -> None:
    # episode_end present but not greater than the start is not a span.
    # Both the designator and the title must agree, which is what makes
    # extracting the predicate worth doing: a fixture that renders the raw
    # start number must also render the title.
    replacer = _multi_episode_replacer(
        "{episode_number}|{episode_title}",
        MultiEpisodeStyle.RANGE,
        episode=2,
        episode_end=2,
    )

    assert replacer.get_output() == "2|Multi Episode"


@pytest.mark.parametrize("placeholder_name", ["TBA", "Episode 12"])
def test_episode_metadata_omits_tvdb_placeholder_name(placeholder_name: str) -> None:
    # {episode_metadata} must not leak a TVDB placeholder episode name into
    # the NFO body, consistent with the episode-title tokens' handling.
    replacer = _series_replacer_with_episode_name(placeholder_name)
    out = replacer._episode_metadata(token_data=TokenData())

    assert placeholder_name not in out
    assert "Season 01 Episode 02" in out


def test_episode_metadata_includes_real_episode_name() -> None:
    replacer = _series_replacer_with_episode_name("The Beginning")
    out = replacer._episode_metadata(token_data=TokenData())

    assert "The Beginning" in out


@pytest.mark.parametrize("placeholder_name", ["TBA", "Episode 12"])
def test_episode_metadata_mediainfo_omits_tvdb_placeholder_name(
    placeholder_name: str,
) -> None:
    replacer = _series_replacer_with_episode_name(placeholder_name)
    out = replacer._episode_metadata_mediainfo(token_data=TokenData())

    assert placeholder_name not in out
    assert "Season 01 Episode 02" in out


def test_episode_metadata_mediainfo_includes_real_episode_name() -> None:
    replacer = _series_replacer_with_episode_name("The Beginning")
    out = replacer._episode_metadata_mediainfo(token_data=TokenData())

    assert "The Beginning" in out


@pytest.mark.parametrize("placeholder_name", ["TBA", "Episode 12"])
def test_get_metadata_synopsis_omits_tvdb_placeholder_name(
    placeholder_name: str,
) -> None:
    # get_metadata_synopsis is not wired to a {...} token yet (planned,
    # unwired), so it's exercised by calling the method directly.
    replacer = _series_replacer_with_episode_name(placeholder_name)
    out = replacer.get_metadata_synopsis()

    assert placeholder_name not in out
    assert "Season 01 Episode 02" in out


def test_get_metadata_synopsis_includes_real_episode_name() -> None:
    replacer = _series_replacer_with_episode_name("The Beginning")
    out = replacer.get_metadata_synopsis()

    assert "The Beginning" in out


def test_episode_number_absolute_falls_back_when_tvdb_value_is_zero() -> None:
    # TVDB commonly stores absoluteNumber: 0 for non-anime episodes; that
    # should be treated as "no absolute number" and fall back to the
    # season-relative episode number instead of rendering "0"/"000".
    file_path = Path("Show.S02E05.mkv")
    replacer = TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 2,
                    "episode": 5,
                    "episode_name": "Non-Anime Episode",
                    "episode_data": {
                        "seasonNumber": 2,
                        "number": 5,
                        "absoluteNumber": 0,
                        "name": "Non-Anime Episode",
                        "aired": "2024-05-01",
                    },
                }
            },
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            tvdb_data={
                "episodes": [
                    {
                        "seasonNumber": 2,
                        "number": 5,
                        "absoluteNumber": 0,
                        "name": "Non-Anime Episode",
                        "aired": "2024-05-01",
                    }
                ]
            },
        ),
        token_string="{episode_number_absolute}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=2,
        episode_number=5,
    )

    assert replacer.get_output() == "5"


def test_end_episode_number_renders_range_end_for_multi_episode_file() -> None:
    file_path = Path("Show.S01E02E03.mkv")
    replacer = TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 1,
                    "episode": 2,
                    "episode_end": 3,
                    "episode_name": "Multi Episode",
                    "episode_data": {
                        "seasonNumber": 1,
                        "number": 2,
                        "name": "Multi Episode",
                        "aired": "2024-02-03",
                    },
                }
            },
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            tvdb_data={"episodes": []},
        ),
        token_string="{end_episode_number}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=1,
        episode_number=2,
    )

    assert replacer.get_output() == "3"


def test_end_episode_number_blank_for_single_episode() -> None:
    output = _series_replacer("{end_episode_number}").get_output()

    assert output == ""


def _multi_episode_replacer(
    token: str,
    multi_episode_style: MultiEpisodeStyle,
    episode: int = 1,
    episode_end: int = 3,
    season: int = 1,
) -> TokenReplacer:
    file_path = Path("Show.S01E01-E03.mkv")
    return TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": season,
                    "episode": episode,
                    "episode_end": episode_end,
                    "episode_name": "Multi Episode",
                }
            },
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES, tvdb_data={"episodes": []}
        ),
        token_string=token,
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=season,
        episode_number=episode,
        multi_episode_style=multi_episode_style,
    )


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        # EXTEND and RANGE collapse to the same "start-end" form because the
        # mapping (Task 4.1) only stores start/end, not the full intermediate
        # episode list EXTEND would otherwise need.
        (MultiEpisodeStyle.EXTEND, "01-03"),
        (MultiEpisodeStyle.DUPLICATE, "01.S01E03"),
        (MultiEpisodeStyle.REPEAT, "01E03"),
        # SCENE and PREFIXED_RANGE likewise collapse to the same
        # "start-Eend" form given only start/end data.
        (MultiEpisodeStyle.SCENE, "01-E03"),
        (MultiEpisodeStyle.RANGE, "01-03"),
        (MultiEpisodeStyle.PREFIXED_RANGE, "01-E03"),
    ],
)
def test_episode_number_renders_multi_episode_designator_per_style(
    style: MultiEpisodeStyle, expected: str
) -> None:
    output = _multi_episode_replacer("{episode_number}", style).get_output()

    assert output == expected


def test_episode_number_single_episode_unchanged_raw_number() -> None:
    # single episode (no episode_end key in the mapping): {episode_number}
    # must render exactly as it did before this feature existed -- the raw
    # start number, unpadded, regardless of the configured MultiEpisodeStyle.
    file_path = Path("Show.S01E01.mkv")
    replacer = TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 1,
                    "episode": 1,
                    "episode_name": "Single Episode",
                }
            },
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES, tvdb_data={"episodes": []}
        ),
        token_string="{episode_number}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=1,
        episode_number=1,
        multi_episode_style=MultiEpisodeStyle.SCENE,
    )

    assert replacer.get_output() == "1"


def test_episode_number_single_episode_still_honors_template_zfill() -> None:
    # single-episode file rendered through a template's own |zfill(2) filter
    # (mirrors the default series token) must still just zero-pad the raw
    # number -- unaffected by the multi-episode styling path.
    output = _multi_episode_replacer(
        "S{season_number|zfill(2)}E{episode_number|zfill(2)}",
        MultiEpisodeStyle.RANGE,
        episode=1,
        episode_end=1,
    ).get_output()

    assert output == "S01E01"


def test_optional_prefix_does_not_consume_the_zfill_filter() -> None:
    """The shipped Aither/LST tokens write the "E" as an optional prefix, not
    as a literal, so it disappears on a season pack.

    Filters used to run after that prefix was already glued on, so zfill(2)
    was handed "E2" -- two characters, so it padded nothing -- and every
    single-episode upload to those trackers shipped as "S01E2". The test above
    missed it by using a literal "E" instead of the ``:opt=`` form.
    """
    padded = _multi_episode_replacer(
        "S{season_number|zfill(2)}{:opt=E:episode_number|zfill(2)}",
        MultiEpisodeStyle.RANGE,
        episode=2,
        episode_end=2,
    ).get_output()

    assert padded == "S01E02"


def test_optional_prefix_is_not_itself_filtered() -> None:
    """A filter describes the token's value; the optional string is a literal
    the user typed and must survive it unchanged."""
    output = _multi_episode_replacer(
        "{:opt=ep :episode_number|upper}",
        MultiEpisodeStyle.RANGE,
        episode=2,
        episode_end=2,
    ).get_output()

    assert output == "ep 2"


def test_episode_number_range_style_end_to_end_template() -> None:
    # end-to-end proof using the shape of the default standard episode token
    # ("S{season_number|zfill(2)}E{episode_number|zfill(2)}"): a RANGE-styled
    # multi-episode file must render "S01E01-03", not drop the range end.
    output = _multi_episode_replacer(
        "S{season_number|zfill(2)}E{episode_number|zfill(2)}",
        MultiEpisodeStyle.RANGE,
    ).get_output()

    assert output == "S01E01-03"


def _season_replacer(
    token: str,
    season: int = 1,
    season_end: int | None = 5,
) -> TokenReplacer:
    file_path = Path("Show.S01.mkv")
    return TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES, tvdb_data={"episodes": []}
        ),
        token_string=token,
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=season,
        season_end=season_end,
    )


def test_season_number_renders_multi_season_pack_range() -> None:
    output = _season_replacer("{season_number}", season=1, season_end=5).get_output()

    assert output == "01-S05"


def test_season_number_end_to_end_template_renders_multi_season_range() -> None:
    # end-to-end proof using the shape of the default series tokens
    # ("S{season_number|zfill(2)}"): a complete-series pack (season 1 through
    # 5) must render "S01-S05", not collapse to just the lowest season.
    output = _season_replacer(
        "S{season_number|zfill(2)}", season=1, season_end=5
    ).get_output()

    assert output == "S01-S05"


@pytest.mark.parametrize("season_end", [None, 1])
def test_season_number_single_season_unchanged(season_end: int | None) -> None:
    # single season (season_end is None, or equals season_number): the raw
    # season number renders unchanged, exactly as it did before this feature.
    output = _season_replacer(
        "{season_number}", season=1, season_end=season_end
    ).get_output()

    assert output == "1"


@pytest.mark.parametrize("season_end", [None, 1])
def test_season_number_single_season_template_zfill_unchanged(
    season_end: int | None,
) -> None:
    output = _season_replacer(
        "S{season_number|zfill(2)}", season=1, season_end=season_end
    ).get_output()

    assert output == "S01"


def test_season_number_season_zero_special_still_renders() -> None:
    # season 0 (specials) is a valid season number, not falsy/absent; a
    # single-season specials pack must still render "0", not blank out due to
    # a truthiness check.
    output = _season_replacer("{season_number}", season=0, season_end=None).get_output()

    assert output == "0"


def test_season_number_season_zero_multi_season_pack_range() -> None:
    # season 0 is a valid start of a range too (explicit comparisons, not
    # truthiness, must gate the multi-season branch).
    output = _season_replacer("{season_number}", season=0, season_end=2).get_output()

    assert output == "00-S02"


def test_air_date_is_series_level_first_aired_distinct_from_episode_air_date() -> None:
    # {air_date} is series-level (parallels the movie {release_date} token) and
    # must differ from {episode_air_date}, which stays the selected episode's
    # own air date.
    output = _series_replacer("{air_date} {episode_air_date}").get_output()

    assert output == "2019-04-01 2024-02-03"


def test_series_nfo_tokens_render_selected_episode_context() -> None:
    file_path = Path("Show.S01E02.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
        file_list_mediainfo={file_path: EXAMPLE_MEDIAINFO_OBJ},
        series_episode_map={
            file_path: {
                "season": 1,
                "episode": 2,
                "episode_name": "Selected Order Title",
                "episode_data": {
                    "seasonNumber": 1,
                    "number": 2,
                    "absoluteNumber": 22,
                    "name": "Selected Order Title",
                    "aired": "2024-02-03",
                },
            }
        },
    )

    output = TokenReplacer(
        media_input_obj=media_input,
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        token_string=(  # noqa: S106 - NFO template token string used as test fixture data, not a credential
            "{{ season_number }}|{{ episode_number }}|"
            "{{ episode_title_exact }}|{{ air_date }}|{{ episode_air_date }}"
        ),
        jinja_engine=Jinja2TemplateEngine(),
        season_number=1,
        episode_number=2,
    ).get_output()

    # EXAMPLE_SEARCH_PAYLOAD's tvdb_data now matches production's flat shape,
    # so {air_date} resolves to the series-level "firstAired" value;
    # {episode_air_date} still resolves from the selected episode.
    assert output == "1|2|Selected Order Title|2013-12-02|2024-02-03"


def test_series_pack_nfo_single_episode_tokens_stay_blank() -> None:
    file_one = Path("Show.S01E02.mkv")
    file_two = Path("Show.S01E03.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show.S01"),
        media_type=MediaType.SERIES,
        file_list=[file_one, file_two],
        file_list_mediainfo={
            file_one: EXAMPLE_MEDIAINFO_OBJ,
            file_two: EXAMPLE_MEDIAINFO_OBJ,
        },
        series_episode_map={
            file_one: {
                "season": 1,
                "episode": 2,
                "episode_name": "Episode Two",
                "episode_data": {
                    "seasonNumber": 1,
                    "number": 2,
                    "name": "Episode Two",
                    "aired": "2024-02-03",
                },
            },
            file_two: {
                "season": 1,
                "episode": 3,
                "episode_name": "Episode Three",
                "episode_data": {
                    "seasonNumber": 1,
                    "number": 3,
                    "name": "Episode Three",
                    "aired": "2024-02-10",
                },
            },
        },
    )

    output = TokenReplacer(
        media_input_obj=media_input,
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        token_string=(  # noqa: S106 - NFO template token string used as test fixture data, not a credential
            "{{ season_number }}|{{ episode_number }}|"
            "{{ episode_title_exact }}|{{ episode_metadata }}"
        ),
        jinja_engine=Jinja2TemplateEngine(),
        season_number=1,
        episode_number=None,
    ).get_output()

    assert output is not None
    first_line, metadata = output.split("|", 3)[0:3], output.split("|", 3)[3]
    assert first_line == ["1", "", ""]
    assert "Episode Two" in metadata
    assert "Episode Three" in metadata


def test_flat_token_with_episode_title_clean_only_does_not_return_none() -> None:
    # token string uses {episode_title_clean} but NOT {title_clean}; the
    # substring "title_clean" inside "episode_title_clean" previously caused
    # a KeyError on filled_tokens["title_clean"], swallowed into None output
    output = _series_replacer("{episode_title_clean}").get_output()

    assert output is not None
    assert output == "Selected Order Title"


def test_flat_original_title_clean_fallback_only_does_not_return_none() -> None:
    # token string uses {original_title_fallback_title_clean} alone; same substring
    # collision as above must not raise a KeyError and return None
    output = _series_replacer("{original_title_fallback_title_clean}").get_output()

    assert output is not None


def test_total_seasons_and_episodes_prefer_tmdb_counts() -> None:
    # TVDB's "seasons" list has one row per (season-type x season)
    # combination, so it's deliberately built "wrong" here (14 rows across
    # two season-types, including a season-0/specials row) to prove it's
    # ignored whenever TMDB's clean rollup counts are present.
    tvdb_seasons_rows = [
        {"number": season_num, "type": {"type": season_type}}
        for season_type in ("official", "dvd")
        for season_num in range(0, 7)  # season 0 (specials) + seasons 1-6
    ]
    assert len(tvdb_seasons_rows) == 14

    replacer = _series_search_replacer(
        tmdb_data={"number_of_seasons": 5, "number_of_episodes": 62},
        tvdb_data={"seasons": tvdb_seasons_rows},
    )

    assert replacer._total_seasons(_td()) == "5"
    assert replacer._total_episodes(_td()) == "62"


def test_total_seasons_falls_back_to_tvdb_filtered_count_excluding_special() -> None:
    # no TMDB counts available; TVDB's raw "seasons" rows span two
    # season-types (14 rows total) but only 6 real seasons (season 0 is
    # specials and must be excluded).
    tvdb_seasons_rows = [
        {"number": season_num, "type": {"type": season_type}}
        for season_type in ("official", "dvd")
        for season_num in range(0, 7)
    ]

    replacer = _series_search_replacer(
        tmdb_data=None,
        tvdb_data={"seasons": tvdb_seasons_rows},
    )

    assert replacer._total_seasons(_td()) == "6"


def test_total_seasons_fallback_prefers_official_season_type_when_listed_after_others() -> (
    None
):
    # TVDB's "seasons" list has no ordering guarantee; a payload can list
    # "dvd" (or other non-official) rows before "official" rows for the same
    # series. The fallback must still count the "official" order (the
    # codebase's canonical/aired order -- see TVDBSeasonType.AIRED_ORDER and
    # media_search.py's `season_type.api_param == "official"` checks), not
    # whichever type happens to appear first in the list.
    tvdb_seasons_rows = [
        # dvd rows come first and, if wrongly preferred, would report 7
        # seasons instead of the correct official count of 5.
        {"number": season_num, "type": {"type": "dvd"}}
        for season_num in range(0, 8)  # season 0 (specials) + 7 dvd seasons
    ] + [
        {"number": season_num, "type": {"type": "official"}}
        for season_num in range(0, 6)  # season 0 (specials) + 5 official seasons
    ]

    replacer = _series_search_replacer(
        tmdb_data=None,
        tvdb_data={"seasons": tvdb_seasons_rows},
    )

    assert replacer._total_seasons(_td()) == "5"


def test_total_episodes_falls_back_to_tvdb_excluding_special_episodes() -> None:
    # no TMDB counts available; TVDB's "episodes" rows include a season-0
    # (specials) episode that must be excluded from the total.
    tvdb_episodes_rows = [
        {"seasonNumber": 0, "number": 1},
        {"seasonNumber": 1, "number": 1},
        {"seasonNumber": 1, "number": 2},
        {"seasonNumber": 2, "number": 1},
    ]

    replacer = _series_search_replacer(
        tmdb_data=None,
        tvdb_data={"episodes": tvdb_episodes_rows},
    )

    assert replacer._total_episodes(_td()) == "3"


def test_jinja_nfo_rendering_only_evaluates_referenced_tokens() -> None:
    file_path = Path("Missing.MediaInfo.File.S01E02.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
    )

    output = TokenReplacer(
        media_input_obj=media_input,
        media_search_obj=MediaSearchPayload(media_type=MediaType.SERIES),
        token_string="{{ title }}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        jinja_engine=Jinja2TemplateEngine(),
    ).get_output()

    assert output == "Missing MediaInfo File"


def test_get_mi_synopsis_handles_no_video_track() -> None:
    # A file with no video track (e.g. an audio-only or corrupt rip) must not
    # crash the whole render; get_mi_synopsis should degrade gracefully like
    # the already-guarded audio loop below it.
    fake_mi_no_video = Mock(spec=MediaInfo)
    fake_mi_no_video.video_tracks = []
    fake_mi_no_video.audio_tracks = []

    replacer = _series_replacer("")
    out = replacer.get_mi_synopsis(fake_mi_no_video)

    assert isinstance(out, str)


def test_media_type_token_renders_series() -> None:
    output = TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string="{{ media_type }}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        jinja_engine=Jinja2TemplateEngine(),
    ).get_output()

    assert output == "Series"


def test_media_type_token_drives_the_series_branch_of_a_conditional() -> None:
    output = TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string='{% if media_type == "Series" %}series{% else %}movie{% endif %}',  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        jinja_engine=Jinja2TemplateEngine(),
    ).get_output()

    assert output == "series"


@pytest.mark.parametrize(
    ("anilist_id", "anilist_data", "episode_format", "expected"),
    [
        ("123", None, EpisodeFormat.STANDARD, "Anime"),
        (None, {"id": 123}, EpisodeFormat.STANDARD, "Anime"),
        (None, None, EpisodeFormat.ANIME_ABSOLUTE, "Anime"),
        (None, None, EpisodeFormat.STANDARD, ""),
    ],
)
def test_is_anime_token_covers_each_signal(
    anilist_id: str | None,
    anilist_data: dict[str, int] | None,
    episode_format: EpisodeFormat,
    expected: str,
) -> None:
    # Each of the three positive signals gets its own case: a change that drops
    # one of them from the shared helper would otherwise still pass.
    media_file = Path("Show.S01E01.mkv")
    media_input = MediaInputPayload(
        input_path=media_file,
        media_type=MediaType.SERIES,
        file_list=[media_file],
        file_list_mediainfo={media_file: EXAMPLE_MEDIAINFO_OBJ},
        series_episode_format=episode_format,
    )

    output = TokenReplacer(
        media_input_obj=media_input,
        token_string="{{ is_anime }}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            anilist_id=anilist_id,
            anilist_data=anilist_data,
        ),
        jinja_engine=Jinja2TemplateEngine(),
    ).get_output()

    assert output == expected


def test_is_anime_token_is_falsy_in_a_conditional_when_not_anime() -> None:
    # Guards the reason the token renders "Anime"/"" instead of "True"/"False":
    # a non-empty string is truthy in Jinja, so "False" would break every
    # {% if is_anime %} block.
    output = TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string="{% if is_anime %}anime{% else %}not anime{% endif %}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        jinja_engine=Jinja2TemplateEngine(),
    ).get_output()

    assert output == "not anime"


def _series_audio_replacer() -> TokenReplacer:
    # `_series_replacer` builds a payload with no MediaInfo, so audio tokens
    # would fall through to guessit. The example payload carries a real
    # MediaInfo object whose first audio track is MLP FBA without the 16-ch
    # variant, which is the non-Atmos case.
    return TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token_string="{audio_codec}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        flatten=True,
        file_name_mode=True,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
    )


def test_audio_codec_tokens_when_there_is_no_atmos() -> None:
    replacer = _series_audio_replacer()

    assert replacer._audio_codec(_td()) == "TrueHD"
    assert replacer._audio_codec_no_atmos(_td()) == "TrueHD"
    assert replacer._atmos(_td()) == ""
