from pathlib import Path
import stat
import sys
from typing import Any

import pytest

from nfoforge.core.disc import (
    MISSING_BDINFO,
    BDInfoError,
    BDInfoReportError,
    BdinfoRsScanner,
    Disc,
    cached_bdinfo_report,
    choose_playlist,
    describe_disc,
    detect_disc,
    parse_bdinfo_report,
)
from tests.disc_helpers import make_bluray, make_dvd

FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures"
    / "bdinfo"
    / "bdinfo_rs_5.0.0_bluray_avc_lpcm.txt"
)
REAL_REPORT = FIXTURE.read_text(encoding="utf-8")

UHD_SUMMARY = """\
QUICK SUMMARY:

Disc Label:     MOVIE_UHD
Disc Size:      61,234,567,890 bytes
Protection:     AACS2
Playlist:       00800.MPLS
Size:           58,000,000,000 bytes
Length:         2:01:05.300
Total Bitrate:  63.85 Mbps
Video:          MPEG-H HEVC Video / 51,234 kbps / 2160p / 23.976 fps / 16:9 / Main 10 @ Level 5.1 @ High / 10 bits / HDR10 / BT.2020
* Video:        MPEG-H HEVC Video / 3,012 kbps / 1080p / 23.976 fps / 16:9 / Main 10 @ Level 5.1 @ High / 10 bits / Dolby Vision / BT.2020
Audio:          English / Dolby TrueHD/Atmos Audio / 7.1 / 48 kHz /  4,512 kbps / 24-bit (AC3 Embedded: 5.1 / 48 kHz /   640 kbps / DN -27dB)
Audio:          French / DTS-HD Master Audio / 5.1 / 48 kHz /  2,301 kbps / 16-bit (DTS Core: 5.1 / 48 kHz /   768 kbps / 16-bit)
Subtitle:       English / 34.21 kbps
"""


def test_real_bdinfo_rs_report_is_parsed() -> None:
    report = parse_bdinfo_report(REAL_REPORT)

    assert report.full == REAL_REPORT
    assert report.quick_summary.startswith("Disc Label:")
    assert report.quick_summary.endswith("Subtitle:       French / 13.90 kbps")
    assert report.disc_size == 24_648_859_320
    assert report.playlist == "00004.MPLS"
    assert report.size == 23_541_837_120
    assert report.length == "01:38:42.499"
    assert report.duration_seconds == pytest.approx(5922.499)
    assert report.total_bitrate == "31.80 Mbps"

    (video,) = report.video
    assert video.codec == "MPEG-4 AVC Video"
    assert video.bitrate_kbps == 28000
    assert video.resolution == "1080p"
    assert video.frame_rate == "23.976 fps"
    assert video.aspect_ratio == "16:9"
    assert video.hdr == ()
    assert not video.is_3d

    (audio,) = report.audio
    assert audio.language == "English"
    assert audio.codec == "LPCM Audio"
    assert audio.channels == "2.0"
    assert audio.bitrate_kbps == 2304
    assert not audio.is_atmos

    assert [s.language for s in report.subtitles] == ["English", "Spanish", "French"]


def test_uhd_summary_reads_hdr_and_atmos_whatever_the_field_order() -> None:
    report = parse_bdinfo_report(UHD_SUMMARY)

    # the Dolby Vision layer is a hidden stream, flagged with a leading "*"
    (video,) = report.video
    assert video.resolution == "2160p"
    assert video.hdr == ("HDR10",)
    assert video.bitrate_kbps == 51234

    atmos, dts = report.audio
    assert atmos.codec == "Dolby TrueHD/Atmos Audio"
    assert atmos.is_atmos
    assert atmos.channels == "7.1"
    assert atmos.bitrate_kbps == 4512
    assert dts.language == "French"
    assert dts.channels == "5.1"
    assert not dts.is_atmos


def test_only_the_first_playlist_of_a_multi_playlist_report_is_read() -> None:
    second = UHD_SUMMARY.replace("00800", "00801")
    banner = "\n********************\nPLAYLIST: 00801.MPLS\n********************\n\n"
    report = parse_bdinfo_report(UHD_SUMMARY + banner + second)
    assert report.playlist == "00800.MPLS"
    assert len(report.audio) == 2


@pytest.mark.parametrize("text", ["", "not a report", "QUICK SUMMARY:\n\n"])
def test_text_without_a_summary_is_not_a_report(text: str) -> None:
    with pytest.raises(BDInfoReportError):
        parse_bdinfo_report(text)


# --------------------------------------------------------------------------
# the scanner, against a stand-in executable
# --------------------------------------------------------------------------
def _fake_scanner(folder: Path, body: str) -> Path:
    """An executable that runs `body` as Python, with the scanner's argv."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "fake_bdinfo.py"
    script.write_text(body, encoding="utf-8")
    if sys.platform == "win32":
        launcher = folder / "bdinfo-rs.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = folder / "bdinfo-rs"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
        )
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return launcher


_WRITES_REPORT = "\n".join(
    [
        "import sys",
        "from pathlib import Path",
        "args = sys.argv[1:]",
        "assert args[0] == '--mpls' and args[2] == '--no-banner', args",
        "disc, dest = Path(args[3]), Path(args[4])",
        "for percent in (0, 50, 100):",
        "    sys.stderr.write(f'Scanning {percent:3d}% - 00001.M2TS | Elapsed\\r')",
        f"report = Path({str(FIXTURE)!r}).read_text(encoding='utf-8')",
        "report = report.replace('00004.MPLS', args[1].upper() + '.MPLS')",
        "(dest / f'BDINFO.{disc.name}.txt').write_text(report, encoding='utf-8')",
        "",
    ]
)


def _bluray(tmp_path: Path) -> Disc:
    root = make_bluray(
        tmp_path / "Movie.2020.BluRay", {"00800": [("00001", 0, 7200)]}, {"00001": 9}
    )
    disc = detect_disc(root)
    assert disc is not None
    choose_playlist(disc)
    return disc


def test_scan_writes_outside_the_disc_and_reports_progress(tmp_path: Path) -> None:
    disc = _bluray(tmp_path)
    before = sorted(p.name for p in disc.root.rglob("*"))
    scanner = BdinfoRsScanner(_fake_scanner(tmp_path / "bin", _WRITES_REPORT))
    seen: list[float] = []

    report = scanner.scan(disc, "00800", tmp_path / "reports", seen.append)

    assert report.playlist == "00800.MPLS"
    assert seen and seen[-1] == 100.0
    assert sorted(p.name for p in disc.root.rglob("*")) == before
    assert [p.name for p in (tmp_path / "reports").iterdir()] == [
        "BDINFO.Movie.2020.BluRay.txt"
    ]


def test_describe_disc_scans_once_then_reuses_the_report(tmp_path: Path) -> None:
    disc = _bluray(tmp_path)
    executable = _fake_scanner(tmp_path / "bin", _WRITES_REPORT)
    reports = tmp_path / "reports"

    describe_disc(disc, executable, reports)
    assert disc.bdinfo is not None and disc.bdinfo.playlist == "00800.MPLS"
    assert cached_bdinfo_report(reports, "800") is not None
    assert cached_bdinfo_report(reports, "00801") is None

    # no scanner at all the second time: the report on disk is enough
    disc.bdinfo = None
    describe_disc(disc, None, reports)
    assert disc.bdinfo is not None


def test_bluray_without_a_bdinfo_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BDInfoError) as caught:
        describe_disc(_bluray(tmp_path), None, tmp_path / "reports")
    assert str(caught.value) == MISSING_BDINFO


def test_a_failed_scan_reports_the_reason_the_scanner_gave(tmp_path: Path) -> None:
    body = "\n".join(
        [
            "import sys",
            "sys.stderr.write('Scanning   3% - x\\r')",
            "sys.stderr.write('error: No matching playlists found on BD\\n')",
            "sys.exit(1)",
        ]
    )
    scanner = BdinfoRsScanner(_fake_scanner(tmp_path / "bin", body))
    with pytest.raises(BDInfoError, match=r"\(1\): No matching playlists found"):
        scanner.scan(_bluray(tmp_path), "00800", tmp_path / "reports")


def test_a_scan_that_writes_nothing_is_an_error(tmp_path: Path) -> None:
    scanner = BdinfoRsScanner(_fake_scanner(tmp_path / "bin", "pass\n"))
    with pytest.raises(BDInfoError, match="wrote no report"):
        scanner.scan(_bluray(tmp_path), "00800", tmp_path / "reports")


def test_a_stuck_scan_is_stopped(tmp_path: Path) -> None:
    scanner = BdinfoRsScanner(
        _fake_scanner(tmp_path / "bin", "import time\ntime.sleep(60)\n"), timeout=1
    )
    with pytest.raises(BDInfoError, match="did not finish"):
        scanner.scan(_bluray(tmp_path), "00800", tmp_path / "reports")


def test_missing_executable_is_an_error(tmp_path: Path) -> None:
    scanner = BdinfoRsScanner(tmp_path / "nowhere" / "bdinfo-rs")
    with pytest.raises(BDInfoError, match="not found"):
        scanner.scan(_bluray(tmp_path), "00800", tmp_path / "reports")


def test_dvd_needs_no_scanner(tmp_path: Path) -> None:
    root = make_dvd(tmp_path / "Movie.DVD", {"01": [1, 100]})
    disc = detect_disc(root, lambda _: None)
    assert disc is not None
    choose_playlist(disc)

    describe_disc(disc, None, tmp_path / "reports")

    # the stub files are not real MPEG, so MediaInfo has little to say, but
    # whatever it says names the file and not the folder it sits in
    assert disc.bdinfo is None
    for text in (disc.ifo_mediainfo, disc.vob_mediainfo):
        assert str(tmp_path) not in text


def test_the_scan_opens_no_console_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    import nfoforge.core.disc.bdinfo as bdinfo_module

    real_popen = subprocess.Popen
    seen: dict[str, object] = {}

    def popen(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        # the flag's value is the helper's business; it only has to arrive
        return real_popen(*args, **{**kwargs, "creationflags": 0})

    monkeypatch.setattr(bdinfo_module, "get_subprocess_creation_flags", lambda: 1234)
    monkeypatch.setattr(bdinfo_module.subprocess, "Popen", popen)
    scanner = BdinfoRsScanner(_fake_scanner(tmp_path / "bin", _WRITES_REPORT))
    scanner.scan(_bluray(tmp_path), "00800", tmp_path / "reports")

    assert seen["creationflags"] == 1234
