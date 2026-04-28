"""
Tests for vta (tail-agnostic) and vma (mask-agnostic) policies on Pattern A
arith handlers.

Drives a masked, partial-vl vadd.vv with the destination pre-filled with a
non-trivial sentinel byte pattern, then asserts the post-op contents at
active, inactive (mask-off body), and tail positions match the spec policy:

  vta=True / vma=True : agnostic positions filled with 0xFF
  vta=False / vma=False: agnostic positions left undisturbed (sentinel)
"""

import asyncio
import logging
from random import Random

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering
from zamlet.geometries import get_geometry
from zamlet.kamlet.kinstructions import VArithOp
from zamlet.instructions.vector import VArithVv
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, dump_span_trees,
    fill_register, setup_mask_register,
)

logger = logging.getLogger(__name__)


SENTINEL_BYTE = 0x55


async def _run(
    lamlet, *, vta: bool, vma: bool, sew: int, vl: int,
    mask_bits: list, rnd: Random,
) -> None:
    bits_in_vline = lamlet.params.vline_bytes * 8
    vlmax = bits_in_vline // sew
    assert vl < vlmax, f'need partial vl to test tail; vlmax={vlmax}, vl={vl}'
    assert len(mask_bits) == vl

    eb = sew // 8
    page_bytes = lamlet.params.page_bytes

    vs1_addr = 0x90000000
    vs2_addr = vs1_addr + page_bytes
    sentinel_addr = vs2_addr + page_bytes
    mask_addr = sentinel_addr + page_bytes
    vd_addr = mask_addr + page_bytes
    for a in (vs1_addr, vs2_addr, vd_addr):
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=a * 8, params=lamlet.params),
            page_bytes, memory_type=MemoryType.VPU)

    s1_vals = [rnd.randint(0, (1 << sew) - 1) for _ in range(vlmax)]
    s2_vals = [rnd.randint(0, (1 << sew) - 1) for _ in range(vlmax)]
    s1_bytes = pack_elements(s1_vals, sew)
    s2_bytes = pack_elements(s2_vals, sew)

    ord_sew = Ordering(lamlet.word_order, sew)
    await lamlet.set_memory(vs1_addr, s1_bytes, ordering=ord_sew)
    await lamlet.set_memory(vs2_addr, s2_bytes, ordering=ord_sew)

    vs1_reg = 2
    vs2_reg = 4
    vd_reg = 6
    mask_reg = 0  # VArithVv with vm=0 picks v0 as the mask

    # Pre-fill vd with the sentinel pattern. fill_register loads vlmax
    # elements so every byte of the vd register starts at SENTINEL_BYTE.
    await fill_register(lamlet, vd_reg, vlmax, sew, page_bytes, sentinel_addr,
                        byte_pattern=SENTINEL_BYTE)

    # Mask: pad the body mask out to vlmax (tail bits don't matter — beyond
    # vl the spec ignores the mask).
    full_mask = list(mask_bits) + [False] * (vlmax - vl)
    await setup_mask_register(lamlet, mask_reg, full_mask, page_bytes, mask_addr)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET,
        mnemonic=f'vta={int(vta)}_vma={int(vma)}_vl={vl}')

    await lamlet.vload(vd=vs1_reg, addr=vs1_addr, ordering=ord_sew,
                       n_elements=vlmax, mask_reg=None, start_index=0,
                       parent_span_id=span_id)
    await lamlet.vload(vd=vs2_reg, addr=vs2_addr, ordering=ord_sew,
                       n_elements=vlmax, mask_reg=None, start_index=0,
                       parent_span_id=span_id)

    vsew = {8: 0, 16: 1, 32: 2, 64: 3}[sew]
    vlmul = 0  # lmul=1
    lamlet.vtype = (int(vma) << 7) | (int(vta) << 6) | (vsew << 3) | vlmul
    lamlet.vl = vl
    lamlet.pc = 0

    instr = VArithVv(vd=vd_reg, vs1=vs1_reg, vs2=vs2_reg, vm=0, op=VArithOp.ADD)
    await instr.update_state(lamlet)

    # Store the full vd register (vlmax elements, not just vl) so we can
    # inspect tail bytes too.
    await lamlet.vstore(vs=vd_reg, addr=vd_addr, ordering=ord_sew,
                        n_elements=vlmax, mask_reg=None, start_index=0,
                        parent_span_id=span_id)
    lamlet.monitor.finalize_children(span_id)

    result_bytes = await lamlet.get_memory_blocking(vd_addr, vlmax * eb)
    sentinel = bytes([SENTINEL_BYTE]) * eb
    ones = b'\xff' * eb
    for i in range(vlmax):
        elem_bytes = result_bytes[i * eb:(i + 1) * eb]
        if i >= vl:
            expected = ones if vta else sentinel
            tag = f'tail[{i}]'
        elif not full_mask[i]:
            expected = ones if vma else sentinel
            tag = f'inactive[{i}]'
        else:
            sum_val = (s1_vals[i] + s2_vals[i]) & ((1 << sew) - 1)
            expected = sum_val.to_bytes(eb, 'little')
            tag = f'active[{i}]'
        assert elem_bytes == expected, (
            f'vta={vta} vma={vma} {tag}: got 0x{elem_bytes.hex()}, '
            f'expected 0x{expected.hex()}')


async def _test_main(clock, params, vta, vma, sew, vl, mask_bits, seed):
    lamlet = await setup_lamlet(clock, params)
    rnd = Random(seed)
    try:
        await _run(lamlet, vta=vta, vma=vma, sew=sew, vl=vl,
                   mask_bits=list(mask_bits), rnd=rnd)
    except Exception:
        dump_span_trees(lamlet.monitor)
        raise


def _drive(vta, vma, sew=32, vl=3, mask_bits=(True, False, True), seed=0,
           geometry='k2x1_j2x1'):
    params = get_geometry(geometry)
    clock = Clock(max_cycles=20000)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        await _test_main(clock, params, vta, vma, sew, vl, mask_bits, seed)
        clock.running = False

    asyncio.run(main())


def test_vadd_agnostic_tail_and_inactive():
    """vta=True, vma=True: tail and mask-off bytes filled with 0xFF."""
    _drive(vta=True, vma=True)


def test_vadd_undisturbed_tail_and_inactive():
    """vta=False, vma=False: tail and mask-off bytes preserve sentinel."""
    _drive(vta=False, vma=False)


def test_vadd_vta_only():
    """vta=True, vma=False: tail filled with 0xFF, mask-off preserved."""
    _drive(vta=True, vma=False)


def test_vadd_vma_only():
    """vta=False, vma=True: mask-off filled with 0xFF, tail preserved."""
    _drive(vta=False, vma=True)


async def _run_load(
    lamlet, *, vta: bool, vma: bool, sew: int, vl: int,
    mask_bits: list, rnd: Random,
) -> None:
    """Partial-vl masked vload into pre-filled vd. Exercises Pattern B
    (load_simple) — checks that tail bytes follow vta and mask-off body
    bytes follow vma without disturbing prestart bytes (none here since
    start_index=0)."""
    bits_in_vline = lamlet.params.vline_bytes * 8
    vlmax = bits_in_vline // sew
    assert vl < vlmax, f'need partial vl to test tail; vlmax={vlmax}, vl={vl}'
    assert len(mask_bits) == vl

    eb = sew // 8
    page_bytes = lamlet.params.page_bytes

    src_addr = 0x90000000
    sentinel_addr = src_addr + page_bytes
    mask_addr = sentinel_addr + page_bytes
    vd_addr = mask_addr + page_bytes
    for a in (src_addr, vd_addr):
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=a * 8, params=lamlet.params),
            page_bytes, memory_type=MemoryType.VPU)

    src_vals = [rnd.randint(0, (1 << sew) - 1) for _ in range(vlmax)]
    src_bytes = pack_elements(src_vals, sew)

    ord_sew = Ordering(lamlet.word_order, sew)
    await lamlet.set_memory(src_addr, src_bytes, ordering=ord_sew)

    vd_reg = 6
    mask_reg = 0

    await fill_register(lamlet, vd_reg, vlmax, sew, page_bytes, sentinel_addr,
                        byte_pattern=SENTINEL_BYTE)

    full_mask = list(mask_bits) + [False] * (vlmax - vl)
    await setup_mask_register(lamlet, mask_reg, full_mask, page_bytes, mask_addr)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET,
        mnemonic=f'load_vta={int(vta)}_vma={int(vma)}_vl={vl}')

    vsew = {8: 0, 16: 1, 32: 2, 64: 3}[sew]
    vlmul = 0
    lamlet.vtype = (int(vma) << 7) | (int(vta) << 6) | (vsew << 3) | vlmul
    lamlet.vl = vl
    lamlet.pc = 0

    await lamlet.vload(vd=vd_reg, addr=src_addr, ordering=ord_sew,
                       n_elements=vl, mask_reg=mask_reg, start_index=0,
                       parent_span_id=span_id)

    await lamlet.vstore(vs=vd_reg, addr=vd_addr, ordering=ord_sew,
                        n_elements=vlmax, mask_reg=None, start_index=0,
                        parent_span_id=span_id)
    lamlet.monitor.finalize_children(span_id)

    result_bytes = await lamlet.get_memory_blocking(vd_addr, vlmax * eb)
    sentinel = bytes([SENTINEL_BYTE]) * eb
    ones = b'\xff' * eb
    for i in range(vlmax):
        elem_bytes = result_bytes[i * eb:(i + 1) * eb]
        if i >= vl:
            expected = ones if vta else sentinel
            tag = f'tail[{i}]'
        elif not full_mask[i]:
            expected = ones if vma else sentinel
            tag = f'inactive[{i}]'
        else:
            expected = src_vals[i].to_bytes(eb, 'little')
            tag = f'active[{i}]'
        assert elem_bytes == expected, (
            f'load vta={vta} vma={vma} {tag}: got 0x{elem_bytes.hex()}, '
            f'expected 0x{expected.hex()}')


async def _test_main_load(clock, params, vta, vma, sew, vl, mask_bits, seed):
    lamlet = await setup_lamlet(clock, params)
    rnd = Random(seed)
    try:
        await _run_load(lamlet, vta=vta, vma=vma, sew=sew, vl=vl,
                        mask_bits=list(mask_bits), rnd=rnd)
    except Exception:
        dump_span_trees(lamlet.monitor)
        raise


def _drive_load(vta, vma, sew=32, vl=3, mask_bits=(True, False, True), seed=0,
                geometry='k2x1_j2x1'):
    params = get_geometry(geometry)
    clock = Clock(max_cycles=20000)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        await _test_main_load(clock, params, vta, vma, sew, vl, mask_bits, seed)
        clock.running = False

    asyncio.run(main())


def test_vload_agnostic_tail_and_inactive():
    """vta=True, vma=True: tail and mask-off bytes filled with 0xFF."""
    _drive_load(vta=True, vma=True)


def test_vload_undisturbed_tail_and_inactive():
    """vta=False, vma=False: tail and mask-off bytes preserve sentinel."""
    _drive_load(vta=False, vma=False)


def test_vload_vta_only():
    """vta=True, vma=False: tail filled with 0xFF, mask-off preserved."""
    _drive_load(vta=True, vma=False)


def test_vload_vma_only():
    """vta=False, vma=True: mask-off filled with 0xFF, tail preserved."""
    _drive_load(vta=False, vma=True)
