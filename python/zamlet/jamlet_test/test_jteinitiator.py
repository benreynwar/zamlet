import json
import logging
from collections import deque
from dataclasses import dataclass
from random import Random

import cocotb
from cocotb import clock
from cocotb.handle import HierarchyObject
from zamlet import test_utils
from zamlet.jamlet_test.jteinitiator_driver import JteInitiatorDriver
from zamlet.lane_order import LaneOrder
from zamlet.message import JteIHeader, MessageType, SendType
from zamlet.params import ZamletParams
from zamlet.test_utils import rising_edge
from zamlet.width_codes import ElementWidthCode, WidthFormatCode

logger = logging.getLogger(__name__)

MODE_INDEX_LOAD = 2
MODE_INDEX_STORE = 3

JTE_STATE_REQUEST_SENT = 3
JTE_STATE_COMPLETE = 4


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


@dataclass
class RandomInstrExpectation:
    instr: RandomInstr
    packets: list[list[object]]
    commit: dict[str, object]
    index_requests: list[int]
    tlb_requests: list[int]


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


def get_tlb_entry(
    tlb_table: dict[int, dict[str, int]],
    stripe_addr: int,
    params: ZamletParams,
    rnd: Random,
) -> dict[str, int]:
    if stripe_addr not in tlb_table:
        wfs = [
            wf for wf in [
                WidthFormatCode.WF8,
                WidthFormatCode.WF16,
                WidthFormatCode.WF32,
                WidthFormatCode.WF64,
            ] if bytes_from_ew(wf) <= params.word_bytes
        ]
        pstripe = rnd.randrange(1, 1 << 16)
        tlb_table[stripe_addr] = {
            'stripeAddr': pstripe,
            'ordering_wf': rnd.choice(wfs),
            'ordering_laneOrder': rnd.randrange(LaneOrder.count()),
        }
        logger.info('expected TLB add vstripe=%d pstripe=%d', stripe_addr, pstripe)
    return tlb_table[stripe_addr]


def expected_packets_for_instruction(
    instr: RandomInstr,
    content: list[int],
    tlb_table: dict[int, dict[str, int]],
    params: ZamletParams,
    lane_index: int,
    this_x: int,
    this_y: int,
    rnd: Random,
) -> tuple[list[list[object]], list[int]]:
    data_bytes = bytes_from_ew(instr.data_ew)
    index_bytes = bytes_from_ew(instr.index_ew)
    log2_ratio = instr.reg_wf - instr.data_ew
    packets = []
    index_requests = []
    tlb_requests = []
    last_index_req = None

    for element_index in range(instr.start_index, instr.end_index):
        ordinal = local_ordinal(element_index, lane_index, params.j_in_l, log2_ratio)
        if ordinal is None:
            continue
        index_req = instr.index_reg + (ordinal * index_bytes) // params.word_bytes
        if index_req != last_index_req:
            index_requests.append(index_req)
            last_index_req = index_req
        if instr.mask_enabled and not read_mask_bit(content, instr.mask_reg, ordinal):
            continue

        index_value = read_bytes(content, instr.index_reg, ordinal * index_bytes, index_bytes)
        element_vaddr = (instr.base_addr + index_value) & ((1 << params.mem_addr_width) - 1)
        element_reg_byte = ordinal * data_bytes
        remaining = data_bytes
        element_byte = 0
        last_tlb_vstripe = None

        while remaining:
            vaddr = element_vaddr + element_byte
            vstripe = vaddr // params.stripe_bytes
            if vstripe != last_tlb_vstripe:
                logger.info(
                    'expected TLB use instr=%s element_index=%d ordinal=%d element_byte=%d vaddr=%d vstripe=%d',
                    instr, element_index, ordinal, element_byte, vaddr, vstripe)
                tlb_requests.append(vstripe)
                last_tlb_vstripe = vstripe
            tlb_entry = get_tlb_entry(tlb_table, vstripe, params, rnd)
            paddr = tlb_entry['stripeAddr'] * params.stripe_bytes + (vaddr % params.stripe_bytes)
            pstripe = tlb_entry['stripeAddr']
            mem_wf_bytes = bytes_from_ew(tlb_entry['ordering_wf'])
            reg_byte = element_reg_byte + element_byte
            n_bytes = bytes_until_segment_boundary(
                vaddr, paddr, reg_byte, data_bytes, mem_wf_bytes, params)
            mem_wf_index = paddr >> log2_int(mem_wf_bytes)
            dst_index = mem_wf_index & (params.j_in_l - 1)
            dst_offset = ((dst_index * mem_wf_bytes) + (paddr % mem_wf_bytes)) % params.word_bytes
            src_offset = reg_byte % params.word_bytes
            is_store = instr.mode == MODE_INDEX_STORE
            header = JteIHeader(
                dst_index=dst_index,
                source_x=this_x,
                source_y=this_y,
                length=2 if is_store else 1,
                message_type=(
                    MessageType.STORE_WORD_REQ
                    if is_store
                    else MessageType.LOAD_WORD_REQ
                ),
                send_type=SendType.SINGLE,
                ident=0,
                n_bytes=n_bytes,
                dst_offset=dst_offset,
                src_offset=src_offset,
                slot=0,
            )
            packet = [header, pstripe]
            if is_store:
                body = read_bytes(content, instr.data_reg, reg_byte, n_bytes) << (8 * dst_offset)
                packet.append(body)
            packets.append(packet)
            remaining -= n_bytes
            element_byte += n_bytes

    return packets, index_requests, tlb_requests


def expected_commit_for_packets(packets: list[list[object]], params: ZamletParams) -> dict[str, object]:
    initiator = [JTE_STATE_COMPLETE] * params.word_bytes
    for packet in packets:
        initiator[packet[0].src_offset] = JTE_STATE_REQUEST_SENT
    return {
        'slot': 0,
        'initiator': initiator,
    }


def make_random_instr_expectation(
    rnd: Random,
    params: ZamletParams,
    content: list[int],
    tlb_table: dict[int, dict[str, int]],
    lane_index: int,
    this_x: int,
    this_y: int,
) -> RandomInstrExpectation:
    instr = make_random_instruction(rnd, params, lane_index)
    packets, index_requests, tlb_requests = expected_packets_for_instruction(
        instr, content, tlb_table, params, lane_index, this_x, this_y, rnd)
    commit = expected_commit_for_packets(packets, params)
    return RandomInstrExpectation(
        instr=instr, packets=packets, commit=commit,
        index_requests=index_requests, tlb_requests=tlb_requests)


def make_random_instruction(
    rnd: Random,
    params: ZamletParams,
    lane_index: int,
) -> RandomInstr:
    mode = rnd.choice([MODE_INDEX_LOAD, MODE_INDEX_STORE])
    data_ew = rnd.choice([
        ElementWidthCode.EW8,
        ElementWidthCode.EW16,
        ElementWidthCode.EW32,
        ElementWidthCode.EW64,
    ])
    index_ew = rnd.choice([
        ElementWidthCode.EW8,
        ElementWidthCode.EW16,
        ElementWidthCode.EW32,
        ElementWidthCode.EW64,
    ])
    max_log2_ratio = min(
        WidthFormatCode.WF64 - data_ew,
        WidthFormatCode.WF64 - index_ew)
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


async def consume_and_check_packets(
    driver: JteInitiatorDriver,
    params: ZamletParams,
    packets_received: deque[list[object]],
    packets_expected: deque[tuple[RandomInstr, list[object]]],
) -> None:
    while True:
        while not driver.packet.queue:
            await rising_edge(driver.clock)
        word = driver.packet.pop()
        assert word["isHeader"] == 1
        header = JteIHeader.decode(word["data"], params)
        packet = [header]
        for _ in range(header.length):
            while not driver.packet.queue:
                await rising_edge(driver.clock)
            packet.append(driver.packet.pop()["data"])

        packets_received.append(packet)
        assert packets_expected, f'unexpected packet received: {packet}'
        instr, expected_packet = packets_expected.popleft()
        assert packet == expected_packet, (
            f'instruction {instr} packet mismatch\n'
            f'actual:   {packet}\n'
            f'expected: {expected_packet}'
        )


async def consume_and_check_commits(
    driver: JteInitiatorDriver,
    commits_received: deque[dict[str, object]],
    commits_expected: deque[tuple[RandomInstr, dict[str, object]]],
    params: ZamletParams,
) -> None:
    commit_index = 0
    while True:
        while not driver.commit.queue:
            await rising_edge(driver.clock)
        item = driver.commit.pop()
        commit = {
            'slot': item['teIndex'],
            'initiator': [
                item[f'initiator_{i}']
                for i in range(params.word_bytes)
            ],
        }
        commits_received.append(commit)
        assert commits_expected, f'unexpected commit received: {commit}'
        instr, expected_commit = commits_expected.popleft()
        logger.info(
            'commit %d actual=%s expected_instr=%s expected=%s',
            commit_index, commit, instr, expected_commit)
        assert commit == expected_commit, (
            f'instruction {instr} commit mismatch\n'
            f'actual:   {commit}\n'
            f'expected: {expected_commit}'
        )
        commit_index += 1


async def wait_for_packets(dut: HierarchyObject, packets: deque[list[object]], n_packets: int, timeout_cycles=500):
    for _ in range(timeout_cycles):
        if len(packets) >= n_packets:
            return
        await rising_edge(dut.clock)
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
        await rising_edge(dut.clock)
    assert len(commits) >= n_commits, f'timed out waiting for {n_commits} commits, got {len(commits)}'


def summarize_expected_packets(packets_expected: deque[tuple[RandomInstr, list[object]]]) -> str:
    summary = []
    current_instr = None
    current_count = 0
    for instr, _ in packets_expected:
        if instr != current_instr:
            if current_instr is not None:
                summary.append(f'{current_instr}: {current_count}')
            current_instr = instr
            current_count = 1
        else:
            current_count += 1
    if current_instr is not None:
        summary.append(f'{current_instr}: {current_count}')
    return '\n'.join(summary[:10])


@cocotb.test()
async def jteinitiator_random_test(dut: HierarchyObject) -> None:
    rnd = Random(100)
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.get_test_params()
    with open(test_params['params_file']) as f:
        params = ZamletParams.from_dict(json.load(f))

    this_x = 2
    this_y = 3
    lane_index = 0
    driver = JteInitiatorDriver(dut, params, this_x, this_y, lane_index)

    cocotb.start_soon(clock.Clock(dut.clock, 2, 'ns').start())

    packets_received = deque()
    commits_received = deque()
    content = [rnd.randrange(0, 1 << params.word_width) for _ in range(params.rf_slice_words)]
    tlb_table = {}
    n_instructions = 1000
    expectations = [
        make_random_instr_expectation(
            rnd, params, content, tlb_table, lane_index, this_x, this_y)
        for _ in range(n_instructions)
    ]
    for i, expectation in enumerate(expectations):
        logger.info(
            'expected packets instruction %d instr=%s n_packets=%d',
            i, expectation.instr, len(expectation.packets))
        logger.info(
            'expected index requests instruction %d: %s',
            i, expectation.index_requests)
        for j, packet in enumerate(expectation.packets):
            logger.info('expected packet instruction %d packet %d: %s', i, j, packet)
    instrs_to_send = deque(expectation.instr for expectation in expectations)
    packets_expected = deque(
        (expectation.instr, packet)
        for expectation in expectations
        for packet in expectation.packets
    )
    commits_expected = deque(
        (expectation.instr, expectation.commit)
        for expectation in expectations
    )
    for i, (instr, commit) in enumerate(commits_expected):
        logger.info('expected commit %d instr=%s commit=%s', i, instr, commit)
    index_requests_expected = deque(
        (i, expectation.instr, request)
        for i, expectation in enumerate(expectations)
        for request in expectation.index_requests
    )
    tlb_requests_expected = deque(
        request
        for expectation in expectations
        for request in expectation.tlb_requests
    )
    n_expected_packets = len(packets_expected)
    n_expected_commits = len(commits_expected)

    driver.start(rnd, content, tlb_table, index_requests_expected, tlb_requests_expected)
    cocotb.start_soon(consume_and_check_packets(
        driver, params, packets_received, packets_expected))
    cocotb.start_soon(consume_and_check_commits(driver, commits_received, commits_expected, params))

    dut.reset.value = 1
    await rising_edge(dut.clock)
    dut.reset.value = 0
    await rising_edge(dut.clock)

    driver.enqueue_instructions(instrs_to_send)
    try:
        await wait_for_packets(
            dut, packets_received, n_expected_packets,
            timeout_cycles=100 + 20 * n_expected_packets)
    except AssertionError as exc:
        raise AssertionError(
            f'{exc}\nremaining expected packets by instruction:\n'
            f'{summarize_expected_packets(packets_expected)}'
        ) from exc
    await wait_for_commits(dut, commits_received, n_expected_commits)
    assert not index_requests_expected, f'missing expected index requests: {list(index_requests_expected)}'
    assert not tlb_requests_expected, f'missing expected TLB requests: {list(tlb_requests_expected)}'
    assert not packets_expected, f'missing expected packets: {list(packets_expected)}'
    assert not commits_expected, f'missing expected commits: {list(commits_expected)}'
