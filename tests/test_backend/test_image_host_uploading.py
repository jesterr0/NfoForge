import pytest

from src.backend.image_host_uploading.img_uploader import assert_all_images_uploaded
from src.exceptions import ImageUploadError
from src.packages.custom_types import ImageUploadData


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
