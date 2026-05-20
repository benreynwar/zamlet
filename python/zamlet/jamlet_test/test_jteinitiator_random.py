import json
import logging
from collections import deque
from dataclasses import dataclass
from random import Random

import cocotb
from cocotb import clock, triggers
from cocotb.handle import HierarchyObject

from zamlet import test_utils
from zamlet.params import ZamletParams


logger = logging.getLogger(__name__)

EW8 = 3
EW16 = 4
EW32 = 5
EW64 = 6

WF8 = 3
WF16 = 4
WF32 = 5
WF64 = 6

MODE_INDEX_LOAD = 2
MODE_INDEX_STORE = 3

MSG_READ = 1
MSG_WRITE = 2

JTE_STATE_REQUEST_SENT = 3
JTE_STATE_COMPLETE = 4
JTE_WALK_NEEDS_PROCESSING = 0
JTE_WALK_DONE = 2


@dataclass
class RandomInstr:
    mode: int
    base_addr: int
    data_ew: int
    index_ew: int
    reg_wf: int
    data_reg: int
    index_reg: int
    mask_reg: int
    mask_enabled: bool
    start_index: int
    end_index: int


def log2_int(value: int) -> int:
    assert value > 0 and value & (value - 1) == 0
    return value.bit_length() - 1


def bytes_from_ew(ew: int) -> int:
    return 1 << (ew - 3)


def local_ordinal(element_index: int, lane_index: int, j_in_l: int, log2_ratio: int) -> int | None:
    ratio = 1 << log2_ratio
    lane = (element_index >> log2_ratio) % j_in_l
    if lane != lane_index:
        return None
    return (element_index // (j_in_l * ratio)) * ratio + (element_index & (ratio - 1))


def read_bytes(content: list[int], reg: int, byte_offset: int, n_bytes: int) -> int:
    result = 0
    for i in range(n_bytes):
        absolute_byte = byte_offset + i
        word = content[reg + absolute_byte // 8]
        byte = (word >> (8 * (absolute_byte % 8))) & 0xff
        result |= byte << (8 * i)
    return result


def read_mask_bit(content: list[int], mask_reg: int, ordinal: int) -> int:
    return (content[mask_reg + ordinal // 64] >> (ordinal % 64)) & 1


def header_from_int(value: int) -> dict[str, int]:
    return {
        'dst_index': (value >> 48) & 0xffff,
        'src_x': (value >> 40) & 0xff,
        'src_y': (value >> 32) & 0xff,
        'msg_type': (value >> 26) & 0x3f,
        'msg_length': (value >> 22) & 0xf,
        'n_bytes': (value >> 19) & 0x7,
        'dst_offset': (value >> 16) & 0x7,
        'src_offset': (value >> 13) & 0x7,
    }


def bytes_until_segment_boundary(
    vaddr: int,
    paddr: int,
    reg_byte: int,
    data_bytes: int,
    mem_wf_bytes: int,
    params: ZamletParams,
) -> int:
    return min(
        params.page_bytes - (vaddr % params.page_bytes),
        params.stripe_bytes - (paddr % params.stripe_bytes),
        params.word_bytes - (paddr % params.word_bytes),
        mem_wf_bytes - (paddr % mem_wf_bytes),
        params.word_bytes - (reg_byte % params.word_bytes),
        data_bytes - (reg_byte % data_bytes),
    )


def memory_word_position(paddr: int, wf: int, params: ZamletParams) -> tuple[int, int]:
    wf_bytes = bytes_from_ew(wf)
    dst_index = (paddr >> log2_int(wf_bytes)) & (params.j_in_l - 1)
    if wf_bytes >= params.word_bytes:
        dst_offset = paddr % params.word_bytes
    else:
        wf_index = paddr >> log2_int(wf_bytes)
        dst_offset = ((wf_index & (params.j_in_l - 1)) << log2_int(wf_bytes)) + (paddr % wf_bytes)
    return dst_index, dst_offset


def make_ordering(orderings: dict[int, dict[str, int]], stripe_addr: int, rnd: Random) -> dict[str, int]:
    if stripe_addr not in orderings:
        orderings[stripe_addr] = {'wf': rnd.choice([WF8, WF16, WF32, WF64]), 'laneOrder': 0}
    return orderings[stripe_addr]


def make_translation(page_table: dict[int, int], vpage: int, rnd: Random) -> int:
    if vpage not in page_table:
        page_table[vpage] = rnd.randrange(1, 1 << 16)
    return page_table[vpage]


def expected_packets_for_instruction(
    instr: RandomInstr,
    content: list[int],
    page_table: dict[int, int],
    orderings: dict[int, dict[str, int]],
    params: ZamletParams,
    lane_index: int,
    this_x: int,
    this_y: int,
    rnd: Random,
) -> list[list[object]]:
    data_bytes = bytes_from_ew(instr.data_ew)
    index_bytes = bytes_from_ew(instr.index_ew)
    log2_ratio = instr.reg_wf - instr.data_ew
    packets = []

    for element_index in range(instr.start_index, instr.end_index):
        ordinal = local_ordinal(element_index, lane_index, params.j_in_l, log2_ratio)
        if ordinal is None:
            continue
        if instr.mask_enabled and not read_mask_bit(content, instr.mask_reg, ordinal):
            continue

        index_value = read_bytes(content, instr.index_reg, ordinal * index_bytes, index_bytes)
        element_vaddr = instr.base_addr + index_value
        element_reg_byte = ordinal * data_bytes
        remaining = data_bytes
        element_byte = 0

        while remaining:
            vaddr = element_vaddr + element_byte
            vpage = vaddr // params.page_bytes
            ppage = make_translation(page_table, vpage, rnd)
            paddr = ppage * params.page_bytes + (vaddr % params.page_bytes)
            vstripe = vaddr // params.stripe_bytes
            pstripe = paddr // params.stripe_bytes
            ordering = make_ordering(orderings, vstripe, rnd)
            mem_wf_bytes = bytes_from_ew(ordering['wf'])
            reg_byte = element_reg_byte + element_byte
            n_bytes = bytes_until_segment_boundary(
                vaddr, paddr, reg_byte, data_bytes, mem_wf_bytes, params)
            dst_index, dst_offset = memory_word_position(paddr, ordering['wf'], params)
            src_offset = reg_byte % params.word_bytes
            is_store = instr.mode == MODE_INDEX_STORE
            header = {
                'dst_index': dst_index,
                'src_x': this_x,
                'src_y': this_y,
                'msg_type': MSG_WRITE if is_store else MSG_READ,
                'msg_length': 2 if is_store else 1,
                'n_bytes': n_bytes,
                'dst_offset': dst_offset,
                'src_offset': src_offset,
            }
            packet = [header, pstripe]
            if is_store:
                body = read_bytes(content, instr.data_reg, reg_byte, n_bytes) << (8 * dst_offset)
                packet.append(body)
            packets.append(packet)
            remaining -= n_bytes
            element_byte += n_bytes

    return packets


def expected_commit_for_packets(packets: list[list[object]], params: ZamletParams) -> dict[str, object]:
    initiator = [JTE_STATE_COMPLETE] * params.word_bytes
    for packet in packets:
        initiator[packet[0]['src_offset']] = JTE_STATE_REQUEST_SENT
    return {
        'slot': 0,
        'initiator': initiator,
        'walkState': JTE_WALK_NEEDS_PROCESSING if packets else JTE_WALK_DONE,
    }


def make_random_instruction(
    rnd: Random,
    params: ZamletParams,
    lane_index: int,
) -> RandomInstr:
    mode = rnd.choice([MODE_INDEX_LOAD, MODE_INDEX_STORE])
    data_ew = rnd.choice([EW8, EW16, EW32, EW64])
    index_ew = rnd.choice([EW8, EW16, EW32, EW64])
    max_log2_ratio = min(WF64 - data_ew, WF64 - index_ew)
    log2_ratio = rnd.randrange(0, max_log2_ratio + 1)
    reg_wf = data_ew + log2_ratio
    elements_per_data_word = params.word_bytes // bytes_from_ew(data_ew)
    max_element_index = params.j_in_l * elements_per_data_word
    start_index = rnd.randrange(0, max_element_index)
    end_index = rnd.randrange(start_index + 1, max_element_index + 1)

    max_ordinal = elements_per_data_word - 1
    max_data_regs = (max_ordinal * bytes_from_ew(data_ew)) // params.word_bytes + 1
    max_index_regs = (max_ordinal * bytes_from_ew(index_ew)) // params.word_bytes + 1
    max_mask_regs = max_ordinal // (params.word_bytes * 8) + 1

    data_reg = rnd.randrange(0, params.rf_slice_words - max_data_regs)
    index_reg = rnd.randrange(0, params.rf_slice_words - max_index_regs)
    mask_reg = rnd.randrange(0, params.rf_slice_words - max_mask_regs)

    base_addr = rnd.randrange(0, params.page_bytes * 8)
    mask_enabled = bool(rnd.randrange(2))

    return RandomInstr(
        mode=mode,
        base_addr=base_addr,
        data_ew=data_ew,
        index_ew=index_ew,
        reg_wf=reg_wf,
        data_reg=data_reg,
        index_reg=index_reg,
        mask_reg=mask_reg,
        mask_enabled=mask_enabled,
        start_index=start_index,
        end_index=end_index,
    )


async def send_dispatch(dut: HierarchyObject, dispatch_queue: deque[RandomInstr]) -> None:
    dut.io_input_valid.value = 0
    await triggers.RisingEdge(dut.clock)
    while True:
        await triggers.ReadOnly()
        dispatch_ready = int(dut.io_input_ready.value)
        await triggers.RisingEdge(dut.clock)
        if dispatch_queue and dispatch_ready:
            instr = dispatch_queue.popleft()
            dut.io_input_valid.value = 1
            dut.io_input_bits_slot.value = 0
            dut.io_input_bits_instrIdent.value = 0
            dut.io_input_bits_mode.value = instr.mode
            dut.io_input_bits_baseAddr.value = instr.base_addr
            dut.io_input_bits_stride.value = 0
            dut.io_input_bits_startIndex.value = instr.start_index
            dut.io_input_bits_endIndex.value = instr.end_index
            dut.io_input_bits_dataReg.value = instr.data_reg
            dut.io_input_bits_indexReg.value = instr.index_reg
            dut.io_input_bits_maskReg.value = instr.mask_reg
            dut.io_input_bits_maskEnabled.value = int(instr.mask_enabled)
            dut.io_input_bits_rfLaneOrder.value = 0
            dut.io_input_bits_rfDataWF.value = instr.reg_wf
            dut.io_input_bits_rfDataEW.value = instr.data_ew
            dut.io_input_bits_rfIndexEW.value = instr.index_ew
        elif dispatch_ready:
            dut.io_input_valid.value = 0


async def req_resp_handler(dut, req_prefix: str, resp_prefix: str, mapping):
    await triggers.RisingEdge(dut.clock)
    addr_queue = deque()
    popped_addr = None
    getattr(dut, req_prefix + 'ready').value = 1
    getattr(dut, resp_prefix + 'valid').value = 0
    while True:
        await triggers.ReadOnly()
        req_fire = int(getattr(dut, req_prefix + 'valid').value) and int(getattr(dut, req_prefix + 'ready').value)
        req_addr = int(getattr(dut, req_prefix + 'bits').value)
        resp_fire = popped_addr is not None and int(getattr(dut, resp_prefix + 'ready').value)
        if req_fire:
            addr_queue.append(req_addr)
        if resp_fire:
            popped_addr = None
        await triggers.RisingEdge(dut.clock)
        getattr(dut, req_prefix + 'ready').value = int(len(addr_queue) < 2)
        if popped_addr is None and addr_queue:
            popped_addr = addr_queue.popleft()
        getattr(dut, resp_prefix + 'valid').value = int(popped_addr is not None)
        if popped_addr is not None:
            if isinstance(mapping, list):
                assert 0 <= popped_addr < len(mapping), (
                    f'{req_prefix} requested out-of-range RF address {popped_addr}'
                )
            elif popped_addr not in mapping:
                raise AssertionError(f'{req_prefix} requested unmapped address {popped_addr}')
            mapped = mapping[popped_addr]
            if isinstance(mapped, dict):
                for key, value in mapped.items():
                    getattr(dut, resp_prefix + 'bits_' + key).value = value
            else:
                getattr(dut, resp_prefix + 'bits').value = mapped


async def consume_packets(dut: HierarchyObject, packets: deque[list[object]]) -> None:
    dut.io_packet_ready.value = 1
    await triggers.ReadOnly()
    while True:
        while not int(dut.io_packet_valid.value):
            await triggers.RisingEdge(dut.clock)
            await triggers.ReadOnly()
        assert int(dut.io_packet_bits_isHeader.value) == 1
        header = header_from_int(int(dut.io_packet_bits_bits.value))
        packet = [header]
        await triggers.RisingEdge(dut.clock)
        await triggers.ReadOnly()
        for _ in range(header['msg_length']):
            while not int(dut.io_packet_valid.value):
                await triggers.RisingEdge(dut.clock)
                await triggers.ReadOnly()
            packet.append(int(dut.io_packet_bits_bits.value))
            await triggers.RisingEdge(dut.clock)
            await triggers.ReadOnly()
        packets.append(packet)


async def consume_commits(
    dut: HierarchyObject,
    commits: deque[dict[str, object]],
    params: ZamletParams,
) -> None:
    await triggers.ReadOnly()
    while True:
        while not int(dut.io_commit_valid.value):
            await triggers.RisingEdge(dut.clock)
            await triggers.ReadOnly()
        commits.append({
            'slot': int(dut.io_commit_bits_slot.value),
            'initiator': [
                int(getattr(dut, f'io_commit_bits_initiator_{i}').value)
                for i in range(params.word_bytes)
            ],
            'walkState': int(dut.io_commit_bits_walkState.value),
        })
        await triggers.RisingEdge(dut.clock)
        await triggers.ReadOnly()


async def wait_for_packets(dut: HierarchyObject, packets: deque[list[object]], n_packets: int, timeout_cycles=500):
    for _ in range(timeout_cycles):
        if len(packets) >= n_packets:
            return
        await triggers.RisingEdge(dut.clock)
    assert len(packets) >= n_packets, f'timed out waiting for {n_packets} packets, got {len(packets)}'


async def wait_for_commits(
    dut: HierarchyObject,
    commits: deque[dict[str, object]],
    n_commits: int,
    timeout_cycles=500,
) -> None:
    for _ in range(timeout_cycles):
        if len(commits) >= n_commits:
            return
        await triggers.RisingEdge(dut.clock)
    assert len(commits) >= n_commits, f'timed out waiting for {n_commits} commits, got {len(commits)}'


async def do_random_instruction(
    rnd: Random,
    dut: HierarchyObject,
    params: ZamletParams,
    dispatch_queue: deque[RandomInstr],
    packets: deque[list[object]],
    commits: deque[dict[str, object]],
    content: list[int],
    page_table: dict[int, int],
    orderings: dict[int, dict[str, int]],
    lane_index: int,
    this_x: int,
    this_y: int,
) -> None:
    instr = make_random_instruction(rnd, params, lane_index)
    expected = expected_packets_for_instruction(
        instr, content, page_table, orderings, params, lane_index, this_x, this_y, rnd)
    expected_commit = expected_commit_for_packets(expected, params)
    dispatch_queue.append(instr)
    await wait_for_packets(dut, packets, len(expected))
    await wait_for_commits(dut, commits, 1)
    actual = [packets.popleft() for _ in expected]
    actual_commit = commits.popleft()
    if actual != expected:
        for i, (actual_packet, expected_packet) in enumerate(zip(actual, expected)):
            if actual_packet != expected_packet:
                raise AssertionError(
                    f'instruction {instr} packet {i} mismatch\n'
                    f'actual:   {actual_packet}\n'
                    f'expected: {expected_packet}\n'
                    f'n_actual={len(actual)} n_expected={len(expected)}'
                )
        raise AssertionError(
            f'instruction {instr} packet count/order mismatch\n'
            f'actual:   {actual}\n'
            f'expected: {expected}'
        )
    assert actual_commit == expected_commit, (
        f'instruction {instr} commit mismatch\n'
        f'actual:   {actual_commit}\n'
        f'expected: {expected_commit}'
    )


@cocotb.test()
async def jteinitiator_random_test(dut: HierarchyObject) -> None:
    rnd = Random(1)
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.get_test_params()
    with open(test_params['params_file']) as f:
        params = ZamletParams.from_dict(json.load(f))

    this_x = 2
    this_y = 3
    lane_index = 0
    dut.io_x.value = this_x
    dut.io_y.value = this_y
    dut.io_laneIndex.value = lane_index

    cocotb.start_soon(clock.Clock(dut.clock, 2, 'ns').start())

    dispatch_queue = deque()
    packets = deque()
    commits = deque()
    content = [rnd.randrange(0, 1 << params.word_width) for _ in range(params.rf_slice_words)]
    page_table = {}
    orderings = {}

    cocotb.start_soon(send_dispatch(dut, dispatch_queue))
    cocotb.start_soon(req_resp_handler(dut, 'io_rfIndexReq_', 'io_rfIndexResp_', content))
    cocotb.start_soon(req_resp_handler(dut, 'io_rfDataReq_', 'io_rfDataResp_', content))
    cocotb.start_soon(req_resp_handler(dut, 'io_rfMaskReq_', 'io_rfMaskResp_', content))
    cocotb.start_soon(req_resp_handler(dut, 'io_tlbReq_', 'io_tlbResp_', page_table))
    cocotb.start_soon(req_resp_handler(dut, 'io_orderingReq_', 'io_orderingResp_', orderings))
    cocotb.start_soon(consume_packets(dut, packets))
    cocotb.start_soon(consume_commits(dut, commits, params))

    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)

    for _ in range(1):
        await do_random_instruction(
            rnd, dut, params, dispatch_queue, packets, commits, content, page_table,
            orderings, lane_index, this_x, this_y)
