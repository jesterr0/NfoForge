from __future__ import annotations

from pathlib import Path
import sys
import threading
import time

import pytest

from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import PluginError, PluginExecutionError
from src.packages.custom_types import ImageUploadData
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.tracker_search_result import TrackerSearchResult
from src.plugins.api import (
    DuplicateChecker,
    DuplicateCheckRequest,
    MetadataInputContext,
    MetadataTransformContext,
    MetadataTransformer,
    MetadataTransformRequest,
    PluginDefinition,
    PostUploadOutcome,
    PostUploadProcessor,
    PostUploadRequest,
    UploadReporter,
)
from src.plugins.manager import PluginManager


def _definition(
    *, plugin_id: str, metadata_transformer: MetadataTransformer
) -> PluginDefinition:
    return PluginDefinition(
        display_name=plugin_id,
        version="1.0.0",
        metadata_transformer=metadata_transformer,
    )


def _transform_request(*, timeout: int) -> MetadataTransformRequest:
    payload = MediaSearchPayload(title="TMDb title")
    return MetadataTransformRequest(
        config=None,  # type: ignore[arg-type]
        context=MetadataTransformContext(
            media_input=MetadataInputContext(
                input_path=None,
                media_type=None,
                working_dir=None,
                files=(),
            ),
            media_search=payload,
        ),
        payload=payload,
        timeout=timeout,
    )


def test_a_blocking_transformer_is_abandoned_at_the_timeout() -> None:
    manager = PluginManager()

    def hangs(request: MetadataTransformRequest) -> MediaSearchPayload:
        time.sleep(30)
        raise AssertionError("should never be reached")

    manager.register(
        "test.hang",
        _definition(plugin_id="test.hang", metadata_transformer=hangs),
        "test",
    )

    started = time.monotonic()
    with pytest.raises(PluginExecutionError, match="timed out"):
        manager.transform_metadata("test.hang", _transform_request(timeout=1))

    assert time.monotonic() - started < 10


def test_the_abandoned_transformer_thread_does_not_block_interpreter_exit() -> None:
    """A hung transformer's worker must be a daemon thread.

    Non-daemon threads (e.g. those spawned by ``ThreadPoolExecutor``) are joined
    by an ``atexit`` handler, so a genuinely hung transformer would block the
    application from exiting. A daemon thread does not.
    """
    manager = PluginManager()

    def hangs(request: MetadataTransformRequest) -> MediaSearchPayload:
        time.sleep(30)
        raise AssertionError("should never be reached")

    manager.register(
        "test.hang.daemon",
        _definition(plugin_id="test.hang.daemon", metadata_transformer=hangs),
        "test",
    )

    with pytest.raises(PluginExecutionError, match="timed out"):
        manager.transform_metadata("test.hang.daemon", _transform_request(timeout=1))

    hung_threads = [
        thread for thread in threading.enumerate() if "test.hang.daemon" in thread.name
    ]
    assert hung_threads
    assert all(thread.daemon for thread in hung_threads)


def test_a_transformer_finishing_before_the_timeout_succeeds() -> None:
    manager = PluginManager()

    def slow(request: MetadataTransformRequest) -> MediaSearchPayload:
        time.sleep(0.2)
        request.payload.title = "Transformed"
        return request.payload

    manager.register(
        "test.slow",
        _definition(plugin_id="test.slow", metadata_transformer=slow),
        "test",
    )

    result = manager.transform_metadata("test.slow", _transform_request(timeout=2))

    assert result.title == "Transformed"


def test_a_transformer_exception_still_propagates_as_plugin_execution_error() -> None:
    manager = PluginManager()

    def fails(request: MetadataTransformRequest) -> MediaSearchPayload:
        raise RuntimeError("provider unavailable")

    manager.register(
        "test.fails",
        _definition(plugin_id="test.fails", metadata_transformer=fails),
        "test",
    )

    with pytest.raises(PluginExecutionError, match="provider unavailable"):
        manager.transform_metadata("test.fails", _transform_request(timeout=2))


def test_a_transformer_calling_sys_exit_surfaces_as_an_error() -> None:
    """SystemExit is a BaseException, not an Exception.

    Catching only ``Exception`` in the worker would let the thread die
    silently on ``sys.exit()``: ``outcome`` would stay empty and the caller
    would read that as "the transformer chose not to change anything"
    instead of a crash.
    """
    manager = PluginManager()

    def exits(request: MetadataTransformRequest) -> MediaSearchPayload:
        sys.exit("plugin requested exit")

    manager.register(
        "test.exits",
        _definition(plugin_id="test.exits", metadata_transformer=exits),
        "test",
    )

    with pytest.raises(PluginExecutionError, match="plugin requested exit"):
        manager.transform_metadata("test.exits", _transform_request(timeout=2))


def _post_upload_definition(
    *, plugin_id: str, post_upload: PostUploadProcessor
) -> PluginDefinition:
    return PluginDefinition(
        display_name=plugin_id,
        version="1.0.0",
        post_upload=post_upload,
    )


def _post_upload_request(*, outcome: PostUploadOutcome) -> PostUploadRequest:
    return PostUploadRequest(
        config=None,  # type: ignore[arg-type]
        context=None,  # type: ignore[arg-type]
        tracker=TrackerSelection.AITHER,
        torrent_file=Path("release.torrent"),
        reporter=UploadReporter(
            append_text=lambda _text: None,
            replace_last_line=lambda _text: None,
            set_progress=lambda _value: None,
        ),
        outcome=outcome,
    )


def test_run_post_upload_calls_the_registered_processor() -> None:
    manager = PluginManager()
    received: list[PostUploadRequest] = []

    def notify(request: PostUploadRequest) -> None:
        received.append(request)

    manager.register(
        "test.notify",
        _post_upload_definition(plugin_id="test.notify", post_upload=notify),
        "test",
    )

    manager.run_post_upload(
        "test.notify", _post_upload_request(outcome=PostUploadOutcome.SUCCESS)
    )

    assert len(received) == 1
    assert received[0].outcome is PostUploadOutcome.SUCCESS


def test_run_post_upload_wraps_a_raising_processor_in_plugin_execution_error() -> None:
    manager = PluginManager()

    def explodes(request: PostUploadRequest) -> None:
        raise RuntimeError("notifier unreachable")

    manager.register(
        "test.explode",
        _post_upload_definition(plugin_id="test.explode", post_upload=explodes),
        "test",
    )

    with pytest.raises(PluginExecutionError, match="notifier unreachable"):
        manager.run_post_upload(
            "test.explode",
            _post_upload_request(outcome=PostUploadOutcome.UPLOAD_FAILED),
        )


class _StubImageHostUploader(BaseImageHostUploader):
    async def upload(self, request: ImageUploadRequest) -> dict[int, ImageUploadData]:
        return {}


def test_registering_an_image_host_uploader_only_plugin_succeeds() -> None:
    manager = PluginManager()
    uploader = _StubImageHostUploader()

    record = manager.register(
        "test.imghost",
        PluginDefinition(
            display_name="test.imghost",
            version="1.0.0",
            image_host_uploader=uploader,
        ),
        "test",
    )

    assert record.definition.image_host_uploader is uploader
    assert manager.definitions_with("image_host_uploader") == (record,)


def test_a_non_base_image_host_uploader_value_is_rejected() -> None:
    manager = PluginManager()

    with pytest.raises(PluginError, match="BaseImageHostUploader"):
        manager.register(
            "test.badimghost",
            PluginDefinition(
                display_name="test.badimghost",
                version="1.0.0",
                image_host_uploader="not an uploader",  # type: ignore[arg-type]
            ),
            "test",
        )


def _dupe_definition(
    *, plugin_id: str, duplicate_checker: DuplicateChecker
) -> PluginDefinition:
    return PluginDefinition(
        display_name=plugin_id,
        version="1.0.0",
        duplicate_checker=duplicate_checker,
    )


def _dupe_request(*, timeout: int = 5) -> DuplicateCheckRequest:
    return DuplicateCheckRequest(
        config=None,  # type: ignore[arg-type]
        tracker=TrackerSelection.AITHER,
        media_input=MediaInputPayload(),
        media_search=MediaSearchPayload(title="TMDb title"),
        timeout=timeout,
    )


def test_run_duplicate_checker_returns_the_processors_results() -> None:
    manager = PluginManager()
    hit = TrackerSearchResult(name="Existing.Release-GROUP")

    def finds_one(request: DuplicateCheckRequest) -> list[TrackerSearchResult]:
        return [hit]

    manager.register(
        "test.dupechecker",
        _dupe_definition(plugin_id="test.dupechecker", duplicate_checker=finds_one),
        "test",
    )

    result = manager.run_duplicate_checker("test.dupechecker", _dupe_request())

    assert list(result) == [hit]


def test_run_duplicate_checker_wraps_a_raising_processor_in_plugin_execution_error() -> (
    None
):
    manager = PluginManager()

    def explodes(request: DuplicateCheckRequest) -> list[TrackerSearchResult]:
        raise RuntimeError("search backend unreachable")

    manager.register(
        "test.explode",
        _dupe_definition(plugin_id="test.explode", duplicate_checker=explodes),
        "test",
    )

    with pytest.raises(PluginExecutionError, match="search backend unreachable"):
        manager.run_duplicate_checker("test.explode", _dupe_request())


def test_run_duplicate_checker_rejects_a_non_sequence_return() -> None:
    manager = PluginManager()

    def returns_wrong_type(request: DuplicateCheckRequest) -> object:
        return {"not": "a sequence"}

    manager.register(
        "test.badreturn",
        _dupe_definition(
            plugin_id="test.badreturn",
            duplicate_checker=returns_wrong_type,  # type: ignore[arg-type]
        ),
        "test",
    )

    with pytest.raises(PluginExecutionError, match="sequence"):
        manager.run_duplicate_checker("test.badreturn", _dupe_request())


def test_a_blocking_duplicate_checker_is_abandoned_at_the_timeout() -> None:
    manager = PluginManager()

    def hangs(request: DuplicateCheckRequest) -> list[TrackerSearchResult]:
        time.sleep(30)
        raise AssertionError("should never be reached")

    manager.register(
        "test.hang.dupe",
        _dupe_definition(plugin_id="test.hang.dupe", duplicate_checker=hangs),
        "test",
    )

    started = time.monotonic()
    with pytest.raises(PluginExecutionError, match="timed out"):
        manager.run_duplicate_checker("test.hang.dupe", _dupe_request(timeout=1))

    assert time.monotonic() - started < 10


def test_the_abandoned_duplicate_checker_thread_does_not_block_interpreter_exit() -> (
    None
):
    """Same daemon-thread guarantee as the metadata-transformer timeout path --
    see `PluginManager._run_transformer_with_timeout`'s docstring."""
    manager = PluginManager()

    def hangs(request: DuplicateCheckRequest) -> list[TrackerSearchResult]:
        time.sleep(30)
        raise AssertionError("should never be reached")

    manager.register(
        "test.hang.dupe.daemon",
        _dupe_definition(plugin_id="test.hang.dupe.daemon", duplicate_checker=hangs),
        "test",
    )

    with pytest.raises(PluginExecutionError, match="timed out"):
        manager.run_duplicate_checker("test.hang.dupe.daemon", _dupe_request(timeout=1))

    hung_threads = [
        thread
        for thread in threading.enumerate()
        if "test.hang.dupe.daemon" in thread.name
    ]
    assert hung_threads
    assert all(thread.daemon for thread in hung_threads)
