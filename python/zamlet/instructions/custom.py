"""Custom-0 opcode instructions (opcode 0x0B) for VPU optimization.

All use I-type encoding (opcode=0x0B, with rd, rs1, imm fields).
Three instructions distinguished by funct3:
- SetIndexBound (funct3=0): Bounds index register values to lower N bits
- BeginWriteset (funct3=1): Opens a shared writeset scope
- EndWriteset (funct3=2): Closes the writeset scope
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zamlet.register_names import reg_name
from zamlet.kamlet import kinstructions
from zamlet.lamlet import ident_query
from zamlet.monitor import SpanType, CompletionType

if TYPE_CHECKING:
    from zamlet.oamlet.oamlet import Oamlet

logger = logging.getLogger(__name__)


@dataclass
class SetIndexBound:
    """set_index_bound - Bound index register values to lower N bits.

    I-type encoding. If rs1 != 0, N = x[rs1]. If rs1 == 0, N = imm.
    Setting N=0 disables the bound.

    When active, indexed load/store operations mask index values to (2^N - 1),
    bounding the address range to [base, base + 2^N). The lamlet can pre-check
    all pages in this range and skip per-element fault detection.

    Assembly:
      .insn i 0x0b, 0, x0, x0, 10    # immediate, N=10
      .insn i 0x0b, 0, x0, t2, 0     # register, N=x[t2]
    """
    rs1: int
    imm: int

    async def update_state(self, s: 'Oamlet'):
        if self.rs1 != 0:
            await s.scalar.wait_all_regs_ready(0, None, [self.rs1], [])
            n = int.from_bytes(
                s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        else:
            n = self.imm
        s.index_bound_bits = n
        logger.debug(f'{s.clock.cycle}: set_index_bound: n={n}')
        # Broadcast to all kamlets
        instr_ident = await ident_query.get_instr_ident(s)
        kinstr = kinstructions.SetIndexBound(
            index_bound_bits=n, instr_ident=instr_ident)
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4

    def disasm(self, pc: int) -> str:
        if self.rs1 != 0:
            return f'set_index_bound {reg_name(self.rs1)}'
        return f'set_index_bound {self.imm}'

    def __str__(self):
        if self.rs1 != 0:
            return f'SetIndexBound(rs1={reg_name(self.rs1)})'
        return f'SetIndexBound(imm={self.imm})'


@dataclass
class BeginWriteset:
    """begin_writeset - Open a shared writeset scope.

    Allocates a writeset_ident that will be shared by all vector operations
    within the scope. Operations with matching writeset_ident bypass each
    other in the cache table.

    Assembly: .insn i 0x0b, 1, x0, x0, 0
    """

    async def update_state(self, s: 'Oamlet'):
        assert s.active_writeset_ident is None, \
            "begin_writeset while already in a writeset scope"
        ident = s.next_writeset_ident
        s.next_writeset_ident += 1
        s.active_writeset_ident = ident
        logger.debug(f'{s.clock.cycle}: begin_writeset: '
                     f'active_writeset_ident={s.active_writeset_ident}')
        s.pc += 4

    def disasm(self, pc: int) -> str:
        return 'begin_writeset'

    def __str__(self):
        return 'BeginWriteset()'


@dataclass
class EndWriteset:
    """end_writeset - Close the writeset scope.

    Clears active_writeset_ident. Subsequent operations get different
    writeset_idents and naturally serialize against any remaining in-flight
    operations through the cache table.

    Assembly: .insn i 0x0b, 2, x0, x0, 0
    """

    async def update_state(self, s: 'Oamlet'):
        assert s.active_writeset_ident is not None, \
            "end_writeset without an active writeset scope"
        logger.debug(f'{s.clock.cycle}: end_writeset: '
                     f'clearing active_writeset_ident={s.active_writeset_ident}')
        s.active_writeset_ident = None
        s.pc += 4

    def disasm(self, pc: int) -> str:
        return 'end_writeset'

    def __str__(self):
        return 'EndWriteset()'
