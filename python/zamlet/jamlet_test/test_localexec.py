import json
import random
from collections import deque
from dataclasses import dataclass

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet import test_utils
from zamlet.kamlet.kinstructions import (
    KInstrOpcode,
    PackedBinaryOp,
    PackedLoadImm,
    PackedLoadSimple,
    PackedStoreSimple,
)
from zamlet.lane_order import LaneOrder
from zamlet.maths.segmented_multiplier import latency as segmented_multiplier_latency
from zamlet.params import ZamletParams
from zamlet.width_codes import ElementWidthCode, WidthFormatCode


RF_RESPONSE_LATENCY = 1
LOCAL_EXEC_S1_LATENCY = 1


@dataclass
class RfRead:
    valid: bool
    addr: int = 0
    data: int = 0


@dataclass
class SramReq:
    valid: bool
    address: int = 0
    is_write: bool = False
    data: int = 0
    write_mask: int = 0
    response_data: int = 0


@dataclass
class Writeback:
    valid: bool
    addr: int = 0
    data: int = 0
    mask: int = 0


@dataclass
class LocalExecCase:
    kinstr: int
    cache_slot: int
    sram_word_offset: int
    lane_index: int
    wf: int
    start_index: int
    end_index: int
    rf_a: RfRead
    rf_b: RfRead
    rf_mask: RfRead
    sram: SramReq
    writeback: Writeback


def load_params() -> ZamletParams:
    test_params = test_utils.get_test_params()
    with open(test_params["params_file"]) as f:
        return ZamletParams.from_dict(json.load(f))


def no_rf_read() -> RfRead:
    return RfRead(False)


def no_sram() -> SramReq:
    return SramReq(False)


def no_writeback() -> Writeback:
    return Writeback(False)


def full_word_mask(params: ZamletParams) -> int:
    return (1 << params.word_width) - 1


def ew_bits(ew: int) -> int:
    return 1 << ew


def compatible_wf(params: ZamletParams, ew: int, rnd: random.Random) -> int:
    return rnd.choice([
        wf for wf in [
            WidthFormatCode.WF8,
            WidthFormatCode.WF16,
            WidthFormatCode.WF32,
            WidthFormatCode.WF64,
        ] if ew <= wf and (1 << wf) <= params.word_width
    ])


def one_past_end_index(params: ZamletParams, ew: int) -> int:
    elements_per_word = params.word_bytes // (ew_bits(ew) // 8)
    return elements_per_word * params.j_in_l


def expected_bit_mask(
    params: ZamletParams,
    ew: int,
    wf: int,
    lane_index: int,
    start_index: int,
    end_index: int,
    mask_word: int,
) -> int:
    element_bytes = ew_bits(ew) // 8
    elements_per_wf = (1 << wf) // ew_bits(ew)
    result = 0
    for byte in range(params.word_bytes):
        local_element_slot = byte // element_bytes
        wf_group = local_element_slot // elements_per_wf
        element_in_wf = local_element_slot % elements_per_wf
        element_index = lane_index + wf_group * elements_per_wf * params.j_in_l + element_in_wf
        if start_index <= element_index < end_index and ((mask_word >> local_element_slot) & 1):
            result |= 0xff << (byte * 8)
    return result & full_word_mask(params)


def expected_load_imm_mask(params: ZamletParams, section: int, byte_mask: int) -> int:
    shifted = byte_mask << (section * 4)
    result = 0
    for byte in range(params.word_bytes):
        if (shifted >> byte) & 1:
            result |= 0xff << (byte * 8)
    return result


def sign_extend(value: int, width: int) -> int:
    sign_bit = 1 << (width - 1)
    return value - (1 << width) if value & sign_bit else value


def expected_alu_data(
    params: ZamletParams,
    opcode: KInstrOpcode,
    a: int,
    b: int,
    ew: int,
    signed_a: bool,
    signed_b: bool,
) -> int:
    element_width = ew_bits(ew)
    element_mask = (1 << element_width) - 1
    product_mask = (1 << (2 * element_width)) - 1
    result = 0

    for element in range(params.word_width // element_width):
        shift = element * element_width
        lhs_raw = (a >> shift) & element_mask
        rhs_raw = (b >> shift) & element_mask

        if opcode == KInstrOpcode.ADD:
            value = lhs_raw + rhs_raw
        elif opcode == KInstrOpcode.SUB:
            value = lhs_raw - rhs_raw
        else:
            lhs = sign_extend(lhs_raw, element_width) if signed_a else lhs_raw
            rhs = sign_extend(rhs_raw, element_width) if signed_b else rhs_raw
            product = (lhs * rhs) & product_mask
            value = product >> element_width if opcode == KInstrOpcode.MUL_HIGH else product

        result |= (value & element_mask) << shift

    return result & full_word_mask(params)


def make_load_imm(params: ZamletParams, rnd: random.Random) -> LocalExecCase:
    rf_addr = rnd.randrange(params.rf_slice_words)
    section = rnd.randrange(params.word_bytes // 4)
    byte_mask = rnd.randrange(1, 16)
    data = rnd.getrandbits(32)
    return LocalExecCase(
        kinstr=PackedLoadImm(rf_addr=rf_addr, section=section, byte_mask=byte_mask, data=data).encode(params),
        cache_slot=0,
        sram_word_offset=0,
        lane_index=rnd.randrange(params.j_in_l),
        wf=WidthFormatCode.WF64,
        start_index=0,
        end_index=0,
        rf_a=no_rf_read(),
        rf_b=no_rf_read(),
        rf_mask=no_rf_read(),
        sram=no_sram(),
        writeback=Writeback(
            True,
            rf_addr,
            (data << (section * 32)) & full_word_mask(params),
            expected_load_imm_mask(params, section, byte_mask),
        ),
    )


def make_load_simple(params: ZamletParams, rnd: random.Random) -> LocalExecCase:
    ew = rnd.choice([
        ElementWidthCode.EW8,
        ElementWidthCode.EW16,
        ElementWidthCode.EW32,
        ElementWidthCode.EW64,
    ])
    wf = compatible_wf(params, ew, rnd)
    rf_addr = rnd.randrange(params.rf_slice_words)
    mask_enabled = rnd.choice([False, True])
    mask_reg = rnd.randrange(params.rf_slice_words)
    mask_word = rnd.getrandbits(params.word_width)
    lane_index = rnd.randrange(params.j_in_l)
    start_index = rnd.randrange(one_past_end_index(params, ew))
    end_index = rnd.randrange(start_index + 1, one_past_end_index(params, ew) + 1)
    cache_slot = rnd.randrange(params.n_cache_slots)
    sram_word_offset = rnd.randrange(params.cache_slot_words_per_jamlet)
    sram_data = rnd.getrandbits(params.word_width)
    mask = expected_bit_mask(
        params,
        ew,
        wf,
        lane_index,
        start_index,
        end_index,
        mask_word if mask_enabled else full_word_mask(params),
    )
    return LocalExecCase(
        kinstr=PackedLoadSimple(
            rf_addr=rf_addr,
            end_index_param_idx=1,
            mask_reg=mask_reg,
            ew=ew,
            mask_enabled=mask_enabled,
        ).encode(params),
        cache_slot=cache_slot,
        sram_word_offset=sram_word_offset,
        lane_index=lane_index,
        wf=wf,
        start_index=start_index,
        end_index=end_index,
        rf_a=no_rf_read(),
        rf_b=no_rf_read(),
        rf_mask=RfRead(mask_enabled, mask_reg, mask_word),
        sram=SramReq(
            True,
            address=cache_slot * params.cache_slot_words_per_jamlet + sram_word_offset,
            is_write=False,
            response_data=sram_data,
        ),
        writeback=Writeback(True, rf_addr, sram_data, mask),
    )


def make_store_simple(params: ZamletParams, rnd: random.Random) -> LocalExecCase:
    ew = rnd.choice([
        ElementWidthCode.EW8,
        ElementWidthCode.EW16,
        ElementWidthCode.EW32,
        ElementWidthCode.EW64,
    ])
    wf = compatible_wf(params, ew, rnd)
    rf_addr = rnd.randrange(params.rf_slice_words)
    mask_enabled = rnd.choice([False, True])
    mask_reg = rnd.randrange(params.rf_slice_words)
    mask_word = rnd.getrandbits(params.word_width)
    rf_data = rnd.getrandbits(params.word_width)
    lane_index = rnd.randrange(params.j_in_l)
    start_index = rnd.randrange(one_past_end_index(params, ew))
    end_index = rnd.randrange(start_index + 1, one_past_end_index(params, ew) + 1)
    cache_slot = rnd.randrange(params.n_cache_slots)
    sram_word_offset = rnd.randrange(params.cache_slot_words_per_jamlet)
    mask = expected_bit_mask(
        params,
        ew,
        wf,
        lane_index,
        start_index,
        end_index,
        mask_word if mask_enabled else full_word_mask(params),
    )
    return LocalExecCase(
        kinstr=PackedStoreSimple(
            rf_addr=rf_addr,
            end_index_param_idx=1,
            mask_reg=mask_reg,
            ew=ew,
            mask_enabled=mask_enabled,
        ).encode(params),
        cache_slot=cache_slot,
        sram_word_offset=sram_word_offset,
        lane_index=lane_index,
        wf=wf,
        start_index=start_index,
        end_index=end_index,
        rf_a=RfRead(True, rf_addr, rf_data),
        rf_b=no_rf_read(),
        rf_mask=RfRead(mask_enabled, mask_reg, mask_word),
        sram=SramReq(
            True,
            address=cache_slot * params.cache_slot_words_per_jamlet + sram_word_offset,
            is_write=True,
            data=rf_data,
            write_mask=mask,
        ),
        writeback=no_writeback(),
    )


def make_binary(params: ZamletParams, rnd: random.Random, opcode: KInstrOpcode) -> LocalExecCase:
    ew = rnd.choice([
        ElementWidthCode.EW8,
        ElementWidthCode.EW16,
        ElementWidthCode.EW32,
        ElementWidthCode.EW64,
    ])
    wf = compatible_wf(params, ew, rnd)
    dst_reg = rnd.randrange(params.rf_slice_words)
    src_a_reg = rnd.randrange(params.rf_slice_words)
    src_b_reg = rnd.randrange(params.rf_slice_words)
    mask_enabled = rnd.choice([False, True])
    mask_reg = rnd.randrange(params.rf_slice_words)
    mask_word = rnd.getrandbits(params.word_width)
    a = rnd.getrandbits(params.word_width)
    b = rnd.getrandbits(params.word_width)
    signed_a = opcode in (KInstrOpcode.MUL, KInstrOpcode.MUL_HIGH) and rnd.choice([False, True])
    signed_b = opcode in (KInstrOpcode.MUL, KInstrOpcode.MUL_HIGH) and rnd.choice([False, True])
    lane_index = rnd.randrange(params.j_in_l)
    start_index = rnd.randrange(one_past_end_index(params, ew))
    end_index = rnd.randrange(start_index + 1, one_past_end_index(params, ew) + 1)
    mask = expected_bit_mask(
        params,
        ew,
        wf,
        lane_index,
        start_index,
        end_index,
        mask_word if mask_enabled else full_word_mask(params),
    )
    return LocalExecCase(
        kinstr=PackedBinaryOp(
            opcode=opcode,
            dst_reg=dst_reg,
            src_a_reg=src_a_reg,
            src_b_reg=src_b_reg,
            end_index_param_idx=1,
            mask_reg=mask_reg,
            ew=ew,
            is_signed_a=signed_a,
            is_signed_b=signed_b,
            mask_enabled=mask_enabled,
        ).encode(params),
        cache_slot=0,
        sram_word_offset=0,
        lane_index=lane_index,
        wf=wf,
        start_index=start_index,
        end_index=end_index,
        rf_a=RfRead(True, src_a_reg, a),
        rf_b=RfRead(True, src_b_reg, b),
        rf_mask=RfRead(mask_enabled, mask_reg, mask_word),
        sram=no_sram(),
        writeback=Writeback(True, dst_reg, expected_alu_data(params, opcode, a, b, ew, signed_a, signed_b), mask),
    )


def make_cases(params: ZamletParams) -> list[LocalExecCase]:
    rnd = random.Random(12345)
    makers = [
        lambda: make_load_imm(params, rnd),
        lambda: make_load_simple(params, rnd),
        lambda: make_store_simple(params, rnd),
        lambda: make_binary(params, rnd, KInstrOpcode.ADD),
        lambda: make_binary(params, rnd, KInstrOpcode.SUB),
        lambda: make_binary(params, rnd, KInstrOpcode.MUL),
        lambda: make_binary(params, rnd, KInstrOpcode.MUL_HIGH),
    ]
    cases = [maker() for maker in makers]
    cases.extend(rnd.choice(makers)() for _ in range(80))
    return cases


async def reset_dut(dut: HierarchyObject) -> None:
    cocotb.start_soon(Clock(dut.clock, 2, "ns").start())
    dut.reset.value = 1
    dut.io_laneIndex.value = 0
    dut.io_kinstrIn_valid.value = 0
    dut.io_kinstrIn_bits_kinstr.value = 0
    dut.io_kinstrIn_bits_ordering_wf.value = WidthFormatCode.WF64
    dut.io_kinstrIn_bits_ordering_laneOrder.value = LaneOrder.ROW_MAJOR
    dut.io_kinstrIn_bits_cacheSlot.value = 0
    dut.io_kinstrIn_bits_sramWordOffset.value = 0
    dut.io_kinstrIn_bits_param0.value = 0
    dut.io_kinstrIn_bits_param1.value = 0
    dut.io_kinstrIn_bits_param2.value = 0
    drive_rf_response(dut, "A", None)
    drive_rf_response(dut, "B", None)
    drive_rf_response(dut, "Mask", None)
    drive_sram_response(dut, None)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)


def drive_instruction(dut: HierarchyObject, case: LocalExecCase | None) -> None:
    dut.io_kinstrIn_valid.value = int(case is not None)
    dut.io_laneIndex.value = 0 if case is None else case.lane_index
    if case is not None:
        dut.io_kinstrIn_bits_kinstr.value = case.kinstr
        dut.io_kinstrIn_bits_ordering_wf.value = case.wf
        dut.io_kinstrIn_bits_ordering_laneOrder.value = LaneOrder.ROW_MAJOR
        dut.io_kinstrIn_bits_cacheSlot.value = case.cache_slot
        dut.io_kinstrIn_bits_sramWordOffset.value = case.sram_word_offset
        dut.io_kinstrIn_bits_param0.value = case.start_index
        dut.io_kinstrIn_bits_param1.value = case.end_index
        dut.io_kinstrIn_bits_param2.value = 0


def drive_rf_response(dut: HierarchyObject, port: str, item: RfRead | None) -> None:
    valid = int(item is not None and item.valid)
    data = 0 if item is None else item.data
    getattr(dut, f"io_rfRead{port}Resp_valid").value = valid
    getattr(dut, f"io_rfRead{port}Resp_bits_readData").value = data


def drive_sram_response(dut: HierarchyObject, item: SramReq | None) -> None:
    valid = int(item is not None and item.valid and not item.is_write)
    data = 0 if item is None else item.response_data
    dut.io_sramResp_valid.value = valid
    dut.io_sramResp_bits.value = data


def check_rf_req(valid_value, addr_value, expected: RfRead, label: str) -> None:
    assert int(valid_value.value) == int(expected.valid), label
    if expected.valid:
        assert int(addr_value.value) == expected.addr, label


def check_sram_req(dut: HierarchyObject, expected: SramReq | None, label: str) -> None:
    expected = no_sram() if expected is None else expected
    assert int(dut.io_sramReq_valid.value) == int(expected.valid), label
    if expected.valid:
        assert int(dut.io_sramReq_bits_address.value) == expected.address, label
        assert int(dut.io_sramReq_bits_isWrite.value) == int(expected.is_write), label
        if expected.is_write:
            assert int(dut.io_sramReq_bits_data.value) == expected.data, label
            assert int(dut.io_sramReq_bits_writeMask.value) == expected.write_mask, label


def check_writeback(dut: HierarchyObject, expected: Writeback | None, label: str) -> None:
    expected = no_writeback() if expected is None else expected
    assert int(dut.io_rfWriteReq_valid.value) == int(expected.valid), label
    if expected.valid:
        assert int(dut.io_rfWriteReq_bits_addr.value) == expected.addr, label
        assert int(dut.io_rfWriteReq_bits_isWrite.value) == 1, label
        assert int(dut.io_rfWriteReq_bits_writeData.value) == expected.data, label
        assert int(dut.io_rfWriteReq_bits_writeMask.value) == expected.mask, label


@cocotb.test()
async def localexec_random_stream(dut: HierarchyObject) -> None:
    params = load_params()
    cases = make_cases(params)
    alu_latency = segmented_multiplier_latency(params.word_width)
    sram_response_latency = params.sram_params.local_response_latency
    await reset_dut(dut)

    issue_q = deque(cases)
    rf_a_response_q = deque([None] * RF_RESPONSE_LATENCY)
    rf_b_response_q = deque([None] * RF_RESPONSE_LATENCY)
    rf_mask_response_q = deque([None] * RF_RESPONSE_LATENCY)
    sram_expected_q = deque([None] * LOCAL_EXEC_S1_LATENCY)
    sram_response_q = deque([None] * (LOCAL_EXEC_S1_LATENCY + sram_response_latency))
    writeback_expected_q = deque([None] * (LOCAL_EXEC_S1_LATENCY + alu_latency))

    cycles = len(cases) + LOCAL_EXEC_S1_LATENCY + max(alu_latency, sram_response_latency) + 3
    for cycle in range(cycles):
        case = issue_q.popleft() if issue_q else None

        drive_instruction(dut, case)
        drive_rf_response(dut, "A", rf_a_response_q.popleft())
        drive_rf_response(dut, "B", rf_b_response_q.popleft())
        drive_rf_response(dut, "Mask", rf_mask_response_q.popleft())
        drive_sram_response(dut, sram_response_q.popleft())

        if case is not None:
            rf_a_response_q.append(case.rf_a if case.rf_a.valid else None)
            rf_b_response_q.append(case.rf_b if case.rf_b.valid else None)
            rf_mask_response_q.append(case.rf_mask if case.rf_mask.valid else None)
            sram_expected_q.append(case.sram if case.sram.valid else None)
            sram_response_q.append(case.sram if case.sram.valid and not case.sram.is_write else None)
            writeback_expected_q.append(case.writeback if case.writeback.valid else None)
        else:
            rf_a_response_q.append(None)
            rf_b_response_q.append(None)
            rf_mask_response_q.append(None)
            sram_expected_q.append(None)
            sram_response_q.append(None)
            writeback_expected_q.append(None)

        await ReadOnly()

        if case is not None:
            check_rf_req(dut.io_rfReadAReq_valid, dut.io_rfReadAReq_bits_addr, case.rf_a, f"cycle={cycle} rfA")
            check_rf_req(dut.io_rfReadBReq_valid, dut.io_rfReadBReq_bits_addr, case.rf_b, f"cycle={cycle} rfB")
            check_rf_req(
                dut.io_rfReadMaskReq_valid,
                dut.io_rfReadMaskReq_bits_addr,
                case.rf_mask,
                f"cycle={cycle} rfMask",
            )
        else:
            check_rf_req(dut.io_rfReadAReq_valid, dut.io_rfReadAReq_bits_addr, no_rf_read(), f"cycle={cycle} rfA idle")
            check_rf_req(dut.io_rfReadBReq_valid, dut.io_rfReadBReq_bits_addr, no_rf_read(), f"cycle={cycle} rfB idle")
            check_rf_req(dut.io_rfReadMaskReq_valid, dut.io_rfReadMaskReq_bits_addr, no_rf_read(), f"cycle={cycle} rfMask idle")

        check_sram_req(dut, sram_expected_q.popleft(), f"cycle={cycle} sram")
        check_writeback(dut, writeback_expected_q.popleft(), f"cycle={cycle} writeback")
        assert int(dut.io_errors_unsupportedOpcode.value) == 0
        assert int(dut.io_errors_alu_unsupportedEw.value) == 0
        assert int(dut.io_errors_alu_unsupportedWf.value) == 0
        assert int(dut.io_errors_alu_unsupportedEwWfRatio.value) == 0

        await RisingEdge(dut.clock)
