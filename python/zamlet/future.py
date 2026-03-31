"""Awaitable future that carries a result value, backed by an Event.

Works with both cocotb Events and model Clock Events.
"""


class Future:

    def __init__(self, event):
        self._event = event
        self._result = None

    def set_result(self, value):
        self._result = value
        self._event.set()

    def __await__(self):
        yield from self._event.wait().__await__()
        return self._result
