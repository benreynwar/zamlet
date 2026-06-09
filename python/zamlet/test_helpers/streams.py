"""Deque-backed cocotb helpers for valid/ready streams."""

from collections import deque
from random import Random

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet.utils import make_seed


def discover_bits(dut, prefix: str) -> dict[str, object]:
    bits_prefix = f"{prefix}_bits_"
    names = [name for name in dir(dut) if name.startswith(bits_prefix)]
    fields = {name[len(bits_prefix):] for name in names}
    bits = {}
    for name in names:
        field = name[len(bits_prefix):]
        parts = field.rsplit("_", 1)
        is_generated_alias = (
            len(parts) == 2
            and parts[1].isdigit()
            and parts[0] in fields
        )
        if not is_generated_alias:
            bits[field] = getattr(dut, name)
    return bits


def get_stream_signals(dut, prefix: str) -> tuple[dict[str, object], object | None]:
    bits = discover_bits(dut, prefix)
    if set(bits) == {"0"}:
        bits = {}
    if bits:
        return bits, None
    return bits, getattr(dut, f"{prefix}_bits")


def sample_stream_bits(bits: dict[str, object], scalar_bits):
    if scalar_bits is not None:
        return int(scalar_bits.value)
    return {field: int(signal.value) for field, signal in bits.items()}


def drive_stream_bits(prefix: str, bits: dict[str, object], scalar_bits, item) -> None:
    if scalar_bits is not None:
        assert not isinstance(item, dict), f"{prefix}: scalar stream got dict item"
        scalar_bits.value = item
        return

    assert isinstance(item, dict), f"{prefix}: bundle stream got scalar item"
    item_fields = set(item.keys())
    bit_fields = set(bits.keys())
    missing = bit_fields - item_fields
    extra = item_fields - bit_fields
    assert not missing and not extra, (
        f"{prefix}: item fields do not match bits fields; "
        f"missing={sorted(missing)} extra={sorted(extra)}"
    )
    for field, value in item.items():
        bits[field].value = value


class ValidReadySource:
    """Drive a Decoupled-style input stream from a queue."""

    def __init__(self, dut, clock, prefix: str):
        self.dut = dut
        self.clock = clock
        self.prefix = prefix
        self.valid = getattr(dut, f"{prefix}_valid")
        self.ready = getattr(dut, f"{prefix}_ready")
        self.bits, self.scalar_bits = get_stream_signals(dut, prefix)
        self.queue = deque()

    def append(self, item) -> None:
        self.queue.append(item)

    def extend(self, items) -> None:
        self.queue.extend(items)

    def start(self, rng: Random, p_valid: float = 1.0) -> list:
        return [cocotb.start_soon(self.run(seed=make_seed(rng), p_valid=p_valid))]

    def _drive_bits(self, item) -> None:
        drive_stream_bits(self.prefix, self.bits, self.scalar_bits, item)

    async def run(self, seed: int, p_valid: float = 1.0) -> None:
        rng = Random(seed)

        self.valid.value = 0
        current = None
        while True:
            if current is None and self.queue and rng.random() < p_valid:
                current = self.queue.popleft()

            if current is None:
                self.valid.value = 0
                fired = False
            else:
                self._drive_bits(current)
                self.valid.value = 1
                await ReadOnly()
                fired = bool(int(self.ready.value))

            await RisingEdge(self.clock)

            if fired:
                current = None


class ValidReadySink:
    """Capture a Decoupled-style output stream into a queue."""

    def __init__(
        self,
        dut,
        clock,
        prefix: str,
        max_queue_depth: int | None = None,
    ):
        self.dut = dut
        self.clock = clock
        self.prefix = prefix
        self.valid = getattr(dut, f"{prefix}_valid")
        self.ready = getattr(dut, f"{prefix}_ready")
        self.bits, self.scalar_bits = get_stream_signals(dut, prefix)
        self.max_queue_depth = max_queue_depth
        self.queue = deque()

    def pop(self):
        return self.queue.popleft()

    def start(self, rng: Random, p_ready: float = 1.0) -> list:
        return [cocotb.start_soon(self.run(seed=make_seed(rng), p_ready=p_ready))]

    def _sample_bits(self):
        return sample_stream_bits(self.bits, self.scalar_bits)

    async def run(self, seed: int, p_ready: float = 1.0) -> None:
        rng = Random(seed)

        self.ready.value = 0
        while True:
            has_room = (
                self.max_queue_depth is None
                or len(self.queue) < self.max_queue_depth
            )
            self.ready.value = int(has_room and rng.random() < p_ready)
            await ReadOnly()
            if int(self.valid.value) and int(self.ready.value):
                self.queue.append(self._sample_bits())
            await RisingEdge(self.clock)


class ValidMonitor:
    """Capture a Valid-style output into a queue."""

    def __init__(self, dut, clock, prefix: str):
        self.dut = dut
        self.clock = clock
        self.prefix = prefix
        self.valid = getattr(dut, f"{prefix}_valid")
        self.bits, self.scalar_bits = get_stream_signals(dut, prefix)
        self.queue = deque()

    def pop(self):
        return self.queue.popleft()

    def start(self) -> list:
        return [cocotb.start_soon(self.run())]

    def _sample_bits(self):
        return sample_stream_bits(self.bits, self.scalar_bits)

    async def run(self) -> None:
        while True:
            await ReadOnly()
            if int(self.valid.value):
                self.queue.append(self._sample_bits())
            await RisingEdge(self.clock)
