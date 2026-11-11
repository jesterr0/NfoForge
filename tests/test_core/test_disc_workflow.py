"""A disc through the run: asked about, renamed by its folder, saved in a job."""

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from nfoforge.backend.rename_files import RenameExecutor
from nfoforge.cli.console import TerminalPrompter
from nfoforge.core.disc import (
    Disc,
    choose_playlist,
    detect_disc,
    disc_from_dict,
    disc_to_dict,
    needs_playlist_choice,
    parse_bdinfo_report,
    preferred_playlist,
)
from nfoforge.core.rename.movie import disc_rename_plan, movie_rename_map
from nfoforge.core.workflow.decisions import DECLINED, Decision, DecisionKind
from nfoforge.core.workflow.steps import Run, WorkflowError, _settle_playlist
from nfoforge.payloads.media_inputs import MediaInputPayload
from tests.disc_helpers import make_bluray, make_dvd

FEATURE = [("00001", 0, 7200)]
REAL_REPORT = (
    Path(__file__).parents[1]
    / "fixtures"
    / "bdinfo"
    / "bdinfo_rs_5.0.0_bluray_avc_lpcm.txt"
).read_text(encoding="utf-8")


def _two_cuts(root: Path) -> Disc:
    make_bluray(
        root,
        {"00800": FEATURE, "00801": [("00002", 0, 7500)]},
        {"00001": 4900, "00002": 5000},
    )
    disc = detect_disc(root)
    assert disc is not None
    return disc


def _run(answer: Any, asked: list[Decision]) -> Run:
    def decide(decision: Decision) -> Any:
        asked.append(decision)
        return answer

    return cast(Run, SimpleNamespace(decide=decide))


# --------------------------------------------------------------------------
# which playlist
# --------------------------------------------------------------------------
def test_only_a_bluray_with_several_candidates_needs_a_choice(tmp_path: Path) -> None:
    cuts = _two_cuts(tmp_path / "cuts")
    assert needs_playlist_choice(cuts)
    # the suggestion is the larger cut, whichever is listed first
    preferred = preferred_playlist(cuts)
    assert preferred is not None and preferred.playlist_id == "00801"

    episodes = detect_disc(
        make_dvd(tmp_path / "dvd", {"01": [1, 800], "02": [1, 810]}),
        lambda _: 1440.0,
    )
    assert episodes is not None and len(episodes.main_playlists()) == 2
    assert not needs_playlist_choice(episodes)


def test_an_ambiguous_disc_is_asked_about_and_the_answer_selected(
    tmp_path: Path,
) -> None:
    disc = _two_cuts(tmp_path / "disc")
    asked: list[Decision] = []

    clip = _settle_playlist(_run("800", asked), disc)

    assert clip == disc.root / "BDMV" / "STREAM" / "00001.m2ts"
    assert disc.selected == ["00800"]
    (decision,) = asked
    assert decision.kind is DecisionKind.PLAYLIST
    assert decision.options == ("00800", "00801")
    assert decision.default == "00801"
    assert "2:05:00" in decision.context["00801"]
    assert "--playlist" in decision.hint


def test_an_unambiguous_disc_is_not_asked_about(tmp_path: Path) -> None:
    disc = detect_disc(make_bluray(tmp_path / "disc", {"00800": FEATURE}, {"00001": 9}))
    assert disc is not None
    asked: list[Decision] = []

    _settle_playlist(_run(None, asked), disc)

    assert asked == [] and disc.selected == ["00800"]


def test_an_answer_that_is_not_a_playlist_stops_the_run(tmp_path: Path) -> None:
    disc = _two_cuts(tmp_path / "disc")
    with pytest.raises(WorkflowError, match="not a playlist"):
        _settle_playlist(_run("00999", []), disc)


def test_the_terminal_offers_the_playlists_as_a_numbered_choice() -> None:
    decision = Decision(
        DecisionKind.PLAYLIST,
        "Which?",
        options=("00800", "00801"),
        default="00801",
        context={"00800": "00800  2:00:00", "00801": "00801  2:05:00"},
    )

    def ask(typed: str) -> tuple[Any, str]:
        out = io.StringIO()
        return TerminalPrompter(io.StringIO(typed), out)(decision), out.getvalue()

    answer, shown = ask("1\n")
    assert answer == "00800"
    assert "00801  2:05:00" in shown
    assert ask("\n")[0] == "00801"
    assert ask("q\n")[0] is DECLINED


# --------------------------------------------------------------------------
# renaming the root folder
# --------------------------------------------------------------------------
def _payload(disc: Disc) -> MediaInputPayload:
    choose_playlist(disc)
    primary = disc.primary_media_file()
    assert primary is not None
    return MediaInputPayload(
        input_path=disc.root,
        file_list=[primary],
        file_list_mediainfo={primary: cast(Any, object())},
        input_kind="directory",
        content_size=disc.size,
        discs=[disc],
    )


def test_only_a_disc_has_a_folder_rename(tmp_path: Path) -> None:
    disc = detect_disc(make_bluray(tmp_path / "old", {"00800": FEATURE}, {"00001": 9}))
    assert disc is not None
    payload = _payload(disc)

    plan = disc_rename_plan(payload, "New.Name")
    assert plan is not None
    assert plan.file_targets == {}
    assert plan.directory_targets == {tmp_path / "old": tmp_path / "New.Name"}
    assert disc_rename_plan(payload, "old") is None
    assert disc_rename_plan(payload, "") is None

    media = tmp_path / "Movie.mkv"
    assert disc_rename_plan(MediaInputPayload(media, file_list=[media]), "New") is None


def test_renaming_the_folder_moves_every_path_the_disc_holds(tmp_path: Path) -> None:
    disc = detect_disc(make_bluray(tmp_path / "old", {"00800": FEATURE}, {"00001": 9}))
    assert disc is not None
    payload = _payload(disc)
    old_clip = payload.file_list[0]
    new_root = tmp_path / "Movie.2020.1080p.Blu-ray.AVC-GRP"

    assert movie_rename_map(payload, new_root.name) == {}
    plan = disc_rename_plan(payload, new_root.name)
    assert plan is not None
    result = RenameExecutor.execute(plan)
    assert result.success, result.message
    payload.apply_rename_mapping(result.path_mapping, result.updated_input_path)

    new_clip = new_root / "BDMV" / "STREAM" / "00001.m2ts"
    assert not (tmp_path / "old").exists()
    # nothing inside the disc changed its name
    assert new_clip.is_file()
    assert payload.input_path == new_root
    assert payload.file_list == [new_clip]
    assert old_clip not in payload.file_list_mediainfo
    assert disc.root == new_root
    assert disc.primary_media_file() == new_clip
    assert disc.playlists[0].path == new_root / "BDMV" / "PLAYLIST" / "00800.mpls"
    payload.require_existing_media_paths(include_comparison=False)


# --------------------------------------------------------------------------
# saved jobs
# --------------------------------------------------------------------------
def test_a_bluray_survives_a_saved_job_with_its_report(tmp_path: Path) -> None:
    disc = _two_cuts(tmp_path / "disc")
    disc.select("00801")
    disc.bdinfo = parse_bdinfo_report(REAL_REPORT)

    restored = disc_from_dict(disc_to_dict(disc))

    assert restored is not None
    # the report is re-read from its text, so compare it apart from the rest
    assert restored.bdinfo == disc.bdinfo
    assert restored.bdinfo is not None and restored.bdinfo.video
    assert restored == disc
    assert restored.primary_media_file() == disc.primary_media_file()


def test_a_dvd_survives_a_saved_job_with_its_reports(tmp_path: Path) -> None:
    disc = detect_disc(make_dvd(tmp_path / "dvd", {"01": [1, 100]}))
    assert disc is not None
    choose_playlist(disc)
    disc.ifo_mediainfo, disc.vob_mediainfo = "ifo text", "vob text"

    assert disc_from_dict(disc_to_dict(disc)) == disc


@pytest.mark.parametrize(
    "document", [None, "disc", {}, {"root": "x", "disc_type": "hddvd"}]
)
def test_anything_else_is_not_a_disc(document: Any) -> None:
    assert disc_from_dict(document) is None


# --------------------------------------------------------------------------
# what the search is for
# --------------------------------------------------------------------------
@pytest.mark.parametrize("nested", [False, True])
def test_a_disc_is_searched_for_by_its_folder_not_its_clips(
    tmp_path: Path, nested: bool
) -> None:
    from nfoforge.backend.utils.title_inference import MediaTitleInferer

    folder = tmp_path / "Men at Work 1990 1080p Blu-ray AVC LPCM 2.0-Liber8"
    make_bluray(
        folder / "DISC1" if nested else folder, {"00800": FEATURE}, {"00004": 9}
    )
    clip = next(folder.rglob("00004.m2ts"))

    result = MediaTitleInferer().infer(folder, video_files=(clip,))

    assert result.title == "Men at Work 1990"
    assert all("00004" not in title for title, _score in result.candidates)
