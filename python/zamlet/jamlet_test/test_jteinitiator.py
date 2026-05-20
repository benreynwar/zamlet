import json
from collections import deque
from random import Random
import logging

import cocotb
from cocotb import clock, triggers
from cocotb.handle import HierarchyObject

from zamlet import test_utils
from zamlet.params import ZamletParams


logger = logging.getLogger(__name__)


class TestInfo:

    def __init__(self, data_ew, index_ew, reg_wf, data_reg, index_reg, mask_reg, start_index, end_index):
        self.data_ew = data_ew
        self.index_ew = index_ew
        self.reg_wf = reg_wf
        self.data_reg = data_reg
        self.index_reg = index_reg
        self.mask_reg = mask_reg
        self.start_index = start_index
        self.end_index = end_index

EW1 = 0
EW8 = 3
EW16 = 4
EW32 = 5
EW64 = 6

WF1 = 0
WF8 = 3
WF16 = 4
WF32 = 5
WF64 = 6

async def send_dispatch(dut: HierarchyObject, dispatch_queue) -> None:
    dut.io_input_valid.value = 0
    await triggers.RisingEdge(dut.clock)
    while True:
        await triggers.ReadOnly()
        dispatch_ready = dut.io_input_ready.value
        await triggers.RisingEdge(dut.clock)
        if dispatch_queue and dispatch_ready:
            logger.info('DISPATCh')
            test_info = dispatch_queue.popleft()
            dut.io_input_valid.value = 1
            dut.io_input_bits_slot.value = 0
            dut.io_input_bits_instrIdent.value = 0
            dut.io_input_bits_mode.value = 3
            dut.io_input_bits_baseAddr.value = 0
            dut.io_input_bits_stride.value = 0
            dut.io_input_bits_startIndex.value = test_info.start_index
            dut.io_input_bits_endIndex.value = test_info.end_index
            dut.io_input_bits_dataReg.value = test_info.data_reg
            dut.io_input_bits_indexReg.value = test_info.index_reg
            dut.io_input_bits_maskReg.value = test_info.mask_reg
            dut.io_input_bits_maskEnabled.value = 0
            dut.io_input_bits_rfLaneOrder.value = 0
            dut.io_input_bits_rfDataWF.value = test_info.reg_wf
            dut.io_input_bits_rfDataEW.value = test_info.data_ew
            dut.io_input_bits_rfIndexEW.value = test_info.index_ew
        elif dispatch_ready:
            dut.io_input_valid.value = 0


async def req_resp_handler(dut, req_prefix, resp_prefix, mapping):
    await triggers.RisingEdge(dut.clock)
    addr_queue = deque()
    popped_addr = None
    while True:
        await triggers.ReadOnly()
        req_valid = getattr(dut, req_prefix + 'valid').value
        req_addr = getattr(dut, req_prefix + 'bits').value
        resp_ready = getattr(dut, resp_prefix + 'ready').value
        if req_valid:
            addr_queue.append(req_addr)
        if resp_ready:
            popped_addr = None
        await triggers.RisingEdge(dut.clock)
        req_ready = len(addr_queue) < 2
        resp_valid = len(addr_queue) > 0
        getattr(dut, req_prefix + 'ready').value = req_ready
        getattr(dut, resp_prefix + 'valid').value = resp_valid
        if popped_addr is None and addr_queue:
            popped_addr = int(addr_queue.popleft())
            logger.info(f'Reading {req_prefix}')
        if popped_addr is not None:
            if isinstance(mapping, dict):
                if popped_addr not in mapping:
                    raise Exception(f'Value {popped_addr} not in {mapping} for {resp_prefix}')
            if isinstance(mapping, list):
                assert popped_addr < len(mapping)
            mapped = mapping[popped_addr]
            if isinstance(mapped, dict):
                for key, value in mapped.items():
                    getattr(dut, resp_prefix + 'bits_' + key).value = mapped[key]
            else:
                getattr(dut, resp_prefix + 'bits').value = mapped


def get_header(value):
    dst_index = value >> 48 & ((1 << 16)-1)
    src_x = (value >> 40) & ((1 << 8)-1)
    src_y = (value >> 32) & ((1 << 8)-1)
    header = {'dst_index': dst_index, 'src_x': src_x, 'src_y': src_y}
    return header


async def consume_packets(dut, packets):
    dut.io_packet_ready.value = 1
    await triggers.ReadOnly()
    while True:
        while not (dut.io_packet_valid.value):
            await triggers.RisingEdge(dut.clock)
            await triggers.ReadOnly()
        assert dut.io_packet_bits_isHeader.value == 1
        header = get_header(int(dut.io_packet_bits_bits.value))
        length = 2
        packet = [header]
        await triggers.RisingEdge(dut.clock)
        await triggers.ReadOnly()
        for index in range(length):
            while not (dut.io_packet_valid.value):
                await triggers.RisingEdge(dut.clock)
                await triggers.ReadOnly()
            data = int(dut.io_packet_bits_bits.value)
            packet.append(data)
            await triggers.RisingEdge(dut.clock)
            await triggers.ReadOnly()
        packets.append(packet)


@cocotb.test()
async def jteinitiator_test(dut: HierarchyObject) -> None:
    seed = 0
    rnd = Random(seed)
    test_utils.configure_logging_sim("DEBUG")

    this_x = 2
    this_y = 3
    dut.io_x.value = this_x
    dut.io_y.value = this_y

    # Load params
    test_params = test_utils.get_test_params()
    with open(test_params['params_file']) as f:
        params = ZamletParams.from_dict(json.load(f))

    cocotb.start_soon(clock.Clock(dut.clock, 2, 'ns').start())

    dispatch_queue = deque()
    cocotb.start_soon(send_dispatch(dut, dispatch_queue))

    content = [0] * 32

    # Let's target to two pages
    page_virt_addr_0 = params.page_bytes * 56
    page_virt_addr_1 = params.page_bytes * 189
    page_phys_addr_0 = params.page_bytes * 35
    page_phys_addr_1 = params.page_bytes * 3
    page_table = {
        page_virt_addr_0//params.page_bytes: page_phys_addr_0//params.page_bytes,
        page_virt_addr_1//params.page_bytes: page_phys_addr_1//params.page_bytes,
        }
    logger.info(f'page bytes is {params.page_bytes}, address is {page_virt_addr_0}')
    # Let's set the stripe WF in these pages
    orderings = {}
    for page_addr in (page_virt_addr_0, page_virt_addr_1):
        for stripe_index in range(params.page_words_per_jamlet):
            wf = rnd.choice([WF8, WF16, WF32, WF64])
            stripe_addr = (page_addr + stripe_index * params.page_bytes)//params.stripe_bytes
            orderings[stripe_addr] = {'wf': wf, 'laneOrder': 0}

    packets = []

    cocotb.start_soon(req_resp_handler(dut, 'io_rfIndexReq_', 'io_rfIndexResp_', content))
    cocotb.start_soon(req_resp_handler(dut, 'io_rfDataReq_', 'io_rfDataResp_', content))
    cocotb.start_soon(req_resp_handler(dut, 'io_rfMaskReq_', 'io_rfMaskResp_', content))
    cocotb.start_soon(req_resp_handler(dut, 'io_tlbReq_', 'io_tlbResp_', page_table))
    cocotb.start_soon(req_resp_handler(dut, 'io_orderingReq_', 'io_orderingResp_', orderings))
    cocotb.start_soon(consume_packets(dut, packets))

    dut.io_laneIndex.value = 0

    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)

    # Do a simple write.
    data_reg = 0
    index_reg = 4
    test_info = TestInfo(
        data_ew=EW8,
        index_ew=EW32,
        reg_wf=WF16,
        data_reg=data_reg,
        index_reg=index_reg,
        mask_reg=8,
        start_index=0,
        end_index=1,
        )
    index_eb = 4
    data_eb = 1
    dispatch_queue.append(test_info)
    content[data_reg] = 20
    index_value = page_virt_addr_0 // data_eb
    assert index_value < pow(2, index_eb*8)
    content[index_reg] = index_value

    for i in range(20):
        await triggers.RisingEdge(dut.clock)

    # We expect to have a write packet sent
    print(packets)
    assert len(packets) == 1
    packet = packets.pop(0)
    assert packet[0]['src_x'] == this_x
    assert packet[0]['src_y'] == this_y
    assert packet[0]['dst_index'] == 0
    assert packet[1] == page_phys_addr_0 // params.stripe_bytes
    assert packet[2] == content[data_reg]

    # Do four writes
    test_info = TestInfo(
        data_ew=EW8,
        index_ew=EW32,
        reg_wf=WF16,
        data_reg=data_reg,
        index_reg=index_reg,
        mask_reg=8,
        start_index=0,
        # We have 4 jamlets
        # So to do 4 elements in this jamlet we need 16 elements altogether
        end_index=16,
        )
    dispatch_queue.append(test_info)
    content[data_reg] = 20
    index_values = [
        page_virt_addr_0 // data_eb + 3,
        page_virt_addr_1 // data_eb + 7,
        page_virt_addr_1 // data_eb + 1,
        page_virt_addr_0 // data_eb + 0,
        ]
    content[index_reg] = (index_values[1] << 32) + index_values[0]
    content[index_reg+1] = (index_values[3] << 32) + index_values[2]
    content[data_reg] = 0xabcd

    for i in range(60):
        await triggers.RisingEdge(dut.clock)
    assert len(packets) == 4








    # Handle register requests

    # Handle tlb request

    # Handle ordering request

    # Send in a dispatch

