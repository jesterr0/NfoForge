"""A listener one test leaves behind must not still be there in the next.

`GlobalSignals` is a process-wide singleton, and every settings page connects
itself to it in `__init__` and never disconnects. A widget a test builds is
rarely destroyed, so without isolation each one stays subscribed for the rest
of the session and every later emit fans out to all of them.

That is not a tidiness point. `SeriesManagement` and `MoviesManagement` answer
`global_management_state_changed` by re-rendering their examples, which runs
`guessit` over a filename several times. By the end of the frontend suite the
signal had 33 listeners and a single emit took about three seconds, which is
how a trivial wizard test that merely pumps the event queue reached the 60
second timeout on CI.
"""

from typing import Any

from nfoforge.frontend.global_signals import GSigs

_received: list[object] = []


def _record(data: object) -> None:
    _received.append(data)


def test_a_listener_reaches_the_signal_inside_its_own_test(qapp: Any) -> None:
    """Connect and never disconnect, the way every settings page does."""
    _received.clear()
    GSigs().global_management_state_changed.connect(_record)
    GSigs().global_management_state_changed.emit({"probe": "first"})

    assert _received == [{"probe": "first"}]


def test_the_next_test_does_not_inherit_that_listener(qapp: Any) -> None:
    _received.clear()
    GSigs().global_management_state_changed.emit({"probe": "second"})

    assert _received == []
