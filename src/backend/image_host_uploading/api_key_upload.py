import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping, Sequence
from os import PathLike
from pathlib import Path
from typing import Any, Literal, cast

import aiohttp

from src.exceptions import ImageUploadError
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import ImageUploadData

AuthMode = Literal["body", "header", "both"]


async def _post_image(
    url: str,
    api_key: str,
    auth_mode: AuthMode,
    image_data: str,
    host_name: str,
    retries: int = 3,
) -> dict[str, Any]:
    """Uploads a base64-encoded image using aiohttp with retries and proper error handling."""
    data: dict[str, str] = {"image": image_data}
    headers: dict[str, str] | None = None
    if auth_mode in ("body", "both"):
        data["key"] = api_key
    if auth_mode in ("header", "both"):
        headers = {"X-API-Key": api_key}

    async with aiohttp.ClientSession() as session:
        for attempt in range(retries):
            try:
                async with session.post(url, data=data, headers=headers) as response:
                    if response.status == 200:
                        return cast(dict[str, Any], await response.json())

                    if response.status in {429, 500, 502, 503, 504}:
                        await asyncio.sleep(2**attempt)
                        continue
                    else:
                        return {"status": response.status, "reason": response.reason}

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < retries - 1:
                    await asyncio.sleep(2**attempt)
                else:
                    LOG.warning(
                        LOG.LOG_SOURCE.BE,
                        f"{host_name}: upload failed after {retries} attempts: {e}",
                    )

    return {"status": "Failed", "reason": "Failure on retry"}


def _sub_mapping(source: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = source.get(key)
    return value if isinstance(value, Mapping) else None


def extract_image_urls(response: Mapping[str, Any]) -> ImageUploadData:
    """Pull the full-size and medium URLs out of a Chevereto-family response.

    The same API v1 has shipped three response shapes across versions and
    deployments, and the hosts here span all three:

        {"data": {"image": {"url": ...}, "medium": {"url": ...}}}   ImgBB
        {"data": {"url": ...,            "medium": {"url": ...}}}   many v4
        {"image": {"url": ..., "medium": {"url": ...}}}             some v3/v4

    So unwrap `data` if it is there, then accept the full-size URL either
    nested under `image` or sitting flat, and look for `medium` as a sibling
    of whichever one answered.

    `medium` is deliberately not defaulted to the full-size URL when absent
    (Chevereto omits it for images below its medium threshold) -- the token
    layer already documents and handles "medium_url if available, else url".
    """
    payload: Mapping[str, Any] = _sub_mapping(response, "data") or response
    image = _sub_mapping(payload, "image")

    full_url = ""
    for candidate in (image, payload):
        if candidate is None:
            continue
        value = candidate.get("url")
        if isinstance(value, str) and value:
            full_url = value
            break

    medium_url = ""
    for candidate in (image, payload):
        if candidate is None:
            continue
        medium = _sub_mapping(candidate, "medium")
        value = medium.get("url") if medium else None
        if isinstance(value, str) and value:
            medium_url = value
            break

    return ImageUploadData(full_url, medium_url)


async def _upload_batch(
    url: str,
    api_key: str,
    auth_mode: AuthMode,
    host_name: str,
    filepaths: Sequence[Path],
    start_index: int,
    cb: Callable[[int], Awaitable[None]] | None = None,
) -> dict[int, ImageUploadData]:
    async def upload_single_image(
        filepath: PathLike[str], index: int
    ) -> tuple[int, ImageUploadData]:
        with open(filepath, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")
            response = await _post_image(url, api_key, auth_mode, image_data, host_name)
            upload_data = extract_image_urls(response)
            if cb:
                await cb(index + 1)
            return index, upload_data

    tasks = [
        asyncio.create_task(upload_single_image(filepath, start_index + i))
        for i, filepath in enumerate(filepaths)
    ]
    batch_results = await asyncio.gather(*tasks)
    return {index: result for index, result in batch_results}


async def api_key_image_upload(
    url: str,
    api_key: str,
    auth_mode: AuthMode,
    host_name: str,
    filepaths: Sequence[Path],
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
) -> dict[int, ImageUploadData] | None:
    """Shared upload flow for image hosts that accept a base64-encoded image
    plus a static API key (as a ``key`` form field, an ``X-API-Key`` header,
    or both) and answer with one of the Chevereto-family response shapes
    `extract_image_urls` knows.

    Used by ImgBB, OnlyImage, Lensdump and every configured Chevereto v4
    instance -- identical apart from where the API key goes. Chevereto
    instances send ``both``, since a given site may honour only one of the two
    and ignores the other.
    """
    if not api_key:
        raise ImageUploadError(f"You are required to have an API key for {host_name}")

    if not filepaths:
        return {}
    filepaths = sorted(filepaths)

    results: dict[int, ImageUploadData] = {}
    tasks: list[asyncio.Task[dict[int, ImageUploadData]]] = []
    for i in range(0, len(filepaths), batch_size):
        batch = filepaths[i : i + batch_size]
        task = asyncio.create_task(
            _upload_batch(
                url, api_key, auth_mode, host_name, batch, i, progress_callback
            )
        )
        tasks.append(task)

    batch_results_list = await asyncio.gather(*tasks)
    for batch_results in batch_results_list:
        results.update(batch_results)

    return results
