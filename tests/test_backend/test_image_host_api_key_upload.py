"""Coverage for the shared base64+API-key image-host upload flow
(src/backend/image_host_uploading/api_key_upload.py) and the three
uploaders built on it: ImgBB (refactored to use it), OnlyImage, and
Lensdump. No image host's upload logic was unit tested before this file --
aiohttp is mocked directly rather than via a request-mocking library since
none is a current dependency."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.image_host_uploading.api_key_upload import (
    _post_image,
    api_key_image_upload,
)
from src.backend.image_host_uploading.base_image_host import ImageUploadRequest
from src.backend.image_host_uploading.imgbb import ImageBBUploader
from src.backend.image_host_uploading.lensdump import LensdumpUploader
from src.backend.image_host_uploading.onlyimage import OnlyImageUploader
from src.exceptions import ImageUploadError
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
    "data": {
        "image": {"url": "https://example.com/full.png"},
        "medium": {"url": "https://example.com/medium.png"},
    }
}


def _patched_post(response: _MockResponse) -> MagicMock:
    return MagicMock(return_value=response)


def test_body_auth_mode_sends_key_in_form_data_not_headers() -> None:
    post = _patched_post(_MockResponse(200, _SUCCESS_RESPONSE))
    with patch("aiohttp.ClientSession.post", post):
        asyncio.run(
            _post_image(
                "https://api.imgbb.com/1/upload",
                "my-key",
                "body",
                "base64data",
                "imgbb",
            )
        )

    _, kwargs = post.call_args
    assert kwargs["data"] == {"image": "base64data", "key": "my-key"}
    assert kwargs["headers"] is None


def test_header_auth_mode_sends_key_as_header_not_form_data() -> None:
    post = _patched_post(_MockResponse(200, _SUCCESS_RESPONSE))
    with patch("aiohttp.ClientSession.post", post):
        asyncio.run(
            _post_image(
                "https://onlyimage.org/api/1/upload",
                "my-key",
                "header",
                "base64data",
                "OnlyImage",
            )
        )

    _, kwargs = post.call_args
    assert kwargs["data"] == {"image": "base64data"}
    assert kwargs["headers"] == {"X-API-Key": "my-key"}


def test_response_parsing_extracts_full_and_medium_urls(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake image data")

    with patch(
        "aiohttp.ClientSession.post",
        _patched_post(_MockResponse(200, _SUCCESS_RESPONSE)),
    ):
        results = asyncio.run(
            api_key_image_upload(
                url="https://api.imgbb.com/1/upload",
                api_key="my-key",
                auth_mode="body",
                host_name="imgbb",
                filepaths=[image],
            )
        )

    assert results is not None
    assert results[0] == ImageUploadData(
        "https://example.com/full.png", "https://example.com/medium.png"
    )


def test_missing_api_key_raises_without_a_network_call() -> None:
    post = _patched_post(_MockResponse(200, _SUCCESS_RESPONSE))
    with patch("aiohttp.ClientSession.post", post):
        with pytest.raises(ImageUploadError, match="API key"):
            asyncio.run(
                api_key_image_upload(
                    url="https://api.imgbb.com/1/upload",
                    api_key="",
                    auth_mode="body",
                    host_name="imgbb",
                    filepaths=[Path("shot.png")],
                )
            )

    post.assert_not_called()


def test_imgbb_uploader_still_produces_expected_data_after_refactor(
    tmp_path: Path,
) -> None:
    """Regression guard: ImageBBUploader's observable behavior must be
    unchanged now that it delegates to the shared helper."""
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake image data")

    with patch(
        "aiohttp.ClientSession.post",
        _patched_post(_MockResponse(200, _SUCCESS_RESPONSE)),
    ):
        results = asyncio.run(
            ImageBBUploader(api_key="my-key").upload(
                ImageUploadRequest(filepaths=[image])
            )
        )

    assert results[0] == ImageUploadData(
        "https://example.com/full.png", "https://example.com/medium.png"
    )


def test_onlyimage_and_lensdump_target_their_own_url_with_header_auth(
    tmp_path: Path,
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake image data")

    for uploader_cls, expected_url in (
        (OnlyImageUploader, "https://onlyimage.org/api/1/upload"),
        (LensdumpUploader, "https://lensdump.com/api/1/upload"),
    ):
        post = _patched_post(_MockResponse(200, _SUCCESS_RESPONSE))
        with patch("aiohttp.ClientSession.post", post):
            results = asyncio.run(
                uploader_cls(api_key="my-key").upload(
                    ImageUploadRequest(filepaths=[image])
                )
            )

        assert results[0] == ImageUploadData(
            "https://example.com/full.png", "https://example.com/medium.png"
        )
        args, kwargs = post.call_args
        assert args[0] == expected_url
        assert kwargs["headers"] == {"X-API-Key": "my-key"}
        assert "key" not in kwargs["data"]
