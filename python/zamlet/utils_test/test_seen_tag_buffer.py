"""Randomized cocotb test for SeenTagBuffer."""

from collections import deque
from dataclasses import dataclass
from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet import test_utils


@dataclass
class Entry:
    data: int
    tag: int
    seen: bool


@dataclass
class PendingEntry:
    entry: Entry
    input_broadcast_count: int


def drive_entry(dut: HierarchyObject, entry: Entry) -> None:
    dut.io_i_bits_data.value = entry.data
    dut.io_i_bits_tag.value = entry.tag
    dut.io_i_bits_seen.value = int(entry.seen)


def read_output(dut: HierarchyObject) -> Entry:
    return Entry(
        data=int(dut.io_o_bits_data.value),
        tag=int(dut.io_o_bits_tag.value),
        seen=bool(int(dut.io_o_bits_seen.value)),
    )


def apply_broadcasts(entry: Entry, tags: list[int]) -> Entry:
    seen = entry.seen or any(entry.tag == tag for tag in tags)
    return Entry(entry.data, entry.tag, seen)


def copy_entry(entry: Entry) -> Entry:
    return Entry(entry.data, entry.tag, entry.seen)


def current_broadcast_tag(dut: HierarchyObject) -> int | None:
    if int(dut.io_broadcastOut_valid.value) == 0:
        return None
    return int(dut.io_broadcastOut_bits.value)


@cocotb.test()
async def test_random_stream_with_broadcasts(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")

    seed = 0x5EED_7A6
    rng = Random(seed)
    n_items = 200
    data_width = len(dut.io_i_bits_data.value)
    tag_width = len(dut.io_i_bits_tag.value)
    max_tag = 1 << tag_width

    entries = [
        Entry(
            data=rng.getrandbits(data_width),
            tag=rng.randrange(max_tag),
            seen=bool(rng.randrange(2)),
        )
        for _ in range(n_items)
    ]

    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    dut.io_i_valid.value = 0
    drive_entry(dut, Entry(0, 0, False))
    dut.io_o_ready.value = 0
    dut.io_broadcastIn_valid.value = 0
    dut.io_broadcastIn_bits.value = 0

    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)

    expected = deque()
    sent = 0
    received = 0
    input_broadcast_tags: list[int] = []
    output_broadcast_count = 0

    for _cycle in range(10_000):
        want_send = sent < n_items and rng.random() < 0.75
        current_entry = entries[sent] if want_send else Entry(0, rng.randrange(max_tag), False)
        current_broadcast = rng.randrange(max_tag) if rng.random() < 0.35 else None

        dut.io_i_valid.value = int(want_send)
        drive_entry(dut, current_entry)
        dut.io_o_ready.value = int(rng.random() < 0.70)
        dut.io_broadcastIn_valid.value = int(current_broadcast is not None)
        dut.io_broadcastIn_bits.value = 0 if current_broadcast is None else current_broadcast

        await ReadOnly()

        output_fire = int(dut.io_o_valid.value) == 1 and int(dut.io_o_ready.value) == 1
        if output_fire:
            pending = expected.popleft()
            expected_entry = apply_broadcasts(
                pending.entry,
                input_broadcast_tags[
                    pending.input_broadcast_count:output_broadcast_count
                ],
            )
            actual = read_output(dut)
            assert actual == expected_entry, (
                f"output {received}: expected={expected_entry}, actual={actual}, "
                f"seed={seed:#x}"
            )
            received += 1

        broadcast_out_tag = current_broadcast_tag(dut)
        if broadcast_out_tag is not None:
            assert output_broadcast_count < len(input_broadcast_tags), (
                f"unexpected broadcast output tag={broadcast_out_tag}; seed={seed:#x}"
            )
            expected_tag = input_broadcast_tags[output_broadcast_count]
            assert broadcast_out_tag == expected_tag, (
                f"broadcast output {output_broadcast_count}: "
                f"expected tag={expected_tag}, actual tag={broadcast_out_tag}, "
                f"seed={seed:#x}"
            )
            output_broadcast_count += 1

        if current_broadcast is not None:
            input_broadcast_tags.append(current_broadcast)

        input_fire = int(dut.io_i_valid.value) == 1 and int(dut.io_i_ready.value) == 1
        if input_fire:
            expected.append(PendingEntry(copy_entry(current_entry), len(input_broadcast_tags)))
            sent += 1

        await RisingEdge(dut.clock)

        if received == n_items:
            break

    assert received == n_items, (
        f"timed out after receiving {received}/{n_items}; sent={sent}; seed={seed:#x}"
    )
