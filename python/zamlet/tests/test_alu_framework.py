"""Unit tests for the long-latency ALU framework (PLAN_long_latency_alu.md step 1).

Covers:
  - latency-1 stub op end-to-end (dispatch -> latency wait -> commit visible to
    a dependent reader via rf_info scoreboard).
  - sticky_fflags / sticky_vxsat OR-accumulation across multiple ops.

These tests bypass the lamlet's instruction fetch path and push stub kinstrs
directly onto a kamlet's instruction queue so the framework can be exercised
in isolation.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from zamlet.runner import Clock
from zamlet.geometries import get_geometry
from zamlet.kamlet.kinstructions import AluKInstr, AluResult, FFlags, KInstr
from zamlet.register_file_slot import Resources
from zamlet.tests.test_utils import setup_lamlet


logger = logging.getLogger(__name__)


@dataclass
class _AluStub(AluKInstr):
    """Minimal AluKInstr for framework testing.

    Reads `src_preg` from `j_in_k`'s rf_slice as a little-endian unsigned int,
    increments it (mod 2^(word_bytes*8)), and writes the result to `dst_preg`
    on the same jamlet. fflags/vxsat outputs are populated from kinstr fields
    so tests can drive sticky-flag accumulation deterministically.

    Fields are kept distinct from the renamed.dst_pregs/src_pregs convention
    so the test stays readable; admit() builds the Renamed using these fields.
    """
    src_preg: int = 0
    dst_preg: int = 0
    j_in_k: int = 0
    latency: int = 1
    resources: dict = field(default_factory=dict)
    fflags_out: FFlags = field(default_factory=FFlags)
    vxsat_out: bool = False
    span_id: int = 0
    # Side channel: each entry is (cycle, value) read from src_preg during compute.
    # Shared by reference across copy.copy() so the test can inspect after dispatch.
    record: list = field(default_factory=list, repr=False)

    async def admit(self, kamlet) -> 'KInstr | None':
        return self.rename(
            src_pregs={0: self.src_preg},
            dst_pregs={0: self.dst_preg},
        )

    def alu_compute(self, kamlet) -> list[AluResult]:
        wb = kamlet.params.word_bytes
        jamlet = kamlet.jamlets[self.j_in_k]
        src_base = self.src_preg * wb
        src_bytes = bytes(jamlet.rf_slice[src_base:src_base + wb])
        src_val = int.from_bytes(src_bytes, 'little', signed=False)
        self.record.append((kamlet.clock.cycle, src_val))
        out_val = (src_val + 1) & ((1 << (wb * 8)) - 1)
        return [AluResult(
            j_in_k=self.j_in_k,
            dst_preg=self.dst_preg,
            byte_offset=0,
            data=out_val.to_bytes(wb, 'little'),
            span_id=self.span_id,
            fflags=self.fflags_out,
            vxsat=self.vxsat_out,
        )]


def _seed_preg(jamlet, preg: int, value: int) -> None:
    wb = jamlet.params.word_bytes
    base = preg * wb
    jamlet.rf_slice[base:base + wb] = value.to_bytes(wb, 'little')


def _read_preg(jamlet, preg: int) -> int:
    wb = jamlet.params.word_bytes
    base = preg * wb
    return int.from_bytes(jamlet.rf_slice[base:base + wb], 'little', signed=False)


async def _enqueue(clock, kamlet, kinstrs):
    """Push kinstrs onto the kamlet's instruction queue, yielding when it
    can't accept (full, or already appended this cycle)."""
    for instr in kinstrs:
        while not kamlet._instruction_queue.can_append():
            await clock.next_cycle
        kamlet.add_to_instruction_queue(instr)


def _run(coro_fn, geometry: str = 'k2x1_j1x1', max_cycles: int = 200) -> None:
    """Boot a lamlet, run `coro_fn(clock, lamlet)`, tear down."""
    params = get_geometry(geometry)
    clock = Clock(max_cycles=max_cycles)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        lamlet = await setup_lamlet(clock, params)
        try:
            await coro_fn(clock, lamlet)
        finally:
            clock.running = False

    asyncio.run(main())


def test_latency_one_chain():
    """Producer -> dependent reader chain validates dispatch + scoreboard.

    Both ops use latency=1. They target distinct dst pregs but the reader's
    src_preg is the producer's dst_preg. If the rf_info write lock isn't held
    for the full latency, the reader could dispatch before the producer's
    write commits and see the pre-write value (0).
    """
    SEED_VALUE = 0x42
    PREG_A = 40   # producer src
    PREG_B = 41   # producer dst / reader src
    PREG_C = 42   # reader dst

    async def body(clock, lamlet):
        kamlet = lamlet.kamlets[0]
        jamlet = kamlet.jamlets[0]
        _seed_preg(jamlet, PREG_A, SEED_VALUE)

        producer = _AluStub(src_preg=PREG_A, dst_preg=PREG_B, latency=1)
        reader = _AluStub(src_preg=PREG_B, dst_preg=PREG_C, latency=1)
        await _enqueue(clock, kamlet, [producer, reader])

        # Run long enough for both to admit, dispatch, and commit.
        for _ in range(40):
            await clock.next_cycle

        # Final values: producer wrote SEED+1, reader wrote SEED+2 (chained).
        assert _read_preg(jamlet, PREG_B) == SEED_VALUE + 1, (
            f"producer dst: got {_read_preg(jamlet, PREG_B):#x}, "
            f"expected {SEED_VALUE + 1:#x}")
        assert _read_preg(jamlet, PREG_C) == SEED_VALUE + 2, (
            f"reader dst:   got {_read_preg(jamlet, PREG_C):#x}, "
            f"expected {SEED_VALUE + 2:#x}"
            f" (reader executed before producer's write committed)")

        # Reader must have read producer's output, not the pre-write value.
        assert reader.record, "reader never executed"
        _, read_val = reader.record[-1]
        assert read_val == SEED_VALUE + 1, (
            f"reader saw {read_val:#x}, expected {SEED_VALUE + 1:#x} "
            f"(scoreboard didn't stall the reader)")

    _run(body)


def test_sticky_fflags_accumulation():
    """Multiple ALU ops OR-accumulate into the per-jamlet sticky_fflags."""
    PREG_A, PREG_B, PREG_C, PREG_D = 40, 41, 42, 43

    async def body(clock, lamlet):
        kamlet = lamlet.kamlets[0]
        jamlet = kamlet.jamlets[0]
        _seed_preg(jamlet, PREG_A, 0)

        op1 = _AluStub(src_preg=PREG_A, dst_preg=PREG_B,
                       fflags_out=FFlags(nx=True, of=True))
        op2 = _AluStub(src_preg=PREG_B, dst_preg=PREG_C,
                       fflags_out=FFlags(uf=True, of=True))
        op3 = _AluStub(src_preg=PREG_C, dst_preg=PREG_D,
                       fflags_out=FFlags(nv=True))
        await _enqueue(clock, kamlet, [op1, op2, op3])

        for _ in range(60):
            await clock.next_cycle

        sticky = jamlet.sticky_fflags
        assert sticky.nx and sticky.uf and sticky.of and sticky.nv, (
            f"expected nx|uf|of|nv, got {sticky}")
        assert not sticky.dz, f"dz spuriously set: {sticky}"
        assert sticky.to_int() == 0b10111, (
            f"to_int() = {sticky.to_int():#b}, expected 0b10111")

    _run(body)


def test_resource_serializes_dispatch():
    """Two ops claiming the same singleton resource must dispatch sequentially.

    Ops have independent src/dst pregs (no scoreboard hazard). Only the shared
    Resources.IDIV claim should serialize them: op2's compute cycle must lag
    op1's by at least the declared occupancy.
    """
    PREG_A, PREG_B, PREG_C, PREG_D = 40, 41, 42, 43
    OCCUPANCY = 3

    async def body(clock, lamlet):
        kamlet = lamlet.kamlets[0]
        jamlet = kamlet.jamlets[0]
        _seed_preg(jamlet, PREG_A, 0x10)
        _seed_preg(jamlet, PREG_C, 0x20)

        op1 = _AluStub(src_preg=PREG_A, dst_preg=PREG_B,
                       latency=OCCUPANCY,
                       resources={Resources.IDIV: OCCUPANCY})
        op2 = _AluStub(src_preg=PREG_C, dst_preg=PREG_D,
                       latency=OCCUPANCY,
                       resources={Resources.IDIV: OCCUPANCY})
        await _enqueue(clock, kamlet, [op1, op2])

        for _ in range(60):
            await clock.next_cycle

        assert op1.record, "op1 never executed"
        assert op2.record, "op2 never executed (resource never released?)"
        cycle1 = op1.record[0][0]
        cycle2 = op2.record[0][0]
        assert cycle2 - cycle1 >= OCCUPANCY, (
            f"op1 dispatched at cycle {cycle1}, op2 at {cycle2}; "
            f"gap {cycle2 - cycle1} < occupancy {OCCUPANCY} — resource did not stall")

    _run(body)


def test_sticky_vxsat_accumulation():
    """vxsat sticky bit is set by any op that produces vxsat=True."""
    PREG_A, PREG_B, PREG_C, PREG_D = 40, 41, 42, 43

    async def body(clock, lamlet):
        kamlet = lamlet.kamlets[0]
        jamlet = kamlet.jamlets[0]
        _seed_preg(jamlet, PREG_A, 0)

        op_no_sat = _AluStub(src_preg=PREG_A, dst_preg=PREG_B, vxsat_out=False)
        op_sat = _AluStub(src_preg=PREG_B, dst_preg=PREG_C, vxsat_out=True)
        op_no_sat2 = _AluStub(src_preg=PREG_C, dst_preg=PREG_D, vxsat_out=False)
        await _enqueue(clock, kamlet, [op_no_sat, op_sat, op_no_sat2])

        for _ in range(60):
            await clock.next_cycle

        assert jamlet.sticky_vxsat is True, (
            f"sticky_vxsat = {jamlet.sticky_vxsat}, expected True after a "
            f"saturating op")

    _run(body)
