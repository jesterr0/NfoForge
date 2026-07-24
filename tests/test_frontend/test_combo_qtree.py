from src.enums.image_host import ImageHost, ImageSource
from src.frontend.custom_widgets.combo_qtree import ComboBoxTreeWidget
from src.packages.custom_types import ImageUploadFromTo


def _tree_with_payload(payload: object) -> ComboBoxTreeWidget:
    tree = ComboBoxTreeWidget(headers=("Tracker", "", "Status"))
    tree.add_row(
        headers=("MoreThanTV", "", "Queued"),
        combo_data=[(1, [("IMGs ➔ Chevereto v4", payload)])],
    )
    return tree


def test_get_item_values_preserves_named_tuple_payload() -> None:
    """Regression guard: PySide6 6.10 converts a tuple stored as combo userData
    into a plain list, which stripped ImageUploadFromTo down to a list and made
    the isinstance check in handle_images_for_trackers fail, so every tracker
    was processed with no images."""
    upload_from_to = ImageUploadFromTo(ImageSource.IMAGES, ImageHost.CHEVERETO_V4)
    tree = _tree_with_payload(
        (upload_from_to, (ImageHost.CHEVERETO_V4, ImageHost.CHEVERETO_V4))
    )

    ((_tracker, (_text, data), _status),) = tree.get_item_values()

    assert isinstance(data, tuple)
    assert isinstance(data[0], ImageUploadFromTo)
    assert data[0].img_from is ImageSource.IMAGES
    assert data[0].img_to is ImageHost.CHEVERETO_V4


def test_get_item_values_returns_the_same_object() -> None:
    payload = ImageUploadFromTo(ImageSource.URLS, ImageHost.IMAGE_BB)
    tree = _tree_with_payload(payload)

    ((_tracker, (_text, data), _status),) = tree.get_item_values()

    assert data is payload


def test_get_item_values_preserves_scalar_payload() -> None:
    tree = _tree_with_payload(ImageHost.DISABLED)

    ((_tracker, (text, data), _status),) = tree.get_item_values()

    assert text == "IMGs ➔ Chevereto v4"
    assert data is ImageHost.DISABLED


def test_get_item_values_preserves_none_payload() -> None:
    tree = _tree_with_payload(None)

    ((_tracker, (_text, data), _status),) = tree.get_item_values()

    assert data is None


def test_get_item_values_reads_plain_columns() -> None:
    tree = ComboBoxTreeWidget(headers=("Tracker", "Status"))
    tree.add_row(headers=("MoreThanTV", "Queued"))

    assert tree.get_item_values() == [("MoreThanTV", "Queued")]
