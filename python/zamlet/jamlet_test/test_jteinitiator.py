import json
import logging
from collections import deque
from dataclasses import dataclass
from random import Random

import cocotb
from cocotb import clock, triggers
from cocotb.handle import HierarchyObject

from zamlet import test_utils, utils
from zamlet.lane_order import LaneOrder
from zamlet.message import JteIHeader, MessageType, SendType
from zamlet.params import ZamletParams
from zamlet.width_codes import ElementWidthCode, WidthFormatCode


logger = logging.getLogger(__name__)

MODE_INDEX_LOAD = 2
MODE_INDEX_STORE = 3

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


def make_ordering(
    orderings: dict[int, dict[str, int]],
    stripe_addr: int,
    params: ZamletParams,
    rnd: Random,
) -> dict[str, int]:
    if stripe_addr not in orderings:
        wfs = [
            wf for wf in [
                WidthFormatCode.WF8,
                WidthFormatCode.WF16,
                WidthFormatCode.WF32,
                WidthFormatCode.WF64,
            ] if bytes_from_ew(wf) <= params.word_bytes
        ]
        orderings[stripe_addr] = {'wf': rnd.choice(wfs), 'laneOrder': 0}
    return orderings[stripe_addr]


def make_translation(page_table: dict[int, int], vpage: int, rnd: Random) -> int:
    if vpage not in page_table:
        page_table[vpage] = rnd.randrange(1, 1 << 16)
        logger.info('expected TLB add vpage=%d ppage=%d', vpage, page_table[vpage])
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
        last_tlb_vpage = None

        while remaining:
            vaddr = element_vaddr + element_byte
            vpage = vaddr // params.page_bytes
            if vpage != last_tlb_vpage:
                logger.info(
                    'expected TLB use instr=%s element_index=%d ordinal=%d element_byte=%d vaddr=%d vpage=%d',
                    instr, element_index, ordinal, element_byte, vaddr, vpage)
                tlb_requests.append(vpage)
                last_tlb_vpage = vpage
            ppage = make_translation(page_table, vpage, rnd)
            paddr = ppage * params.page_bytes + (vaddr % params.page_bytes)
            vstripe = vaddr // params.stripe_bytes
            pstripe = paddr // params.stripe_bytes
            ordering = make_ordering(orderings, vstripe, params, rnd)
            mem_wf_bytes = bytes_from_ew(ordering['wf'])
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
        'walkState': JTE_WALK_NEEDS_PROCESSING if packets else JTE_WALK_DONE,
    }


def make_random_instr_expectation(
    rnd: Random,
    params: ZamletParams,
    content: list[int],
    page_table: dict[int, int],
    orderings: dict[int, dict[str, int]],
    lane_index: int,
    this_x: int,
    this_y: int,
) -> RandomInstrExpectation:
    instr = make_random_instruction(rnd, params, lane_index)
    packets, index_requests, tlb_requests = expected_packets_for_instruction(
        instr, content, page_table, orderings, params, lane_index, this_x, this_y, rnd)
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


async def send_dispatch(rnd: Random, dut: HierarchyObject, dispatch_queue: deque[RandomInstr], p_valid: float = 0.5) -> None:
    instr = None
    await triggers.RisingEdge(dut.clock)
    while True:
        if instr is None and dispatch_queue:
            instr = dispatch_queue.popleft()
        if instr is not None:
            valid = rnd.random() < p_valid
        else:
            valid = False
        if valid:
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
            dut.io_input_bits_rfLaneOrder.value = LaneOrder.MOORE
            dut.io_input_bits_rfDataWF.value = instr.reg_wf
            dut.io_input_bits_rfDataEW.value = instr.data_ew
            dut.io_input_bits_rfIndexEW.value = instr.index_ew
        else:
            dut.io_input_valid.value = 0
        await triggers.ReadOnly()
        dispatch_ready = int(dut.io_input_ready.value)
        if dispatch_ready and valid:
            instr = None
        await triggers.RisingEdge(dut.clock)


async def req_resp_handler(
    dut,
    req_prefix: str,
    resp_prefix: str,
    mapping,
    expected_requests: deque[object] | None = None,
):
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
            logger.info('%s request address %d', req_prefix, popped_addr)
            if expected_requests is not None:
                assert expected_requests, f'{req_prefix} unexpected request address {popped_addr}'
                expected_request = expected_requests.popleft()
                if isinstance(expected_request, tuple):
                    expected_instr_index, expected_instr, expected_addr = expected_request
                    expected_context = (
                        f'\nexpected instruction index: {expected_instr_index}'
                        f'\nexpected instruction: {expected_instr}'
                    )
                else:
                    expected_addr = expected_request
                    expected_context = ''
                assert popped_addr == expected_addr, (
                    f'{req_prefix} request mismatch\n'
                    f'actual:   {popped_addr}\n'
                    f'expected: {expected_addr}'
                    f'{expected_context}'
                )
        getattr(dut, resp_prefix + 'valid').value = int(popped_addr is not None)
        if popped_addr is not None:
            if isinstance(mapping, list):
                assert 0 <= popped_addr < len(mapping), (
                    f'{req_prefix} requested out-of-range RF address {popped_addr}'
                )
            elif popped_addr not in mapping:
                logger.info('expected mapping for %s: %s', req_prefix, mapping)
                raise AssertionError(f'{req_prefix} requested unmapped address {popped_addr}')
            mapped = mapping[popped_addr]
            if isinstance(mapped, dict):
                for key, value in mapped.items():
                    getattr(dut, resp_prefix + 'bits_' + key).value = value
            else:
                getattr(dut, resp_prefix + 'bits').value = mapped


async def random_packet_ready(rnd: Random, dut: HierarchyObject):
    while True:
        await triggers.RisingEdge(dut.clock)
        dut.io_packet_ready.value = rnd.randint(0, 1)

async def consume_and_check_packets(
    rnd: Random,
    dut: HierarchyObject,
    params: ZamletParams,
    packets_received: deque[list[object]],
    packets_expected: deque[tuple[RandomInstr, list[object]]],
) -> None:
    await triggers.ReadOnly()
    while True:
        while not (int(dut.io_packet_valid.value) and int(dut.io_packet_ready.value)):
            await triggers.RisingEdge(dut.clock)
            await triggers.ReadOnly()
        assert int(dut.io_packet_bits_isHeader.value) == 1
        header = JteIHeader.decode(int(dut.io_packet_bits_data.value), params)
        packet = [header]
        await triggers.RisingEdge(dut.clock)
        await triggers.ReadOnly()
        for _ in range(header.length):
            while not (int(dut.io_packet_valid.value) and int(dut.io_packet_ready.value)):
                await triggers.RisingEdge(dut.clock)
                await triggers.ReadOnly()
            packet.append(int(dut.io_packet_bits_data.value))
            await triggers.RisingEdge(dut.clock)
            await triggers.ReadOnly()

        packets_received.append(packet)
        assert packets_expected, f'unexpected packet received: {packet}'
        instr, expected_packet = packets_expected.popleft()
        assert packet == expected_packet, (
            f'instruction {instr} packet mismatch\n'
            f'actual:   {packet}\n'
            f'expected: {expected_packet}'
        )


async def consume_and_check_commits(
    dut: HierarchyObject,
    commits_received: deque[dict[str, object]],
    commits_expected: deque[tuple[RandomInstr, dict[str, object]]],
    params: ZamletParams,
) -> None:
    commit_index = 0
    await triggers.ReadOnly()
    while True:
        while not int(dut.io_commit_valid.value):
            await triggers.RisingEdge(dut.clock)
            await triggers.ReadOnly()
        commit = {
            'slot': int(dut.io_commit_bits_slot.value),
            'initiator': [
                int(getattr(dut, f'io_commit_bits_initiator_{i}').value)
                for i in range(params.word_bytes)
            ],
            'walkState': int(dut.io_commit_bits_walkState.value),
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
    dut.io_x.value = this_x
    dut.io_y.value = this_y
    dut.io_laneIndex.value = lane_index

    cocotb.start_soon(clock.Clock(dut.clock, 2, 'ns').start())

    dispatch_queue = deque()
    packets_received = deque()
    commits_received = deque()
    content = [rnd.randrange(0, 1 << params.word_width) for _ in range(params.rf_slice_words)]
    page_table = {}
    orderings = {}
    n_instructions = 1000
    expectations = [
        make_random_instr_expectation(
            rnd, params, content, page_table, orderings, lane_index, this_x, this_y)
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

    cocotb.start_soon(send_dispatch(utils.create_rng(rnd), dut, dispatch_queue))
    cocotb.start_soon(req_resp_handler(
        dut, 'io_rfIndexReq_', 'io_rfIndexResp_', content, index_requests_expected))
    cocotb.start_soon(req_resp_handler(dut, 'io_rfDataReq_', 'io_rfDataResp_', content))
    cocotb.start_soon(req_resp_handler(dut, 'io_rfMaskReq_', 'io_rfMaskResp_', content))
    cocotb.start_soon(req_resp_handler(
        dut, 'io_tlbReq_', 'io_tlbResp_', page_table, tlb_requests_expected))
    cocotb.start_soon(req_resp_handler(dut, 'io_orderingReq_', 'io_orderingResp_', orderings))
    cocotb.start_soon(random_packet_ready(utils.create_rng(rnd), dut))
    cocotb.start_soon(consume_and_check_packets(
        utils.create_rng(rnd), dut, params, packets_received, packets_expected))
    cocotb.start_soon(consume_and_check_commits(dut, commits_received, commits_expected, params))

    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)

    dispatch_queue.extend(instrs_to_send)
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
