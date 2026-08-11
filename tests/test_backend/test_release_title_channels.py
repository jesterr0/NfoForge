"""Regression coverage for audio channel layouts in tracker release titles.

Every tracker that ships a space-separated title converts the dot-separated
form by replacing periods with spaces -- which destroys the audio channel
layout (``5.1`` -> ``5 1``) along with the separators. UNIT3D used to put the
periods back with a lookup table built from 11 hard-coded codecs x 11
hard-coded layouts, so the layout only survived when it was immediately
preceded by one of those exact codec strings. Everything outside that grid
silently uploaded as ``5 1`` / ``2 0``:

* codecs the table never listed -- AAC, Opus, LPCM, MP2, MP3, Vorbis,
  ``DTS 96-24``, and ``DTS-X`` (the table held ``DTS:X``, which the audio
  conventions never emit),
* an Atmos suffix sitting between the codec and the channels, which every
  tracker using a ``{audio_codec} {audio_channel_s}`` title token produces,
* the layouts ``6.0``, ``7.0`` and ``8.0``, which the table simply omitted.

TorrentLeech and HDBits had no restore step at all and lost every layout.
``strip_title_dots`` now protects the layout by shape before the periods are
stripped, so these tests lock in the full codec x layout grid.
"""

from collections.abc import Callable

import pytest

from src.backend.trackers.hdb import HDBUploader
from src.backend.trackers.torrentleech import TLUploader
from src.backend.trackers.unit3d_base import Unit3dBaseUploader
from src.backend.trackers.utils import strip_title_dots

# every codec runtime/config/audio_conventions/default.json can emit
CODECS = (
    "AAC",
    "DD",
    "DD-EX",
    "DD+",
    "DDP",
    "DDP Atmos",
    "TrueHD",
    "TrueHD Atmos",
    "DTS",
    "DTS-ES",
    "DTS-HD MA",
    "DTS-HD HRA",
    "DTS-X",
    "DTS 96-24",
    "FLAC",
    "MP2",
    "MP3",
    "Opus",
    "LPCM",
    "Vorbis",
)

# every layout ParseAudioChannels.get_channel_layout can produce (AudioChannels
# allows 1-8 channels, minus one when LFE is present), plus an Atmos-style
# height group
LAYOUTS = (
    "1.0",
    "2.0",
    "2.1",
    "3.0",
    "3.1",
    "4.0",
    "4.1",
    "5.0",
    "5.1",
    "6.0",
    "6.1",
    "7.0",
    "7.1",
    "8.0",
    "8.1",
    "7.1.4",
)

GENERATORS: tuple[Callable[[str], str], ...] = (
    Unit3dBaseUploader.generate_release_title,
    TLUploader.generate_release_title,
    HDBUploader.generate_release_title,
)


@pytest.mark.parametrize("codec", CODECS)
@pytest.mark.parametrize("layout", LAYOUTS)
def test_unit3d_keeps_every_codec_and_layout(codec: str, layout: str) -> None:
    title = f"Example Movie 2026 1080p BluRay {codec} {layout} AVC-GRP"

    assert f"{codec} {layout} " in Unit3dBaseUploader.generate_release_title(title)


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("generate", GENERATORS)
def test_every_tracker_keeps_layout_from_a_dotted_filename(
    generate: Callable[[str], str], layout: str
) -> None:
    stem = f"Example.Movie.2026.1080p.BluRay.AAC.{layout}.x264-GRP"

    assert f"AAC {layout} " in generate(stem)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # separator periods still become spaces
        (
            "Example.Movie.2026.1080p.BluRay.DTS-HD.MA.5.1.x264-GRP",
            "Example Movie 2026 1080p BluRay DTS-HD MA 5.1 x264-GRP",
        ),
        # a year/resolution boundary is not a layout
        (
            "Example.Movie.2019.1080p.WEB-DL.DDP.2.0.H.264-GRP",
            "Example Movie 2019 1080p WEB-DL DDP 2.0 H 264-GRP",
        ),
        # an Atmos suffix between codec and channels was the common failure
        (
            "Example Movie 2026 1080p WEB-DL DDP Atmos 5.1 H.264-GRP",
            "Example Movie 2026 1080p WEB-DL DDP Atmos 5.1 H 264-GRP",
        ),
        # a bare part number followed by a resolution is not a layout
        (
            "Example.Movie.Part.2.1080p.WEB-DL.AAC.2.0.x264-GRP",
            "Example Movie Part 2 1080p WEB-DL AAC 2.0 x264-GRP",
        ),
        # a real decimal is not a layout -- .5 is not an LFE digit
        (
            "Nine.9.5.Weeks.2026.1080p.BluRay.DDP.2.0.x264-GRP",
            "Nine 9 5 Weeks 2026 1080p BluRay DDP 2.0 x264-GRP",
        ),
        # hyphenated digits are untouched
        (
            "9-1-1 S01E01 Pilot 1080p WEB-DL AAC 2.0 H.264-GRP",
            "9-1-1 S01E01 Pilot 1080p WEB-DL AAC 2.0 H 264-GRP",
        ),
        # repeated whitespace is still collapsed
        ("Example  Movie   2026 1080p AAC 2.0", "Example Movie 2026 1080p AAC 2.0"),
    ],
)
def test_strip_title_dots(title: str, expected: str) -> None:
    assert strip_title_dots(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Example.Movie.2026.1080p.BluRay.DTS-HD.MA.5.1.x264-GRP",
        "Example Movie 2026 1080p WEB-DL DDP Atmos 5.1 H.264-GRP",
        "Example Movie 2026 2160p UHD BluRay TrueHD Atmos 7.1.4 HEVC-GRP",
    ],
)
@pytest.mark.parametrize("generate", GENERATORS)
def test_generate_release_title_is_idempotent(
    generate: Callable[[str], str], title: str
) -> None:
    once = generate(title)

    assert generate(once) == once
