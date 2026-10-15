"""Tests for the pure episode-matching helpers.

No Qt here -- these are the rules the matcher widget applies, extracted so
they can be pinned without a ``QApplication``.
"""

from nfoforge.backend.utils.episode_matching import (
    ParsedFile,
    check_title_against_episode,
    claimed_season_episodes,
    comparable_title,
    episode_designator,
    episode_spec_text,
    expand_mapping_episodes,
    multi_part_groups,
    parse_episode_spec,
    rank_episode_orderings,
    rank_title_candidates,
    resolve_part_reference,
    score_episode_ordering,
    shared_span_title,
    strip_part_suffix,
    title_similarity,
)

# TVDB aired order for Star Trek: Prodigy season 1, which is the ordering the
# real release is numbered against.
PRODIGY_AIRED_NAMES = [
    "Lost & Found (1)",
    "Lost & Found (2)",
    "Starstruck",
    "Dream Catcher",
    "Terror Firma",
    "Kobayashi",
    "First Con-tact",
    "Time Amok",
]

#: The same season with the two-part premiere collapsed into a single entry,
#: which shifts every later episode down by one. A provider that lists the
#: season this way still has an episode 3, so numbers alone cannot tell the
#: two orderings apart.
PRODIGY_MERGED_NAMES = ["Lost & Found"] + PRODIGY_AIRED_NAMES[2:]


def _episodes(names: list[str]) -> list[dict[str, object]]:
    return [
        {"seasonNumber": 1, "number": index, "name": name}
        for index, name in enumerate(names, start=1)
    ]


def _prodigy_parsed_files() -> list[ParsedFile]:
    """What the release's filenames claim, as the matcher reads them.

    Nineteen files for twenty episodes in the real pack, because the
    two-part premiere ships as one file; the first seven are enough to
    exercise every rule.
    """
    return [
        ParsedFile(season=1, episodes=(1, 2), title="Lost-Found"),
        ParsedFile(season=1, episodes=(3,), title="Starstruck"),
        ParsedFile(season=1, episodes=(4,), title="Dream Catcher"),
        ParsedFile(season=1, episodes=(5,), title="Terror Firma"),
        ParsedFile(season=1, episodes=(6,), title="Kobayashi"),
        ParsedFile(season=1, episodes=(7,), title="First Con-tact"),
        ParsedFile(season=1, episodes=(8,), title="Time Amok"),
    ]


class TestExpandMappingEpisodes:
    def test_a_single_episode_row_claims_one_episode(self) -> None:
        assert expand_mapping_episodes({"episode": 7, "episode_end": None}) == [7]

    def test_a_contiguous_span_claims_every_episode_between_its_ends(self) -> None:
        assert expand_mapping_episodes({"episode": 1, "episode_end": 3}) == [1, 2, 3]

    def test_a_stored_list_wins_over_the_ends(self) -> None:
        """A non-contiguous span is only describable by its list.

        "S01E01E05" carries ``episode_end=5``, and reading that as a range
        claims five episodes for a file that holds two -- over-claiming three
        episodes no file covers, which can block a pack from validating.
        """
        mapping = {"episode": 1, "episode_end": 5, "episode_list": [1, 5]}

        assert expand_mapping_episodes(mapping) == [1, 5]

    def test_a_list_is_sorted_and_deduplicated(self) -> None:
        assert expand_mapping_episodes({"episode": 2, "episode_list": [5, 2, 5]}) == [
            2,
            5,
        ]

    def test_an_end_below_the_start_claims_only_the_start(self) -> None:
        """Reachable by retyping the start of a span.

        Expanding ``range(3, 3)`` yielded nothing, so the row claimed no
        episode at all yet still satisfied the overlap check -- it could
        neither collide with anything nor be reported as missing.
        """
        assert expand_mapping_episodes({"episode": 3, "episode_end": 2}) == [3]

    def test_a_row_with_no_episode_number_claims_nothing(self) -> None:
        assert expand_mapping_episodes({"episode": None}) == []
        assert expand_mapping_episodes({}) == []

    def test_a_boolean_is_not_an_episode_number(self) -> None:
        # bool is an int subclass; letting True through would claim episode 1
        assert expand_mapping_episodes({"episode": True}) == []
        assert expand_mapping_episodes({"episode": 1, "episode_list": [True]}) == [1]


class TestClaimedSeasonEpisodes:
    def test_every_claimed_episode_is_paired_with_its_season(self) -> None:
        mapping = {"season": 2, "episode": 1, "episode_end": 2}

        assert claimed_season_episodes(mapping) == [(2, 1), (2, 2)]

    def test_season_zero_is_carried_through(self) -> None:
        """TVDB files specials as season 0, which is falsy."""
        assert claimed_season_episodes({"season": 0, "episode": 5}) == [(0, 5)]

    def test_a_row_with_no_episode_number_claims_nothing(self) -> None:
        assert claimed_season_episodes({"season": 1, "episode": None}) == []


class TestTitleSimilarity:
    def test_an_exact_title_scores_full_marks(self) -> None:
        assert title_similarity("Starstruck", "Starstruck") == 100

    def test_punctuation_and_case_do_not_matter(self) -> None:
        assert title_similarity("starstruck!", "Starstruck") == 100

    def test_an_ampersand_reads_as_the_word(self) -> None:
        """A provider writes "Lost & Found"; a release writes "Lost.and.Found".

        Dropping the ampersand instead of expanding it left the same title
        spelled two ways scoring as a near miss, which cost a multi-part
        group the tie-break against its own first episode.
        """
        assert title_similarity("lost.and.found", "Lost & Found") == 100

    def test_a_missing_space_is_still_the_same_title(self) -> None:
        assert title_similarity("Dream Catcher", "Dreamcatcher") > 90

    def test_different_titles_score_low(self) -> None:
        assert title_similarity("Starstruck", "Dream Catcher") < 50

    def test_an_absent_side_scores_zero_rather_than_raising(self) -> None:
        assert title_similarity(None, "Starstruck") == 0.0
        assert title_similarity("Starstruck", "") == 0.0


class TestComparableTitle:
    def test_a_provider_placeholder_carries_no_signal(self) -> None:
        assert comparable_title("TBA") is None
        assert comparable_title("Episode 12") is None

    def test_a_very_short_title_carries_no_signal(self) -> None:
        assert comparable_title("ab") is None

    def test_a_real_title_is_normalized(self) -> None:
        assert comparable_title("Lost & Found (1)") == "lost and found 1"


class TestRankEpisodeOrderings:
    def test_the_ordering_the_release_was_numbered_against_wins(self) -> None:
        """The merged ordering is listed first and still loses.

        Both orderings have an episode 3, so the numbers alone cannot choose
        between them -- and picking the merged one renames every file from
        the premiere onward while reporting full confidence.
        """
        by_type = {
            2: {
                "type_name": "DVD Order",
                "type": "dvd",
                "episodes": _episodes(PRODIGY_MERGED_NAMES),
            },
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _episodes(PRODIGY_AIRED_NAMES),
            },
        }

        ranked = rank_episode_orderings(_prodigy_parsed_files(), by_type)

        assert [score.type_name for score in ranked] == ["Aired Order", "DVD Order"]
        assert ranked[0].coverage == 1.0
        assert ranked[0].title_agreement > 95
        assert ranked[1].title_agreement < 60

    def test_a_multi_episode_file_is_counted_once_per_episode(self) -> None:
        """The merged ordering has no episode 2, and that must cost it."""
        score = score_episode_ordering(
            _prodigy_parsed_files(), _episodes(PRODIGY_MERGED_NAMES)
        )

        assert score.claims_total == 8
        assert score.claims_matched == 7

    def test_a_tie_goes_to_the_ordering_already_committed_to(self) -> None:
        identical = _episodes(PRODIGY_AIRED_NAMES)
        by_type = {
            1: {"type_name": "Aired Order", "type": "official", "episodes": identical},
            2: {"type_name": "DVD Order", "type": "dvd", "episodes": list(identical)},
        }

        ranked = rank_episode_orderings(
            _prodigy_parsed_files(), by_type, prefer_type_id=2
        )

        assert ranked[0].type_id == 2

    def test_a_tie_with_nothing_committed_goes_to_aired_order(self) -> None:
        identical = _episodes(PRODIGY_AIRED_NAMES)
        by_type = {
            2: {"type_name": "DVD Order", "type": "dvd", "episodes": identical},
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": list(identical),
            },
        }

        ranked = rank_episode_orderings(_prodigy_parsed_files(), by_type)

        assert ranked[0].api_type == "official"

    def test_a_committed_ordering_id_matches_across_a_json_round_trip(self) -> None:
        """Saved jobs come back with the ordering ids stringified."""
        identical = _episodes(PRODIGY_AIRED_NAMES)
        by_type = {
            "1": {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": identical,
            },
            "2": {"type_name": "DVD Order", "type": "dvd", "episodes": list(identical)},
        }

        ranked = rank_episode_orderings(
            _prodigy_parsed_files(), by_type, prefer_type_id=2
        )

        assert ranked[0].type_id == "2"

    def test_absolute_order_is_excluded_unless_the_release_is_absolute(self) -> None:
        """It flattens a series into one season and can out-cover the truth."""
        by_type = {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _episodes(PRODIGY_AIRED_NAMES),
            },
            3: {
                "type_name": "Absolute Order",
                "type": "absolute",
                "episodes": _episodes(PRODIGY_AIRED_NAMES),
            },
        }
        parsed = _prodigy_parsed_files()

        assert [s.api_type for s in rank_episode_orderings(parsed, by_type)] == [
            "official"
        ]

        allowed = rank_episode_orderings(parsed, by_type, allow_absolute=True)
        assert {score.api_type for score in allowed} == {"official", "absolute"}

    def test_title_agreement_is_ignored_when_too_few_titles_compare(self) -> None:
        """One stray title must not outvote coverage across a whole pack."""
        one_file = [ParsedFile(season=1, episodes=(3,), title="Starstruck")]
        by_type = {
            1: {
                "type_name": "Aired Order",
                "type": "official",
                "episodes": _episodes(PRODIGY_AIRED_NAMES),
            }
        }

        ranked = rank_episode_orderings(one_file, by_type)

        assert ranked[0].has_title_evidence is False
        assert "titles" not in ranked[0].summary()


class TestCheckTitleAgainstEpisode:
    @staticmethod
    def _season(names: list[str]) -> dict[int, dict[str, object]]:
        return {index: {"name": name} for index, name in enumerate(names, start=1)}

    def test_an_agreeing_title_raises_nothing(self) -> None:
        check = check_title_against_episode(
            "Starstruck", self._season(PRODIGY_AIRED_NAMES), 3
        )

        assert check.disagrees is False
        assert check.points_elsewhere is False

    def test_a_shifted_pack_names_the_episode_the_title_belongs_to(self) -> None:
        check = check_title_against_episode(
            "Starstruck", self._season(PRODIGY_MERGED_NAMES), 3
        )

        assert check.points_elsewhere is True
        assert check.suggested_episode == 2

    def test_an_unparseable_filename_is_silence_not_evidence(self) -> None:
        check = check_title_against_episode(None, self._season(PRODIGY_AIRED_NAMES), 3)

        assert check.has_opinion is False
        assert check.disagrees is False

    def test_a_provider_placeholder_is_silence_not_evidence(self) -> None:
        check = check_title_against_episode("Starstruck", {3: {"name": "TBA"}}, 3)

        assert check.has_opinion is False

    def test_ordinary_mangling_is_not_a_disagreement(self) -> None:
        """Between a clean match and a clear mismatch sits normal noise."""
        check = check_title_against_episode(
            "Dreamcatcher", self._season(PRODIGY_AIRED_NAMES), 4
        )

        assert check.disagrees is False


class TestEpisodeText:
    def test_a_single_episode(self) -> None:
        assert episode_spec_text({"season": 1, "episode": 3}) == "3"
        assert episode_designator({"season": 1, "episode": 3}) == "S01E03"

    def test_a_contiguous_span_reads_as_a_range(self) -> None:
        mapping = {"season": 1, "episode": 1, "episode_end": 2}

        assert episode_spec_text(mapping) == "1-2"
        assert episode_designator(mapping) == "S01E01-E02"

    def test_a_non_contiguous_span_is_listed_not_ranged(self) -> None:
        """Writing [1, 5] as a range would claim three episodes it lacks."""
        mapping = {"season": 1, "episode": 1, "episode_list": [1, 5]}

        assert episode_spec_text(mapping) == "1,5"
        assert episode_designator(mapping) == "S01E01,E05"

    def test_an_unresolved_row_renders_empty(self) -> None:
        assert episode_spec_text({"season": 1, "episode": None}) == ""
        assert episode_designator({"season": None, "episode": 3}) == ""


class TestParseEpisodeSpec:
    def test_a_single_number(self) -> None:
        assert parse_episode_spec("3") == [3]

    def test_a_range(self) -> None:
        assert parse_episode_spec("1-2") == [1, 2]

    def test_a_list(self) -> None:
        assert parse_episode_spec("1, 2") == [1, 2]

    def test_a_mixture(self) -> None:
        assert parse_episode_spec("1-2,5") == [1, 2, 5]

    def test_the_form_copied_out_of_a_filename(self) -> None:
        assert parse_episode_spec("E01-E02") == [1, 2]
        assert parse_episode_spec("S01E01-S01E02") == [1, 2]

    def test_an_en_dash_reads_as_a_range(self) -> None:
        """Typed on a Mac, or pasted from a web page."""
        assert parse_episode_spec("1–2") == [1, 2]

    def test_duplicates_collapse_and_order_is_normalized(self) -> None:
        assert parse_episode_spec("5,1,5") == [1, 5]

    def test_an_empty_cell_clears_the_mapping(self) -> None:
        """Distinct from unreadable: this is the user unmapping the row."""
        assert parse_episode_spec("") == []
        assert parse_episode_spec("   ") == []

    def test_a_descending_range_is_rejected(self) -> None:
        assert parse_episode_spec("2-1") is None

    def test_an_absurd_span_is_rejected_rather_than_allocated(self) -> None:
        assert parse_episode_spec("1-9999") is None

    def test_a_half_typed_range_is_unreadable_not_empty(self) -> None:
        """The caller keeps the old value rather than dropping the row."""
        assert parse_episode_spec("1-") is None

    def test_nonsense_is_unreadable(self) -> None:
        assert parse_episode_spec("abc") is None


class TestStripPartSuffix:
    def test_a_bracketed_part_number_is_dropped(self) -> None:
        assert strip_part_suffix("Lost & Found (1)") == "Lost & Found"

    def test_a_named_part_is_dropped(self) -> None:
        assert strip_part_suffix("A Moral Star, Part 2") == "A Moral Star"
        assert strip_part_suffix("A Moral Star Pt. 2") == "A Moral Star"

    def test_a_roman_numeral_part_is_dropped(self) -> None:
        assert strip_part_suffix("The Beginning - Part II") == "The Beginning"

    def test_a_title_that_merely_ends_in_a_number_keeps_it(self) -> None:
        """Otherwise "Apollo 13" becomes "Apollo"."""
        assert strip_part_suffix("Apollo 13") == "Apollo 13"
        assert strip_part_suffix("Supernova 2") == "Supernova 2"

    def test_a_title_with_no_part_marker_is_untouched(self) -> None:
        assert strip_part_suffix("Preludes") == "Preludes"


class TestSharedSpanTitle:
    def test_two_parts_of_one_story_share_their_title(self) -> None:
        assert shared_span_title(["Lost & Found (1)", "Lost & Found (2)"]) == (
            "Lost & Found"
        )

    def test_unrelated_episodes_have_no_shared_title(self) -> None:
        """Naming the file after the first would describe only half of it."""
        assert shared_span_title(["Starstruck", "Dream Catcher"]) is None

    def test_an_unresolved_episode_withholds_the_title(self) -> None:
        """A title covering only part of the file is worse than none."""
        assert shared_span_title(["Lost & Found (1)", None]) is None

    def test_a_placeholder_withholds_the_title(self) -> None:
        assert shared_span_title(["Lost & Found (1)", "TBA"]) is None

    def test_a_single_episode_is_not_a_span(self) -> None:
        assert shared_span_title(["Starstruck"]) is None


class TestMultiPartGroups:
    def test_consecutive_episodes_sharing_a_title_are_one_story(self) -> None:
        season = {
            1: {"name": "Lost & Found (1)"},
            2: {"name": "Lost & Found (2)"},
            3: {"name": "Starstruck"},
        }

        assert multi_part_groups(season) == [("Lost & Found", (1, 2))]

    def test_a_group_needs_a_part_marker_somewhere_in_it(self) -> None:
        """Two episodes that merely share a name are not one story."""
        season = {1: {"name": "Reunion"}, 2: {"name": "Reunion"}}

        assert multi_part_groups(season) == []

    def test_a_group_must_be_consecutive(self) -> None:
        season = {
            1: {"name": "Supernova (1)"},
            2: {"name": "Interlude"},
            3: {"name": "Supernova (2)"},
        }

        assert multi_part_groups(season) == []

    def test_a_placeholder_never_joins_a_group(self) -> None:
        season = {1: {"name": "Finale (1)"}, 2: {"name": "TBA"}}

        assert multi_part_groups(season) == []


class TestRankTitleCandidates:
    @staticmethod
    def _season() -> dict[int, dict[str, object]]:
        return {
            1: {"name": "Lost & Found (1)"},
            2: {"name": "Lost & Found (2)"},
            3: {"name": "Starstruck"},
            9: {"name": "A Moral Star, Part 1"},
            10: {"name": "A Moral Star, Part 2"},
        }

    def test_a_file_named_for_the_whole_story_matches_every_part(self) -> None:
        """This is what fuzzy matching could not do at all.

        Matching only the first half left the second with no file to give it
        and no way to say so.
        """
        best = rank_title_candidates("Lost.and.Found", self._season())[0]

        assert best.episodes == (1, 2)

    def test_a_file_naming_a_part_matches_that_part_alone(self) -> None:
        best = rank_title_candidates("Lost & Found (1)", self._season())[0]

        assert best.episodes == (1,)

    def test_a_bare_trailing_number_reads_as_a_part_of_its_own_story(self) -> None:
        """Releases write "A.Moral.Star.2" with no "part" anywhere.

        Safe because it only resolves against a group whose title the rest
        of the filename already matches, and only within that group's size.
        """
        best = rank_title_candidates("A Moral Star 2", self._season())[0]

        assert best.episodes == (10,)

    def test_a_title_that_merely_ends_in_a_number_is_not_a_part(self) -> None:
        season = {1: {"name": "Apollo 13"}, 2: {"name": "Starstruck"}}

        best = rank_title_candidates("Apollo 13", season)[0]

        assert best.episodes == (1,)

    def test_a_part_hint_resolves_a_number_the_title_does_not_carry(self) -> None:
        """GuessIt reads "A.Moral.Star.1" as episode 1 with no season.

        That 1 is the part, and the title candidate it leaves behind has no
        part marker left in it to resolve.
        """
        best = rank_title_candidates("A Moral Star", self._season(), part_hint=2)[0]

        assert best.episodes == (10,)

    def test_a_part_hint_outside_the_group_is_ignored(self) -> None:
        best = rank_title_candidates("Lost and Found", self._season(), part_hint=7)[0]

        assert best.episodes == (1, 2)

    def test_episodes_another_file_holds_are_never_offered(self) -> None:
        ranked = rank_title_candidates("Starstruck", self._season(), exclude={3})

        assert all(candidate.episodes != (3,) for candidate in ranked)

    def test_a_group_is_dropped_when_any_of_its_parts_is_taken(self) -> None:
        """Half a story is not the story, so the remaining part stands alone."""
        ranked = rank_title_candidates("Lost and Found", self._season(), exclude={2})

        assert ranked[0].episodes == (1,)
        assert all(2 not in candidate.episodes for candidate in ranked)

    def test_nothing_comparable_ranks_nothing(self) -> None:
        assert rank_title_candidates(None, self._season()) == []
        assert rank_title_candidates("ab", self._season()) == []


class TestResolvePartReference:
    def test_a_bracketed_part(self) -> None:
        assert resolve_part_reference("Supernova (2)", "Supernova", (19, 20)) == 20

    def test_a_named_part(self) -> None:
        assert resolve_part_reference("Supernova Part 1", "Supernova", (19, 20)) == 19

    def test_a_roman_numeral_part(self) -> None:
        assert resolve_part_reference("Supernova II", "Supernova", (19, 20)) == 20

    def test_the_whole_story_names_no_part(self) -> None:
        assert resolve_part_reference("Supernova", "Supernova", (19, 20)) is None

    def test_a_number_beyond_the_group_names_no_part(self) -> None:
        """ "Apollo 13" has nowhere to resolve to."""
        assert resolve_part_reference("Apollo 13", "Apollo", (1, 2)) is None

    def test_extra_words_make_it_unresolvable(self) -> None:
        assert (
            resolve_part_reference("Supernova 2 Redux", "Supernova", (19, 20)) is None
        )
