import sys

from PySide6.QtWidgets import QLabel
import shiboken6

from src.frontend.utils import QWidgetTempStyle


def test_style_restore_survives_a_deleted_widget(qapp, monkeypatch) -> None:
    """The timer can fire up to a second after the widget's C++ object is gone.

    A Python exception raised inside a Qt slot does not propagate through
    ``emit()`` -- PySide6 routes it to ``sys.excepthook`` instead. So this
    test cannot rely on ``pytest.raises`` around ``emit()``; it has to
    intercept ``sys.excepthook`` to detect an unhandled RuntimeError.
    """
    helper = QWidgetTempStyle()
    widget = QLabel()
    timer = helper.set_temp_style(widget, "color: red;", duration=1000)

    widget.deleteLater()
    shiboken6.delete(widget)
    assert not shiboken6.isValid(widget)

    unhandled: list[BaseException] = []
    monkeypatch.setattr(
        sys, "excepthook", lambda _type, value, _tb: unhandled.append(value)
    )

    timer.timeout.emit()

    # Must not have raised RuntimeError: Internal C++ object already deleted.
    assert unhandled == []
