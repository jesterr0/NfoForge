from types import SimpleNamespace
from typing import cast

import pytest

from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.backend.process import ProcessBackEnd
from src.config.config import ConfigManager
from src.enums.image_host import ImageHost
from src.exceptions import ImageHostError
from src.packages.custom_types import ImageHostRef, ImageUploadData
from src.plugins.api import PluginDefinition
from src.plugins.manager import PluginManager


class _StubImageHostUploader(BaseImageHostUploader):
    async def upload(self, request: ImageUploadRequest) -> dict[int, ImageUploadData]:
        return {}


def _backend(
    *, enable_plugins: bool, plugin_id: str | None, manager: PluginManager
) -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        ConfigManager,
        SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(enable_plugins=enable_plugins),
                plugins=SimpleNamespace(image_host_uploader=plugin_id),
            ),
            plugin_manager=manager,
        ),
    )
    return backend


def test_returns_the_configured_plugin_uploader() -> None:
    uploader = _StubImageHostUploader()
    manager = PluginManager()
    manager.register(
        "test.imghost",
        PluginDefinition(
            display_name="test.imghost",
            version="1.0.0",
            image_host_uploader=uploader,
        ),
        "test",
    )
    backend = _backend(enable_plugins=True, plugin_id="test.imghost", manager=manager)

    result = backend._get_uploader_for_host(ImageHostRef(ImageHost.PLUGIN))

    assert result is uploader


def test_raises_when_plugins_are_disabled() -> None:
    manager = PluginManager()
    backend = _backend(enable_plugins=False, plugin_id="test.imghost", manager=manager)

    with pytest.raises(ImageHostError, match="disabled"):
        backend._get_uploader_for_host(ImageHostRef(ImageHost.PLUGIN))


def test_raises_when_nothing_is_configured() -> None:
    manager = PluginManager()
    backend = _backend(enable_plugins=True, plugin_id=None, manager=manager)

    with pytest.raises(ImageHostError, match="No plugin configured"):
        backend._get_uploader_for_host(ImageHostRef(ImageHost.PLUGIN))


def test_raises_when_the_configured_plugin_is_unavailable() -> None:
    manager = PluginManager()
    backend = _backend(enable_plugins=True, plugin_id="missing.plugin", manager=manager)

    with pytest.raises(ImageHostError, match="not available"):
        backend._get_uploader_for_host(ImageHostRef(ImageHost.PLUGIN))
