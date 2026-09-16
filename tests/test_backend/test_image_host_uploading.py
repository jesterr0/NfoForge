import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.backend.image_host_uploading.img_uploader import assert_all_images_uploaded
from src.backend.process import ProcessBackEnd
from src.enums.image_host import ImageHost
from src.exceptions import ImageUploadError
from src.packages.custom_types import ImageHostRef, ImageUploadData


def test_partial_upload_failure_is_surfaced() -> None:
    # One of three images fails; the batch must not report success.
    images = {
        1: ImageUploadData("http://a", "http://a_m"),
        2: ImageUploadData(None, None),
        3: ImageUploadData("http://c", "http://c_m"),
    }
    with pytest.raises(ImageUploadError) as excinfo:
        assert_all_images_uploaded("Aither", images)

    assert "1 of 3" in str(excinfo.value)
    assert "Aither" in str(excinfo.value)


def test_a_complete_batch_raises_nothing() -> None:
    images = {
        1: ImageUploadData("http://a", "http://a_m"),
        2: ImageUploadData("http://b", "http://b_m"),
    }

    assert_all_images_uploaded("Aither", images)


def test_an_empty_batch_raises_nothing() -> None:
    # No images requested is not a failure; only a requested-but-missing URL is.
    assert_all_images_uploaded("Aither", {})


class _Recorder(BaseImageHostUploader):
    """Answers the way a real uploader does: keyed 0..n of what it was given."""

    def __init__(self) -> None:
        self.request: ImageUploadRequest | None = None

    async def upload(self, request: ImageUploadRequest) -> dict[int, ImageUploadData]:
        self.request = request
        return {
            offset: ImageUploadData(f"https://host/{path.stem}.png", None)
            for offset, path in enumerate(request.filepaths)
        }


def _upload_backend(uploader: BaseImageHostUploader, timeout: int = 60):
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        Any,
        SimpleNamespace(
            settings=SimpleNamespace(general=SimpleNamespace(timeout=timeout))
        ),
    )
    backend._get_uploader_for_host = (  # pyright: ignore[reportAttributeAccessIssue]
        lambda _host: uploader
    )
    return cast(ProcessBackEnd, backend)


def test_a_retry_lands_its_urls_at_the_positions_it_was_sent_for(
    tmp_path: Path,
) -> None:
    """The off-by-one that would quietly overwrite the first three images.

    An uploader keys its answer 0, 1, 2 whether it was handed the whole set or
    a retry of positions 3, 6 and 11. Taken at face value the retry's URLs
    would land on images 0, 1 and 2 -- three good images replaced, and the
    three actual gaps still empty.
    """
    files = [tmp_path / f"shot_{index:02d}.png" for index in range(12)]
    recorder = _Recorder()
    backend = _upload_backend(recorder)

    results = asyncio.run(
        backend.handle_image_upload(
            {ImageHostRef(ImageHost.PIXHOST): (3, 6, 11)}, files, lambda _value: None
        )
    )

    # only the failed files were sent
    assert recorder.request is not None
    assert list(recorder.request.filepaths) == [files[3], files[6], files[11]]
    # and their URLs came back at 3, 6 and 11 -- not 0, 1 and 2
    assert results[ImageHostRef(ImageHost.PIXHOST)] == {
        3: ImageUploadData("https://host/shot_03.png", None),
        6: ImageUploadData("https://host/shot_06.png", None),
        11: ImageUploadData("https://host/shot_11.png", None),
    }


def test_the_configured_timeout_reaches_the_uploader(tmp_path: Path) -> None:
    """Image hosts used to set none at all and inherit aiohttp's five minutes."""
    recorder = _Recorder()
    backend = _upload_backend(recorder, timeout=45)

    asyncio.run(
        backend.handle_image_upload(
            {ImageHostRef(ImageHost.PIXHOST): (0,)},
            [tmp_path / "shot_00.png"],
            lambda _value: None,
        )
    )

    assert recorder.request is not None
    assert recorder.request.timeout == 45


def test_a_per_host_override_beats_the_configured_timeout(tmp_path: Path) -> None:
    recorder = _Recorder()
    backend = _upload_backend(recorder, timeout=45)

    asyncio.run(
        backend.handle_image_upload(
            {ImageHostRef(ImageHost.PIXHOST): (0,)},
            [tmp_path / "shot_00.png"],
            lambda _value: None,
            {ImageHostRef(ImageHost.PIXHOST): 300},
        )
    )

    assert recorder.request is not None
    assert recorder.request.timeout == 300
