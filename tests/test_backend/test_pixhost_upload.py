"""Coverage for the Pixhost image host (no API key, real multipart file
upload, and a thumbnail-to-full-size URL transform)."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from src.backend.image_host_uploading.base_image_host import ImageUploadRequest
from src.backend.image_host_uploading.pixhost import (
    PixhostUploader,
    _full_size_url,
    pixhost_upload,
)
from src.packages.custom_types import ImageUploadData


class _MockResponse:
    def __init__(self, status: int, json_data: dict[str, Any]) -> None:
        self.status = status
        self.reason = "OK"
        self._json_data = json_data

    async def json(self) -> dict[str, Any]:
        return self._json_data

    async def __aenter__(self) -> "_MockResponse":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


_SUCCESS_RESPONSE = {
    "th_url": "https://t60.pixhost.to/thumbs/1/23456789.png",
    "show_url": "https://pixhost.to/show/1/23456789.png",
}


def test_full_size_url_transform() -> None:
    assert (
        _full_size_url("https://t60.pixhost.to/thumbs/1/23456789.png")
        == "https://img60.pixhost.to/images/1/23456789.png"
    )


def test_upload_sends_no_authentication_at_all(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake image data")
    post = MagicMock(return_value=_MockResponse(200, _SUCCESS_RESPONSE))

    with patch("aiohttp.ClientSession.post", post):
        results = asyncio.run(pixhost_upload(filepaths=[image], progress_callback=None))

    assert results is not None
    assert results[0] == ImageUploadData(
        "https://img60.pixhost.to/images/1/23456789.png",
        "https://t60.pixhost.to/thumbs/1/23456789.png",
    )

    args, kwargs = post.call_args
    assert args[0] == "https://api.pixhost.to/images"
    # no api key/credential anywhere in the request
    assert "headers" not in kwargs or not kwargs.get("headers")
    form_data = kwargs["data"]
    field_names = {field[0]["name"] for field in form_data._fields}
    assert field_names == {"img", "content_type", "max_th_size"}
    assert "key" not in field_names
    assert "api_key" not in field_names


def test_uploader_returns_empty_dict_for_no_filepaths() -> None:
    result = asyncio.run(PixhostUploader().upload(ImageUploadRequest(filepaths=[])))
    assert result == {}
