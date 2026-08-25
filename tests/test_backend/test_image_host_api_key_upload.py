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
    extract_image_urls,
)
from src.backend.image_host_uploading.base_image_host import ImageUploadRequest
from src.backend.image_host_uploading.chevereto_v4 import (
    CheveretoV4Uploader,
    _create_api_url,
)
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


# --------------------------------------------------------------------------
# Chevereto response shapes
# --------------------------------------------------------------------------
# The same API v1 has shipped three of these across versions and deployments,
# and the hosts on this code path span all three. ptscreens is the reason the
# third is here: the reference implementation vendored under `scraps/` reads
# `image.url` at the top level, where ImgBB puts it under `data`.
_DATA_IMAGE_NESTED = {
    "data": {
        "image": {"url": "https://example.com/full.png"},
        "medium": {"url": "https://example.com/medium.png"},
    }
}
_DATA_FLAT = {
    "data": {
        "url": "https://example.com/full.png",
        "medium": {"url": "https://example.com/medium.png"},
    }
}
_TOP_LEVEL_IMAGE = {
    "image": {
        "url": "https://example.com/full.png",
        "medium": {"url": "https://example.com/medium.png"},
    }
}


@pytest.mark.parametrize(
    "response",
    [_DATA_IMAGE_NESTED, _DATA_FLAT, _TOP_LEVEL_IMAGE],
    ids=["data.image.url", "data.url", "image.url"],
)
def test_every_chevereto_response_shape_yields_the_same_urls(
    response: dict[str, Any],
) -> None:
    assert extract_image_urls(response) == ImageUploadData(
        "https://example.com/full.png", "https://example.com/medium.png"
    )


def test_a_missing_medium_stays_empty_rather_than_repeating_the_full_url() -> None:
    """Chevereto omits `medium` for images under its medium threshold. The
    token layer already documents "medium_url if available, else url", so
    substituting here would hide the distinction it is making."""
    assert extract_image_urls({"data": {"image": {"url": "https://x/full.png"}}}) == (
        ImageUploadData("https://x/full.png", "")
    )


def test_an_error_response_yields_no_urls() -> None:
    """`assert_all_images_uploaded` turns a falsy url into a reported failure,
    so a rejected upload must not come back looking like a successful one."""
    assert extract_image_urls({"status": 429, "reason": "Too Many Requests"}) == (
        ImageUploadData("", "")
    )


def test_both_auth_mode_sends_the_key_in_the_body_and_the_header() -> None:
    """Chevereto accepts either, and which one a given site honours varies by
    version and configuration -- ptscreens.com documents only the header."""
    post = _patched_post(_MockResponse(200, _SUCCESS_RESPONSE))
    with patch("aiohttp.ClientSession.post", post):
        asyncio.run(
            _post_image(
                "https://ptscreens.com/api/1/upload",
                "my-key",
                "both",
                "base64data",
                "PTScreens",
            )
        )

    _, kwargs = post.call_args
    assert kwargs["data"] == {"image": "base64data", "key": "my-key"}
    assert kwargs["headers"] == {"X-API-Key": "my-key"}


def test_chevereto_v4_uploader_targets_the_instance_url_with_both_auth(
    tmp_path: Path,
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake image data")

    post = _patched_post(_MockResponse(200, _TOP_LEVEL_IMAGE))
    with patch("aiohttp.ClientSession.post", post):
        results = asyncio.run(
            CheveretoV4Uploader(
                api_key="my-key", url="https://ptscreens.com/", host_name="PTScreens"
            ).upload(ImageUploadRequest(filepaths=[image]))
        )

    assert results[0] == ImageUploadData(
        "https://example.com/full.png", "https://example.com/medium.png"
    )
    args, kwargs = post.call_args
    assert args[0] == "https://ptscreens.com/api/1/upload"
    assert kwargs["headers"] == {"X-API-Key": "my-key"}
    assert kwargs["data"]["key"] == "my-key"


@pytest.mark.parametrize(
    "configured_url",
    [
        "https://ptscreens.com",
        "https://ptscreens.com/",
        "https://ptscreens.com/api/1/upload",
        "https://ptscreens.com/api/1/upload/",
    ],
)
def test_the_api_path_is_appended_only_when_it_is_not_already_there(
    configured_url: str,
) -> None:
    assert _create_api_url(configured_url).startswith(
        "https://ptscreens.com/api/1/upload"
    )
