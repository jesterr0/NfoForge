"""Filling a request from a preset, and naming an image host."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nfoforge.config.presets import RunPreset
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.trackers.image_hosts import default_image_hosts, find_image_host
from nfoforge.core.workflow.presets import PresetError, build_request, find_preset
from nfoforge.enums.automation import AutomationMode
from nfoforge.enums.image_host import ImageHost, ImageSource
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.packages.custom_types import DISABLED_HOST, ImageHostRef

PRESET = RunPreset(
    trackers=("BHD",),
    image_host="Pixhost",
    screenshot_count=6,
    mode=AutomationMode.UNATTENDED,
    token_overrides={"edition": "Directors Cut", "hybrid": "HYBRID"},
)


def test_a_preset_fills_what_the_run_left_open() -> None:
    request = build_request({"path": Path("x")}, PRESET, preset_name="bhd")

    assert request.trackers == ("BHD",)
    assert request.image_host == "Pixhost"
    assert request.screenshot_count == 6
    assert request.mode is AutomationMode.UNATTENDED
    assert request.preset == "bhd"


def test_what_the_run_was_given_wins() -> None:
    request = build_request(
        {
            "path": Path("x"),
            "trackers": ("AITHER",),
            "screenshot_count": None,  # not given: the preset fills it
            "token_overrides": {"edition": "Extended"},
        },
        PRESET,
    )

    assert request.trackers == ("AITHER",)
    assert request.screenshot_count == 6
    assert request.token_overrides == {"edition": "Extended", "hybrid": "HYBRID"}


def test_without_a_preset_the_profile_decides() -> None:
    request = build_request({"path": Path("x")})

    assert request.image_host is None
    assert request.mode is AutomationMode.INTERACTIVE


def test_an_unknown_preset_lists_the_known_ones() -> None:
    settings: Any = SimpleNamespace(presets={"bhd": PRESET, "quick": RunPreset()})

    assert find_preset(settings, "bhd") is PRESET
    with pytest.raises(PresetError, match="bhd, quick"):
        find_preset(settings, "nope")


# --------------------------------------------------------------------------
# image hosts by name
# --------------------------------------------------------------------------
PIXHOST = ImageHostRef(ImageHost.PIXHOST)
CHEV_A = ImageHostRef(ImageHost.CHEVERETO_V4, "a", label="My Site")
CHEV_B = ImageHostRef(ImageHost.CHEVERETO_V4, "b", label="Other Site")


@pytest.mark.parametrize("name", ["Pixhost", "pixhost", "PIXHOST"])
def test_a_host_is_found_by_any_of_its_names(name: str) -> None:
    assert find_image_host(name, [PIXHOST, CHEV_A]) == PIXHOST


def test_one_of_several_instances_is_found_by_label_or_key() -> None:
    assert find_image_host("my site", [CHEV_A, CHEV_B]) == CHEV_A
    assert find_image_host("CHEVERETO_V4:b", [CHEV_A, CHEV_B]) == CHEV_B
    with pytest.raises(ValueError, match="several"):
        find_image_host("Chevereto v4", [CHEV_A, CHEV_B])


def test_an_unavailable_host_is_refused_and_disabled_always_works() -> None:
    with pytest.raises(ValueError, match="not available"):
        find_image_host("ImageBox", [PIXHOST])
    assert find_image_host("Disabled", []) == DISABLED_HOST


def test_a_named_host_is_every_trackers_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nfoforge.core.trackers.image_hosts.available_image_hosts",
        lambda *_a: {PIXHOST},
    )
    context = ProcessingContext()
    context.shared_data.loaded_images = [Path("shot.png")]
    trackers = [TrackerSelection.AITHER, TrackerSelection.HUNO]

    hosts, notes = default_image_hosts(
        context, SimpleNamespace(), SimpleNamespace(), trackers, preferred="pixhost"
    )

    assert {host.img_to for host in hosts.values()} == {PIXHOST}
    assert all(host.img_from is ImageSource.IMAGES for host in hosts.values())
    assert notes == []
