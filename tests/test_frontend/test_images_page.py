from pathlib import Path

import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.cropping import Cropping
from src.enums.media_type import MediaType
from src.enums.screen_shot_mode import ScreenShotMode
from src.frontend.wizards.images import ImagesPage
from src.packages.custom_types import ComparisonPair
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.script import ScriptValues

VPY_WITH_CROP = (
    "clip = core.lsmas.LWLibavSource(source)\n"
    "clip = core.std.Crop(clip, left=0, right=0, top=138, bottom=138)\n"
)
VPY_WITHOUT_CROP = "clip = core.lsmas.LWLibavSource(source)\n"


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = Path("runtime/config/defaults")
    default_config = defaults / "default_config.toml"
    default_program = defaults / "default_program_conf.toml"
    default_config.write_text(
        (source_defaults / "default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    default_program.write_text(
        (source_defaults / "default_program_conf.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ConfigPaths(
        default_config=default_config,
        default_program=default_program,
        program=tmp_path / "program/conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )


class _DialogSpy:
    """Stands in for CropWidgetDialog so tests can assert on prompting."""

    instances: list["_DialogSpy"] = []
    result: ScriptValues | None = None

    def __init__(self, parent: object = None) -> None:
        self.loaded_script: Path | None = None
        _DialogSpy.instances.append(self)

    def load_script(self, script_path: Path) -> None:
        self.loaded_script = script_path

    def exec_crop(self) -> ScriptValues | None:
        return _DialogSpy.result


def _make_images_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crop_mode: Cropping,
    ss_mode: ScreenShotMode = ScreenShotMode.ADV_SS_COMP,
    script: Path | None = None,
    comparison: bool = True,
) -> tuple[ImagesPage, list[ScriptValues | None]]:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )

    manager = ConfigManager("test", _paths(tmp_path))
    manager.settings.screenshots.mode = ss_mode
    manager.settings.screenshots.crop_mode = crop_mode

    encode = tmp_path / "Movie.2020.1080p.BluRay.x264-GRP.mkv"
    source = tmp_path / "Movie.2020.1080p.remux.mkv"

    media_input = MediaInputPayload(
        input_path=encode,
        media_type=MediaType.MOVIE,
        file_list=[encode],
        comparison_pair=(
            ComparisonPair(source=source, media=encode, script=script)
            if comparison
            else None
        ),
    )
    context = ProcessingContext(
        media_input=media_input,
        media_search=MediaSearchPayload(media_type=MediaType.MOVIE, title="Movie"),
    )

    page = ImagesPage(config=manager, context=context, parent=None)  # type: ignore[arg-type]

    # the source and encode differ in resolution, which is what puts the crop
    # logic in play at all
    monkeypatch.setattr(ImagesPage, "_compare_resolutions", lambda self: False)

    generated: list[ScriptValues | None] = []
    monkeypatch.setattr(
        ImagesPage,
        "_execute_image_generation",
        lambda self, script_values=None, re_sync=0: generated.append(script_values),
    )

    _DialogSpy.instances = []
    _DialogSpy.result = None
    monkeypatch.setattr("src.frontend.wizards.images.CropWidgetDialog", _DialogSpy)

    return page, generated


def test_manual_crop_with_script_applies_values_without_prompting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: with a comparison script supplying crop values, manual
    crop mode opened the crop dialog pre-filled with the script instead of
    applying it, so a flow that used to need one click on Generate now needed
    the user to confirm the dialog too."""
    script = tmp_path / "compare.vpy"
    script.write_text(VPY_WITH_CROP, encoding="utf-8")
    page, generated = _make_images_page(
        tmp_path, monkeypatch, Cropping.MANUAL, script=script
    )

    page._generate_images()

    assert not _DialogSpy.instances, "crop dialog must not be shown"
    assert len(generated) == 1
    script_values = generated[0]
    assert script_values
    assert script_values.crop_values
    assert script_values.crop_values.top == 138
    assert script_values.crop_values.bottom == 138


def test_auto_crop_with_script_still_applies_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "compare.vpy"
    script.write_text(VPY_WITH_CROP, encoding="utf-8")
    page, generated = _make_images_page(
        tmp_path, monkeypatch, Cropping.AUTO, script=script
    )

    page._generate_images()

    assert not _DialogSpy.instances
    assert len(generated) == 1
    assert generated[0]
    assert generated[0].crop_values


def test_manual_crop_without_script_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, generated = _make_images_page(
        tmp_path, monkeypatch, Cropping.MANUAL, script=None
    )
    _DialogSpy.result = ScriptValues()

    page._generate_images()

    assert len(_DialogSpy.instances) == 1
    assert _DialogSpy.instances[0].loaded_script is None
    assert generated == [ScriptValues()]


def test_manual_crop_with_script_lacking_crop_values_prompts_prefilled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A script carrying no crop values can't drive the crop, so manual mode
    still prompts, with the script pre-loaded for the user to work from."""
    script = tmp_path / "compare.vpy"
    script.write_text(VPY_WITHOUT_CROP, encoding="utf-8")
    page, generated = _make_images_page(
        tmp_path, monkeypatch, Cropping.MANUAL, script=script
    )
    _DialogSpy.result = ScriptValues()

    page._generate_images()

    assert len(_DialogSpy.instances) == 1
    assert _DialogSpy.instances[0].loaded_script == script
    assert generated == [ScriptValues()]


def test_manual_crop_cancelled_dialog_falls_back_to_plain_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, generated = _make_images_page(
        tmp_path, monkeypatch, Cropping.MANUAL, script=None
    )
    _DialogSpy.result = None

    page._generate_images()

    assert len(_DialogSpy.instances) == 1
    assert generated == [None]


def test_disabled_crop_ignores_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crop disabled means disabled, even when a script carries crop values."""
    script = tmp_path / "compare.vpy"
    script.write_text(VPY_WITH_CROP, encoding="utf-8")
    page, generated = _make_images_page(
        tmp_path, monkeypatch, Cropping.DISABLED, script=script
    )

    page._generate_images()

    assert not _DialogSpy.instances
    assert generated == [None]


def test_basic_mode_skips_crop_logic_entirely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "compare.vpy"
    script.write_text(VPY_WITH_CROP, encoding="utf-8")
    page, generated = _make_images_page(
        tmp_path,
        monkeypatch,
        Cropping.MANUAL,
        ss_mode=ScreenShotMode.BASIC_SS_GEN,
        script=script,
    )

    page._generate_images()

    assert not _DialogSpy.instances
    assert generated == [None]


def test_no_comparison_pair_skips_crop_logic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, generated = _make_images_page(
        tmp_path, monkeypatch, Cropping.MANUAL, comparison=False
    )

    page._generate_images()

    assert not _DialogSpy.instances
    assert generated == [None]
