"""Randomized cocotb test for PacketArbiter."""

from collections import deque
from dataclasses import dataclass
import json
from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.queue import Queue
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet import test_utils
from zamlet.message import Header, MessageType, SendType
from zamlet.params import ZamletParams


N_INPUTS = 2


@dataclass(frozen=True)
class Word:
    is_header: bool
    data: int


@dataclass(frozen=True)
class Packet:
    input_idx: int
    packet_idx: int
    words: list[Word]


def load_params() -> ZamletParams:
    test_params = test_utils.get_test_params()
    with open(test_params["params_file"], encoding="utf-8") as f:
        return ZamletParams.from_dict(json.load(f))


def make_header(params: ZamletParams, input_idx: int, packet_idx: int,
                length: int) -> Word:
    header = Header(
        target_x=packet_idx & ((1 << params.x_pos_width) - 1),
        target_y=input_idx,
        source_x=input_idx,
        source_y=(packet_idx >> params.x_pos_width) &
        ((1 << params.y_pos_width) - 1),
        length=length,
        message_type=MessageType.SEND,
        send_type=SendType.SINGLE,
    )
    return Word(is_header=True, data=header.encode(params))


def make_body_word(params: ZamletParams, input_idx: int, packet_idx: int,
                   body_idx: int, rng: Random) -> Word:
    tag = ((input_idx & 0xFF) << 24) | ((packet_idx & 0xFFFF) << 8) | body_idx
    data = ((rng.getrandbits(params.word_width) << 32) ^ tag) & (
        (1 << params.word_width) - 1)
    return Word(is_header=False, data=data)


def make_packets(params: ZamletParams, rng: Random,
                 packets_per_input: int) -> list[list[Packet]]:
    packets: list[list[Packet]] = []
    max_length = (1 << params.message_length_width) - 1
    for input_idx in range(N_INPUTS):
        input_packets = []
        for packet_idx in range(packets_per_input):
            length = 8 if packet_idx % 5 == 0 else rng.randrange(max_length + 1)
            words = [make_header(params, input_idx, packet_idx, length)]
            words.extend(
                make_body_word(params, input_idx, packet_idx, body_idx, rng)
                for body_idx in range(length)
            )
            input_packets.append(Packet(input_idx, packet_idx, words))
        packets.append(input_packets)
    return packets


def drive_word(dut: HierarchyObject, input_idx: int, word: Word) -> None:
    getattr(dut, f"io_in_{input_idx}_bits_isHeader").value = int(word.is_header)
    getattr(dut, f"io_in_{input_idx}_bits_data").value = word.data


def set_input_valid(dut: HierarchyObject, input_idx: int, valid: bool) -> None:
    getattr(dut, f"io_in_{input_idx}_valid").value = int(valid)


def input_ready(dut: HierarchyObject, input_idx: int) -> bool:
    return bool(int(getattr(dut, f"io_in_{input_idx}_ready").value))


def output_word(dut: HierarchyObject) -> Word:
    return Word(
        is_header=bool(int(dut.io_out_bits_isHeader.value)),
        data=int(dut.io_out_bits_data.value),
    )


async def drive_input(dut: HierarchyObject, input_idx: int,
                      packets: list[Packet], rng: Random) -> None:
    set_input_valid(dut, input_idx, False)
    drive_word(dut, input_idx, Word(False, 0))
    await RisingEdge(dut.clock)

    for packet in packets:
        for word in packet.words:
            while rng.random() >= 0.75:
                set_input_valid(dut, input_idx, False)
                await RisingEdge(dut.clock)

            set_input_valid(dut, input_idx, True)
            drive_word(dut, input_idx, word)
            await ReadOnly()
            while not input_ready(dut, input_idx):
                await RisingEdge(dut.clock)
                await ReadOnly()
            await RisingEdge(dut.clock)

    set_input_valid(dut, input_idx, False)


async def receive_output(dut: HierarchyObject, rng: Random,
                         received: Queue[Word]) -> None:
    while True:
        dut.io_out_ready.value = int(rng.random() < 0.70)
        await ReadOnly()
        if int(dut.io_out_valid.value) and int(dut.io_out_ready.value):
            received.put_nowait(output_word(dut))
        await RisingEdge(dut.clock)


def find_packet_head(word: Word, pending: list[deque[Packet]]) -> int | None:
    for input_idx, queue in enumerate(pending):
        if queue and queue[0].words[0] == word:
            return input_idx
    return None


async def monitor_packets(received: Queue[Word], packets: list[list[Packet]],
                          seed: int) -> None:
    pending = [deque(input_packets) for input_packets in packets]
    output_input_idx: int | None = None
    output_word_idx = 0
    completed_packets = 0
    total_packets = sum(len(input_packets) for input_packets in packets)

    while completed_packets < total_packets:
        actual = await received.get()
        if output_input_idx is None:
            assert actual.is_header, (
                f"output body word while idle: {actual}; seed={seed}"
            )
            output_input_idx = find_packet_head(actual, pending)
            assert output_input_idx is not None, (
                f"output header not at any input queue head: {actual}; "
                f"seed={seed}"
            )
            output_word_idx = 1
        else:
            packet = pending[output_input_idx][0]
            expected = packet.words[output_word_idx]
            assert actual == expected, (
                f"packet {packet.packet_idx} input {output_input_idx} "
                f"word {output_word_idx}: expected={expected}, "
                f"actual={actual}; seed={seed}"
            )
            output_word_idx += 1

        assert output_input_idx is not None
        packet = pending[output_input_idx][0]
        if output_word_idx == len(packet.words):
            pending[output_input_idx].popleft()
            output_input_idx = None
            output_word_idx = 0
            completed_packets += 1


@cocotb.test()
async def test_random_packet_streams(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    params = load_params()
    seed = test_utils.get_test_params()["seed"]
    rng = Random(seed)
    packets = make_packets(params, rng, packets_per_input=80)
    received: Queue[Word] = Queue()

    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    for input_idx in range(N_INPUTS):
        set_input_valid(dut, input_idx, False)
        drive_word(dut, input_idx, Word(False, 0))
    dut.io_out_ready.value = 0

    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)

    drivers = [
        cocotb.start_soon(drive_input(
            dut, input_idx, packets[input_idx], Random(rng.getrandbits(64))))
        for input_idx in range(N_INPUTS)
    ]
    receiver = cocotb.start_soon(receive_output(
        dut, Random(rng.getrandbits(64)), received))
    monitor = cocotb.start_soon(monitor_packets(received, packets, seed))

    for driver in drivers:
        await driver
    await monitor
    receiver.kill()
