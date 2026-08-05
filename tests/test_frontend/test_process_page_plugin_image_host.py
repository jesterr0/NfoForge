from types import SimpleNamespace

from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.frontend.wizards.process import ProcessPage
from src.packages.custom_types import ImageUploadData
from src.plugins.api import PluginDefinition
from src.plugins.manager import PluginManager


class _StubImageHostUploader(BaseImageHostUploader):
    async def upload(self, request: ImageUploadRequest) -> dict[int, ImageUploadData]:
        return {}


def _fake_page(
    *, enable_plugins: bool, plugin_id: str | None, manager: PluginManager
) -> object:
    """A duck-typed stand-in for `ProcessPage`, mirroring the pattern already
    used in test_process_page_retry.py for calling its methods unbound."""
    return SimpleNamespace(
        config=SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(enable_plugins=enable_plugins),
                plugins=SimpleNamespace(image_host_uploader=plugin_id),
            ),
            plugin_manager=manager,
        )
    )


def test_available_when_a_plugin_is_registered_and_selected() -> None:
    manager = PluginManager()
    manager.register(
        "test.imghost",
        PluginDefinition(
            display_name="test.imghost",
            version="1.0.0",
            image_host_uploader=_StubImageHostUploader(),
        ),
        "test",
    )

    result = ProcessPage._plugin_image_host_available(
        _fake_page(enable_plugins=True, plugin_id="test.imghost", manager=manager)
    )

    assert result is True


def test_unavailable_when_plugins_are_disabled() -> None:
    manager = PluginManager()
    manager.register(
        "test.imghost",
        PluginDefinition(
            display_name="test.imghost",
            version="1.0.0",
            image_host_uploader=_StubImageHostUploader(),
        ),
        "test",
    )

    result = ProcessPage._plugin_image_host_available(
        _fake_page(enable_plugins=False, plugin_id="test.imghost", manager=manager)
    )

    assert result is False


def test_unavailable_when_nothing_is_configured() -> None:
    manager = PluginManager()

    result = ProcessPage._plugin_image_host_available(
        _fake_page(enable_plugins=True, plugin_id=None, manager=manager)
    )

    assert result is False


def test_unavailable_when_the_configured_plugin_is_missing() -> None:
    manager = PluginManager()

    result = ProcessPage._plugin_image_host_available(
        _fake_page(enable_plugins=True, plugin_id="missing.plugin", manager=manager)
    )

    assert result is False
