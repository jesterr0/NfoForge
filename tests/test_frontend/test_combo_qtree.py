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


def test_combo_changed_sees_a_resolvable_combo_on_the_very_first_item() -> None:
    """Regression guard: adding a combo box's first item transitions Qt's
    `currentIndex` from -1 to 0, which fires `currentIndexChanged` (and thus
    `combo_changed`) synchronously, from inside `add_combobox_to_row`, before
    that method used to register the combo in `combo_box_map`. A listener
    that reacted by calling `get_item_values()` -- as `ProcessPage` does --
    saw its own row's column as plain (still-empty) item text instead of the
    combo tuple, since `(item, col_index) not in combo_box_map` yet, which
    crashed unpacking it. This was reachable with as little as a single combo
    option (e.g. a tracker offered only "Disabled" because no screenshots
    were provided for the run)."""
    tree = ComboBoxTreeWidget(headers=("Tracker", "", "Status"))
    seen_during_signal: list[tuple[str | tuple[str, object], ...]] = []
    tree.combo_changed.connect(
        lambda *_args: seen_during_signal.extend(tree.get_item_values())
    )

    # a single combo option is enough: it still triggers the -1 -> 0
    # transition on its own
    tree.add_row(
        headers=("Aither", "", "Queued"),
        combo_data=[(1, [("Disabled", ImageHost.DISABLED)])],
    )

    assert seen_during_signal, "combo_changed should have fired while adding the item"
    tracker, host_column, _status = seen_during_signal[0]
    assert tracker == "Aither"
    assert isinstance(host_column, tuple)
    _text, data = host_column
    assert data is ImageHost.DISABLED
