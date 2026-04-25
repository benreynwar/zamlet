"""Vector extension instructions.

Reference: riscv-isa-manual/src/v-st-ext.adoc
"""

import logging
import struct
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zamlet.oamlet.oamlet import Oamlet

from zamlet.kamlet import kinstructions
from zamlet import addresses
from zamlet.addresses import Ordering, WordOrder
from zamlet.register_names import reg_name, freg_name
from zamlet.monitor import CompletionType, SpanType
from zamlet.lamlet import ident_query
from zamlet.lamlet.lamlet_waiting_item import LamletWaitingVrgatherBroadcast
from zamlet.synchronization import SyncAggOp
from zamlet.transactions.reduce_sync import ReduceSync
from zamlet.transactions.reg_slide import SlideDirection
from zamlet.instructions.riscv_instr import riscv_instr

logger = logging.getLogger(__name__)


@dataclass
class Vsetvli:
    """VSETVLI - Vector Set Vector Length Immediate.

    Sets vector length and vector type based on AVL (application vector length)
    from rs1 and immediate-encoded VTYPE.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    rd: int
    rs1: int
    vtypei: int

    def __str__(self):
        vlmul = (self.vtypei >> 0) & 0x7
        vsew = (self.vtypei >> 3) & 0x7
        vta = (self.vtypei >> 6) & 0x1
        vma = (self.vtypei >> 7) & 0x1

        lmul_strs = ['m1', 'm2', 'm4', 'm8', 'reserved', 'mf8', 'mf4', 'mf2']
        sew_strs = ['e8', 'e16', 'e32', 'e64', 'e128', 'e256', 'e512', 'e1024']

        lmul_str = lmul_strs[vlmul]
        sew_str = sew_strs[vsew]
        ta_str = 'ta' if vta else 'tu'
        ma_str = 'ma' if vma else 'mu'

        return f'vsetvli\t{reg_name(self.rd)},{reg_name(self.rs1)},{sew_str},{lmul_str},{ta_str},{ma_str}'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        avl = int.from_bytes(rs1_bytes, byteorder='little', signed=False)

        s.vtype = self.vtypei

        vlmul = (self.vtypei >> 0) & 0x7
        vsew = (self.vtypei >> 3) & 0x7
        vta = (self.vtypei >> 6) & 0x1
        vma = (self.vtypei >> 7) & 0x1

        if vlmul <= 3:
            lmul = 1 << vlmul
        else:
            lmul = 1 / (1 << (8 - vlmul))

        sew = 8 << vsew

        vlen_bits = s.params.maxvl_bytes * 8
        vlmax = int((vlen_bits / sew) * lmul)
        logger.info(f'sew is {sew} and lmul is {lmul} vlmax is {vlmax} to avl is {avl}')

        # Per RISC-V V spec section "AVL encoding":
        # - rs1=x0 and rd=x0: keep existing vl (only update vtype).
        # - rs1=x0 and rd!=x0: set vl = VLMAX.
        # - otherwise: set vl = min(avl, vlmax).
        # Reference: riscv-isa-manual/src/v-st-ext.adoc
        if self.rs1 == 0 and self.rd == 0:
            pass  # vl stays unchanged
        elif self.rs1 == 0:
            s.vl = vlmax
        elif avl <= vlmax:
            s.vl = avl
        else:
            s.vl = vlmax

        vl_bytes = s.vl.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, vl_bytes, span_id)
        logger.info(f'Set vl to {s.vl}')
        s.pc += 4


@dataclass
class Vsetivli:
    """VSETIVLI - Vector Set Vector Length Immediate with Immediate AVL.

    Sets vector length and vector type based on immediate-encoded AVL (uimm)
    and immediate-encoded VTYPE.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    rd: int
    uimm: int
    vtypei: int

    def __str__(self):
        vlmul = (self.vtypei >> 0) & 0x7
        vsew = (self.vtypei >> 3) & 0x7
        vta = (self.vtypei >> 6) & 0x1
        vma = (self.vtypei >> 7) & 0x1

        lmul_strs = ['m1', 'm2', 'm4', 'm8', 'reserved', 'mf8', 'mf4', 'mf2']
        sew_strs = ['e8', 'e16', 'e32', 'e64', 'e128', 'e256', 'e512', 'e1024']

        lmul_str = lmul_strs[vlmul]
        sew_str = sew_strs[vsew]
        ta_str = 'ta' if vta else 'tu'
        ma_str = 'ma' if vma else 'mu'

        return f'vsetivli\t{reg_name(self.rd)},{self.uimm},{sew_str},{lmul_str},{ta_str},{ma_str}'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [])
        avl = self.uimm

        s.vtype = self.vtypei

        vlmul = (self.vtypei >> 0) & 0x7
        vsew = (self.vtypei >> 3) & 0x7

        if vlmul <= 3:
            lmul = 1 << vlmul
        else:
            lmul = 1 / (1 << (8 - vlmul))

        sew = 8 << vsew

        vlen_bits = s.params.maxvl_bytes * 8
        vlmax = int((vlen_bits / sew) * lmul)
        logger.info(f'vsetivli: sew={sew} lmul={lmul} vlmax={vlmax} avl={avl}')

        if avl <= vlmax:
            s.vl = avl
        else:
            s.vl = vlmax

        vl_bytes = s.vl.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, vl_bytes, span_id)
        logger.info(f'Set vl to {s.vl}')
        s.pc += 4


@dataclass
class VleV:
    """VLE.V - Vector Load Elements (generic for all element widths).

    Unit-stride load of elements from memory into a vector register.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int
    vm: int
    element_width: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vle{self.element_width}.v\tv{self.vd},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'Oamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        mask_reg = None if self.vm else 0
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        ordering = addresses.Ordering(s.word_order, self.element_width)
        emul = max(1, (self.element_width * s.lmul) // s.sew)
        result = await s.vload(
            self.vd, addr, ordering, s.vl, mask_reg, s.vstart,
            parent_span_id=span_id, emul=emul)
        if s.maybe_trap_vector(
                result, is_store=False,
                fault_addr_fallback=addr + (result.element_index or 0) * (self.element_width // 8)):
            s.monitor.finalize_children(span_id)
            return
        s.vstart = 0
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VlrV:
    """VL*R.V - Vector Load Whole Registers.

    Loads nreg consecutive vector registers from memory as a single unit.
    Used for register restoring. Always loads full registers regardless of vl/vtype.

    Variants: vl1re8.v, vl2re8.v, vl4re8.v, vl8re8.v

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int
    nreg: int

    def __str__(self):
        return f'vl{self.nreg}re8.v\tv{self.vd},({reg_name(self.rs1)})'

    async def update_state(self, s: 'Oamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        # Use the register's element width to determine which address space to use.
        # The register's ordering should still be set from before it was spilled.
        reg_ordering = s.vrf_ordering[self.vd]
        ew = reg_ordering.ew
        n_elements = (s.params.vline_bytes * self.nreg * 8) // ew
        ordering = addresses.Ordering(reg_ordering.word_order, ew)
        result = await s.vload(
            self.vd, addr, ordering, n_elements, None, 0,
            parent_span_id=span_id, emul=self.nreg)
        if s.maybe_trap_vector(
                result, is_store=False,
                fault_addr_fallback=addr + (result.element_index or 0) * (ew // 8)):
            s.monitor.finalize_children(span_id)
            return
        s.vstart = 0
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VseV:
    """VSE.V - Vector Store Elements (generic for all element widths).

    Unit-stride store of elements from vector register to memory.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vs3: int
    rs1: int
    vm: int
    element_width: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vse{self.element_width}.v\tv{self.vs3},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'Oamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        mask_reg = None if self.vm else 0
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        ordering = addresses.Ordering(s.word_order, self.element_width)
        emul = max(1, (self.element_width * s.lmul) // s.sew)
        result = await s.vstore(
            self.vs3, addr, ordering, s.vl, mask_reg, s.vstart,
            parent_span_id=span_id, emul=emul)
        if s.maybe_trap_vector(
                result, is_store=True,
                fault_addr_fallback=addr + (result.element_index or 0) * (self.element_width // 8)):
            s.monitor.finalize_children(span_id)
            return
        s.vstart = 0
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VsrV:
    """VS*R.V - Vector Store Whole Registers.

    Stores nreg consecutive vector registers to memory as a single unit.
    Used for register spilling. Always stores full registers regardless of vl/vtype.

    Variants: vs1r.v, vs2r.v, vs4r.v, vs8r.v

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vs3: int
    rs1: int
    nreg: int

    def __str__(self):
        return f'vs{self.nreg}r.v\tv{self.vs3},({reg_name(self.rs1)})'

    async def update_state(self, s: 'Oamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        # Use the register's element width to determine which address space to use
        reg_ordering = s.vrf_ordering[self.vs3]
        ew = reg_ordering.ew
        n_elements = (s.params.vline_bytes * self.nreg * 8) // ew
        ordering = addresses.Ordering(reg_ordering.word_order, ew)
        result = await s.vstore(
            self.vs3, addr, ordering, n_elements, None, 0,
            parent_span_id=span_id, emul=self.nreg)
        if s.maybe_trap_vector(
                result, is_store=True,
                fault_addr_fallback=addr + (result.element_index or 0) * (ew // 8)):
            s.monitor.finalize_children(span_id)
            return
        s.vstart = 0
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VlseV:
    """VLSE.V - Vector Load Strided Elements.

    Constant-stride load of elements from memory into a vector register.
    Element i is loaded from address (rs1 + i * rs2).

    Reference: riscv-isa-manual/src/v-st-ext.adoc lines 1602-1647
    """
    vd: int
    rs1: int
    rs2: int
    vm: int
    element_width: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vlse{self.element_width}.v\tv{self.vd},({reg_name(self.rs1)}),{reg_name(self.rs2)}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs2_bytes = s.scalar.read_reg(self.rs2)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        stride = int.from_bytes(rs2_bytes, byteorder='little', signed=True)
        mask_reg = None if self.vm else 0
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        ordering = addresses.Ordering(s.word_order, self.element_width)
        emul = max(1, (self.element_width * s.lmul) // s.sew)
        result = await s.vload(
            self.vd, addr, ordering, s.vl, mask_reg, s.vstart,
            parent_span_id=span_id, emul=emul, stride_bytes=stride)
        if s.maybe_trap_vector(
                result, is_store=False,
                fault_addr_fallback=addr + (result.element_index or 0) * stride):
            s.monitor.finalize_children(span_id)
            return
        s.vstart = 0
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VsseV:
    """VSSE.V - Vector Store Strided Elements.

    Constant-stride store of elements from vector register to memory.
    Element i is stored to address (rs1 + i * rs2).

    Reference: riscv-isa-manual/src/v-st-ext.adoc lines 1602-1647
    """
    vs3: int
    rs1: int
    rs2: int
    vm: int
    element_width: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vsse{self.element_width}.v\tv{self.vs3},({reg_name(self.rs1)}),{reg_name(self.rs2)}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs2_bytes = s.scalar.read_reg(self.rs2)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        stride = int.from_bytes(rs2_bytes, byteorder='little', signed=True)
        mask_reg = None if self.vm else 0
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        ordering = addresses.Ordering(s.word_order, self.element_width)
        emul = max(1, (self.element_width * s.lmul) // s.sew)
        result = await s.vstore(
            self.vs3, addr, ordering, s.vl, mask_reg, s.vstart,
            parent_span_id=span_id, emul=emul, stride_bytes=stride)
        if s.maybe_trap_vector(
                result, is_store=True,
                fault_addr_fallback=addr + (result.element_index or 0) * stride):
            s.monitor.finalize_children(span_id)
            return
        s.vstart = 0
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VlsegV:
    """VLSEG - Vector Load Segment.

    Unit-stride load of multiple fields (segments) from memory into consecutive
    vector registers. Each segment contains nf fields stored contiguously in memory.

    Example: vlseg3e8.v v0, (a0) loads RGB pixels:
      Memory: R0 G0 B0 R1 G1 B1 R2 G2 B2 ...
      v0: R0 R1 R2 ...
      v1: G0 G1 G2 ...
      v2: B0 B1 B2 ...

    Reference: riscv-isa-manual/src/v-st-ext.adoc lines 1758-1888
    """
    vd: int
    rs1: int
    vm: int
    element_width: int
    nf: int  # Number of fields (2-8)

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vlseg{self.nf}e{self.element_width}.v\tv{self.vd},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)
        logger.debug(f'{s.clock.cycle}: VLSEG{self.nf}E{self.element_width}.V: '
                    f'vd=v{self.vd}, addr=0x{addr:x}, vl={s.vl}, nf={self.nf}, '
                    f'masked={not self.vm}, mask_reg={mask_reg}')
        ordering = addresses.Ordering(s.word_order, self.element_width)
        await s.vsegload(self.vd, addr, ordering, s.vl, mask_reg, s.vstart, self.nf)
        s.monitor.finalize_children(span_id)
        s.pc += 4
        logger.debug(f'Loaded segment into vd=v{self.vd} through v{self.vd + self.nf - 1}')


@dataclass
class VssegV:
    """VSSEG - Vector Store Segment.

    Unit-stride store of multiple fields (segments) from consecutive vector
    registers to memory. Each segment contains nf fields stored contiguously.

    Example: vsseg3e8.v v0, (a0) stores RGB pixels:
      v0: R0 R1 R2 ...
      v1: G0 G1 G2 ...
      v2: B0 B1 B2 ...
      Memory: R0 G0 B0 R1 G1 B1 R2 G2 B2 ...

    Reference: riscv-isa-manual/src/v-st-ext.adoc lines 1758-1888
    """
    vs3: int
    rs1: int
    vm: int
    element_width: int
    nf: int  # Number of fields (2-8)

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vsseg{self.nf}e{self.element_width}.v\tv{self.vs3},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)
        logger.debug(f'{s.clock.cycle}: VSSEG{self.nf}E{self.element_width}.V: '
                    f'vs3=v{self.vs3}, addr=0x{addr:x}, vl={s.vl}, nf={self.nf}, '
                    f'masked={not self.vm}, mask_reg={mask_reg}')
        ordering = addresses.Ordering(s.word_order, self.element_width)
        await s.vsegstore(self.vs3, addr, ordering, s.vl, mask_reg, s.vstart, self.nf)
        s.monitor.finalize_children(span_id)
        s.pc += 4
        logger.debug(f'Stored segment from vs3=v{self.vs3} through v{self.vs3 + self.nf - 1}')


@dataclass
class VArithVxFloat:
    """Generic vector-scalar floating-point arithmetic instruction.

    Used for vfadd.vf, vfmacc.vf, etc.
    """
    vd: int
    rs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp

    _ACCUM_OPS = kinstructions.ACCUM_OPS

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'v{self.op.value}.vf\tv{self.vd},{freg_name(self.rs1)},v{self.vs2}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        await s.scalar.wait_all_regs_ready(None, None, [], [self.rs1])

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order
        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vs2, n_vlines)
        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        if self.op in self._ACCUM_OPS:
            await s.ensure_vrf_ordering(self.vd, element_width, span_id)
        s.set_vrf_ordering(self.vd, element_width)

        scalar_bytes = s.scalar.read_freg(self.rs1)

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VArithVxOp(
            op=self.op,
            dst=self.vd,
            scalar_bytes=scalar_bytes,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            is_float=True,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VCmpVi:
    """Vector compare, vector-immediate form.

    vd.mask[i] = (vs2[i] <op> simm5) ? 1 : 0
    """
    vd: int
    vs2: int
    simm5: int
    vm: int
    op: kinstructions.VCmpOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vm{self.op.value}.vi\tv{self.vd},v{self.vs2},{self.simm5}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_dst_vline = vline_bytes * 8  # 1 bit per element
        n_dst_vlines = (s.vl + elements_in_dst_vline - 1) // elements_in_dst_vline

        mask_ordering = Ordering(s.word_order, 1)
        for i in range(n_dst_vlines):
            s.vrf_ordering[self.vd + i] = mask_ordering

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VCmpViOp(
            op=self.op,
            dst=self.vd,
            src=self.vs2,
            simm5=self.simm5,
            n_elements=s.vl,
            element_width=element_width,
            ordering=s.vrf_ordering[self.vs2],
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VCmpVv:
    """Vector compare, vector-vector form.

    vd.mask[i] = (vs2[i] <op> vs1[i]) ? 1 : 0
    """
    vd: int
    vs2: int
    vs1: int
    vm: int
    op: kinstructions.VCmpOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vm{self.op.value}.vv\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.ensure_vrf_ordering(self.vs1, element_width, span_id)

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_dst_vline = vline_bytes * 8  # 1 bit per element
        n_dst_vlines = (s.vl + elements_in_dst_vline - 1) // elements_in_dst_vline

        mask_ordering = Ordering(s.word_order, 1)
        for i in range(n_dst_vlines):
            s.vrf_ordering[self.vd + i] = mask_ordering

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VCmpVvOp(
            op=self.op,
            dst=self.vd,
            src1=self.vs1,
            src2=self.vs2,
            n_elements=s.vl,
            element_width=element_width,
            ordering=s.vrf_ordering[self.vs2],
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VCmpVx:
    """Vector compare, vector-scalar form.

    vd.mask[i] = (vs2[i] <op> x[rs1]) ? 1 : 0
    """
    vd: int
    vs2: int
    rs1: int
    vm: int
    op: kinstructions.VCmpOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return (f'vm{self.op.value}.vx\tv{self.vd},v{self.vs2},'
                f'{reg_name(self.rs1)}{vm_str}')

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_dst_vline = vline_bytes * 8  # 1 bit per element
        n_dst_vlines = (s.vl + elements_in_dst_vline - 1) // elements_in_dst_vline

        mask_ordering = Ordering(s.word_order, 1)
        for i in range(n_dst_vlines):
            s.vrf_ordering[self.vd + i] = mask_ordering

        rs1_bytes = s.scalar.read_reg(self.rs1)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VCmpVxOp(
            op=self.op,
            dst=self.vd,
            src=self.vs2,
            scalar_bytes=rs1_bytes,
            n_elements=s.vl,
            element_width=element_width,
            ordering=s.vrf_ordering[self.vs2],
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


_VCMP_FLOAT_MNEMONIC = {
    kinstructions.VCmpOp.EQ: 'vmfeq',
    kinstructions.VCmpOp.NE: 'vmfne',
    kinstructions.VCmpOp.LT: 'vmflt',
    kinstructions.VCmpOp.LE: 'vmfle',
    kinstructions.VCmpOp.GT: 'vmfgt',
    kinstructions.VCmpOp.GE: 'vmfge',
}


@dataclass
class VCmpVvFloat:
    """Floating-point vector compare, vector-vector form.

    vd.mask[i] = (vs2[i] <op> vs1[i]) ? 1 : 0
    """
    vd: int
    vs2: int
    vs1: int
    vm: int
    op: kinstructions.VCmpOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        mnemonic = _VCMP_FLOAT_MNEMONIC[self.op]
        return f'{mnemonic}.vv\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.ensure_vrf_ordering(self.vs1, element_width, span_id)

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_dst_vline = vline_bytes * 8
        n_dst_vlines = (s.vl + elements_in_dst_vline - 1) // elements_in_dst_vline

        mask_ordering = Ordering(s.word_order, 1)
        for i in range(n_dst_vlines):
            s.vrf_ordering[self.vd + i] = mask_ordering

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VCmpVvOp(
            op=self.op,
            dst=self.vd,
            src1=self.vs1,
            src2=self.vs2,
            n_elements=s.vl,
            element_width=element_width,
            ordering=s.vrf_ordering[self.vs2],
            is_float=True,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VCmpVxFloat:
    """Floating-point vector compare, vector-scalar form.

    vd.mask[i] = (vs2[i] <op> f[rs1]) ? 1 : 0
    """
    vd: int
    vs2: int
    rs1: int
    vm: int
    op: kinstructions.VCmpOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        mnemonic = _VCMP_FLOAT_MNEMONIC[self.op]
        return (f'{mnemonic}.vf\tv{self.vd},v{self.vs2},'
                f'{freg_name(self.rs1)}{vm_str}')

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        await s.scalar.wait_all_regs_ready(None, None, [], [self.rs1])

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_dst_vline = vline_bytes * 8
        n_dst_vlines = (s.vl + elements_in_dst_vline - 1) // elements_in_dst_vline

        mask_ordering = Ordering(s.word_order, 1)
        for i in range(n_dst_vlines):
            s.vrf_ordering[self.vd + i] = mask_ordering

        rs1_bytes = s.scalar.read_freg(self.rs1)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VCmpVxOp(
            op=self.op,
            dst=self.vd,
            src=self.vs2,
            scalar_bytes=rs1_bytes,
            n_elements=s.vl,
            element_width=element_width,
            ordering=s.vrf_ordering[self.vs2],
            is_float=True,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VmLogicMm:
    """Vector mask-mask logical op: vm{and,andn,or,orn,xor,nand,nor,xnor}.mm.

    Operand convention per RVV: `vm<op>.mm vd, vs2, vs1`
      vd.mask[i] = op(vs2.mask[i], vs1.mask[i])  for i in [vstart, vl)

    Pseudo-ops (preserved in disassembly):
      vmmv.m  vd, vs  => vmand.mm  vd, vs, vs
      vmclr.m vd      => vmxor.mm  vd, vd, vd
      vmset.m vd      => vmxnor.mm vd, vd, vd
      vmnot.m vd, vs  => vmnand.mm vd, vs, vs

    Mask logical operations are always unmasked.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs2: int
    vs1: int
    op: kinstructions.VmLogicOp

    def __str__(self):
        same_srcs = self.vs2 == self.vs1
        vd_eq_src = same_srcs and self.vd == self.vs2
        if self.op == kinstructions.VmLogicOp.AND and same_srcs:
            return f'vmmv.m\tv{self.vd},v{self.vs2}'
        if self.op == kinstructions.VmLogicOp.XOR and vd_eq_src:
            return f'vmclr.m\tv{self.vd}'
        if self.op == kinstructions.VmLogicOp.XNOR and vd_eq_src:
            return f'vmset.m\tv{self.vd}'
        if self.op == kinstructions.VmLogicOp.NAND and same_srcs:
            return f'vmnot.m\tv{self.vd},v{self.vs2}'
        return f'{self.op.value}.mm\tv{self.vd},v{self.vs2},v{self.vs1}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        # RVV: mask-register logical instructions operate on a single vector
        # register regardless of LMUL (v-st-ext.adoc:4046-4048). vl at ew=1
        # is therefore bounded by one vline's worth of bits.
        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_vline = vline_bytes * 8  # 1 bit per mask element
        assert s.vl <= elements_in_vline, (
            f'vl={s.vl} exceeds one mask vline ({elements_in_vline} bits)')

        # Sources must already be at ew=1 (mask layout). No auto-remap today;
        # see docs/TODO.md "ew remap infrastructure".
        vs2_ord = s.vrf_ordering[self.vs2]
        vs1_ord = s.vrf_ordering[self.vs1]
        assert vs2_ord is not None and vs2_ord.ew == 1, (
            f'v{self.vs2} must be at ew=1 for mask logical, got {vs2_ord}')
        assert vs1_ord is not None and vs1_ord.ew == 1, (
            f'v{self.vs1} must be at ew=1 for mask logical, got {vs1_ord}')

        await s.await_vreg_write_pending(self.vd, 1)

        # Prestart bits (indices < vstart) are preserved bitwise via RMW in the
        # kinstr. For those bits to be meaningful under ew=1 interpretation the
        # dst should already be at ew=1; we don't enforce that today (vstart is
        # typically 0 in practice).
        s.vrf_ordering[self.vd] = Ordering(s.word_order, 1)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VmLogicMmOp(
            op=self.op,
            dst=self.vd,
            src1=self.vs2,
            src2=self.vs1,
            start_index=s.vstart,
            n_elements=s.vl,
            word_order=s.word_order,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VmvVi:
    """VMV.V.I - Vector Move Immediate.

    vd[i] = imm (splat immediate to all active elements)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    simm5: int

    def __str__(self):
        return f'vmv.v.i\tv{self.vd},{self.simm5}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        await s.await_vreg_write_pending(self.vd, s.emul_for_eew(element_width))
        s.set_vrf_ordering(self.vd, element_width)

        sign_extended_imm = self.simm5 if self.simm5 < 16 else self.simm5 - 32

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VBroadcastOp(
            dst=self.vd,
            scalar=sign_extended_imm,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VmvVx:
    """VMV.V.X - Vector Move Scalar Register.

    vd[i] = x[rs1] (splat scalar to all active elements)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int

    def __str__(self):
        return f'vmv.v.x\tv{self.vd},{reg_name(self.rs1)}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        rs1_bytes = s.scalar.read_reg(self.rs1)
        scalar_val = int.from_bytes(rs1_bytes, byteorder='little', signed=True)

        await s.await_vreg_write_pending(self.vd, s.emul_for_eew(element_width))
        s.set_vrf_ordering(self.vd, element_width)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VBroadcastOp(
            dst=self.vd,
            scalar=scalar_val,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VmergeVx:
    """vmerge.vxm vd, vs2, rs1, v0

    vd[i] = v0.mask[i] ? x[rs1] : vs2[i]
    Always uses v0 as mask (vm=0 encoding).
    """
    vd: int
    rs1: int
    vs2: int

    def __str__(self):
        return f'vmerge.vxm\tv{self.vd},v{self.vs2},{reg_name(self.rs1)},v0'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vs2, n_vlines)
        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        s.set_vrf_ordering(self.vd, element_width)
        await s.ensure_vrf_ordering(0, 1, span_id)

        rs1_bytes = s.scalar.read_reg(self.rs1)
        scalar_val = int.from_bytes(rs1_bytes[:element_width // 8],
                                    byteorder='little', signed=True)

        # Step 1: copy vs2 to vd (unmasked)
        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VUnaryOvOp(
            op=kinstructions.VUnaryOp.COPY,
            dst=self.vd,
            src=self.vs2,
            n_elements=s.vl,
            dst_ew=element_width,
            src_ew=element_width,
            word_order=word_order,
            mask_reg=None,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)

        # Step 2: broadcast rs1 to vd where v0 mask is set
        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VBroadcastOp(
            dst=self.vd,
            scalar=scalar_val,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            instr_ident=instr_ident,
            mask_reg=0,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)

        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VmergeVvm:
    """vmerge.vvm vd, vs2, vs1, v0

    vd[i] = v0.mask[i] ? vs1[i] : vs2[i]
    Always uses v0 as mask (vm=0 encoding).
    """
    vd: int
    vs1: int
    vs2: int

    def __str__(self):
        return f'vmerge.vvm\tv{self.vd},v{self.vs2},v{self.vs1},v0'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vs2, n_vlines)
        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.await_vreg_write_pending(self.vs1, n_vlines)
        await s.ensure_vrf_ordering(self.vs1, element_width, span_id)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        s.set_vrf_ordering(self.vd, element_width)
        await s.ensure_vrf_ordering(0, 1, span_id)

        if self.vd == self.vs1 and self.vd == self.vs2:
            # vd == vs1 == vs2: result is always vd, no-op.
            pass
        elif self.vd == self.vs2:
            # vd == vs2: just copy vs1 where mask is set.
            instr_ident = await s.get_instr_ident()
            kinstr = kinstructions.VUnaryOvOp(
                op=kinstructions.VUnaryOp.COPY,
                dst=self.vd,
                src=self.vs1,
                n_elements=s.vl,
                dst_ew=element_width,
                src_ew=element_width,
                word_order=word_order,
                mask_reg=0,
                instr_ident=instr_ident,
            )
            await s.add_to_instruction_buffer(kinstr, span_id)
        elif self.vd == self.vs1:
            # vd == vs1: just copy vs2 where mask is NOT set.
            instr_ident = await s.get_instr_ident()
            kinstr = kinstructions.VUnaryOvOp(
                op=kinstructions.VUnaryOp.COPY,
                dst=self.vd,
                src=self.vs2,
                n_elements=s.vl,
                dst_ew=element_width,
                src_ew=element_width,
                word_order=word_order,
                mask_reg=0,
                instr_ident=instr_ident,
                invert_mask=True,
            )
            await s.add_to_instruction_buffer(kinstr, span_id)
        else:
            # No overlap: copy vs2 unconditionally, then vs1 where mask set.
            instr_ident = await s.get_instr_ident()
            kinstr = kinstructions.VUnaryOvOp(
                op=kinstructions.VUnaryOp.COPY,
                dst=self.vd,
                src=self.vs2,
                n_elements=s.vl,
                dst_ew=element_width,
                src_ew=element_width,
                word_order=word_order,
                mask_reg=None,
                instr_ident=instr_ident,
            )
            await s.add_to_instruction_buffer(kinstr, span_id)

            instr_ident = await s.get_instr_ident()
            kinstr = kinstructions.VUnaryOvOp(
                op=kinstructions.VUnaryOp.COPY,
                dst=self.vd,
                src=self.vs1,
                n_elements=s.vl,
                dst_ew=element_width,
                src_ew=element_width,
                word_order=word_order,
                mask_reg=0,
                instr_ident=instr_ident,
            )
            await s.add_to_instruction_buffer(kinstr, span_id)

        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VmergeVim:
    """vmerge.vim vd, vs2, imm, v0

    vd[i] = v0.mask[i] ? imm : vs2[i]
    Always uses v0 as mask (vm=0 encoding).
    """
    vd: int
    vs2: int
    simm5: int

    def __str__(self):
        return f'vmerge.vim\tv{self.vd},v{self.vs2},{self.simm5},v0'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vs2, n_vlines)
        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        s.set_vrf_ordering(self.vd, element_width)
        await s.ensure_vrf_ordering(0, 1, span_id)

        # Sign-extend 5-bit immediate
        scalar_val = self.simm5 if self.simm5 < 16 else self.simm5 - 32

        # Step 1: copy vs2 to vd (unmasked)
        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VUnaryOvOp(
            op=kinstructions.VUnaryOp.COPY,
            dst=self.vd,
            src=self.vs2,
            n_elements=s.vl,
            dst_ew=element_width,
            src_ew=element_width,
            word_order=word_order,
            mask_reg=None,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)

        # Step 2: broadcast immediate to vd where v0 mask is set
        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VBroadcastOp(
            dst=self.vd,
            scalar=scalar_val,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            instr_ident=instr_ident,
            mask_reg=0,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)

        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VcpopM:
    """VCPOP.M - Population count of active mask bits.

    x[rd] = sum_i (vs2.mask[i] && (vm || v0.mask[i])) for i in [0, vl).

    Writes rd even when vl == 0 (with the value 0). Spec requires vstart == 0.

    Decomposition:
      if vm == 0: tmp_mask = vs2 AND v0          (VmLogicMmOp)
      per-jamlet popcount of the mask into tmp32 (MaskPopcountLocal)
      tree-reduce SUM over tmp32 into result_vreg[0] with no vs1 accumulator
      rd <- result_vreg[0]

    Reference: riscv-isa-manual/src/v-st-ext.adoc (sec "vcpop.m")
    """
    rd: int
    vs2: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vcpop.m\t{reg_name(self.rd)},v{self.vs2}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        assert s.vstart == 0, 'vcpop.m requires vstart == 0 (spec v-st-ext.adoc:4159)'

        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        if s.vl == 0:
            s.scalar.write_reg(self.rd, bytes(8), span_id)
            s.monitor.finalize_children(span_id)
            s.pc += 4
            return

        await s.await_vreg_write_pending(self.vs2, 1)
        await s.ensure_vrf_ordering(self.vs2, 1, span_id)

        word_order = s.word_order
        accum_ew = 32
        accum_ordering = Ordering(word_order, accum_ew)
        mask_ordering = Ordering(word_order, 1)
        elements_in_vline_ew32 = s.params.vline_bytes * 8 // accum_ew

        temps = s.alloc_temp_regs(2 if self.vm else 3)
        tmp_count, result_vreg = temps[0], temps[1]

        if self.vm:
            src_mask = self.vs2
        else:
            tmp_mask = temps[2]
            await s.await_vreg_write_pending(tmp_mask, 1)
            await s.ensure_vrf_ordering(0, 1, span_id)
            instr_ident = await s.get_instr_ident()
            await s.add_to_instruction_buffer(
                kinstructions.VmLogicMmOp(
                    op=kinstructions.VmLogicOp.AND,
                    dst=tmp_mask, src1=self.vs2, src2=0,
                    start_index=0, n_elements=s.vl,
                    word_order=word_order,
                    instr_ident=instr_ident,
                ), span_id)
            s.vrf_ordering[tmp_mask] = mask_ordering
            src_mask = tmp_mask

        for reg in (tmp_count, result_vreg):
            await s.await_vreg_write_pending(reg, 1)
            s.vrf_ordering[reg] = accum_ordering

        instr_ident = await s.get_instr_ident()
        await s.add_to_instruction_buffer(
            kinstructions.MaskPopcountLocal(
                dst=tmp_count, src=src_mask,
                n_elements=s.vl, word_order=word_order,
                instr_ident=instr_ident,
            ), span_id)

        await s.handle_vreduction_instr(
            op=kinstructions.VRedOp.SUM,
            dst=result_vreg,
            src_vector=tmp_count,
            src_scalar_reg=None,
            mask_reg=None,
            n_elements=elements_in_vline_ew32,
            src_ew=accum_ew,
            accum_ew=accum_ew,
            word_order=word_order,
            vlmax=elements_in_vline_ew32,
            parent_span_id=span_id,
        )

        value_future = await s.read_register_element(
            result_vreg, element_index=0, element_width=accum_ew)
        s.scalar.write_reg_future(self.rd, value_future, span_id)

        await s.free_temp_regs(temps, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VfirstM:
    """VFIRST.M - Find first set mask bit.

    x[rd] = lowest i in [0, vl) with vs2.mask[i] == 1 && (vm || v0.mask[i]),
    else -1. vstart must be 0.

    Decomposition:
      if vm == 0: tmp_mask = vs2 AND v0          (VmLogicMmOp)
      ReduceSync(MIN_EL_INDEX) on tmp_mask -> result_vreg (every ew=32 slot
        holds the aggregate across all jamlets; sentinel 0xFFFFFFFF when
        no active bit is set)
      rd <- result_vreg[0] (sign-extended: 0xFFFFFFFF -> -1)

    Reference: riscv-isa-manual/src/v-st-ext.adoc (sec "vfirst.m")
    """
    rd: int
    vs2: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vfirst.m\t{reg_name(self.rd)},v{self.vs2}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        assert s.vstart == 0, 'vfirst.m requires vstart == 0 (spec v-st-ext.adoc)'

        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        if s.vl == 0:
            s.scalar.write_reg(self.rd, (-1).to_bytes(8, 'little', signed=True),
                               span_id)
            s.monitor.finalize_children(span_id)
            s.pc += 4
            return

        await s.await_vreg_write_pending(self.vs2, 1)
        await s.ensure_vrf_ordering(self.vs2, 1, span_id)

        word_order = s.word_order
        accum_ew = 32
        accum_ordering = Ordering(word_order, accum_ew)
        mask_ordering = Ordering(word_order, 1)

        temps = s.alloc_temp_regs(1 if self.vm else 2)
        result_vreg = temps[0]

        if self.vm:
            src_mask = self.vs2
        else:
            tmp_mask = temps[1]
            await s.await_vreg_write_pending(tmp_mask, 1)
            await s.ensure_vrf_ordering(0, 1, span_id)
            logic_ident = await s.get_instr_ident()
            await s.add_to_instruction_buffer(
                kinstructions.VmLogicMmOp(
                    op=kinstructions.VmLogicOp.AND,
                    dst=tmp_mask, src1=self.vs2, src2=0,
                    start_index=0, n_elements=s.vl,
                    word_order=word_order,
                    instr_ident=logic_ident,
                ), span_id)
            s.vrf_ordering[tmp_mask] = mask_ordering
            src_mask = tmp_mask

        await s.await_vreg_write_pending(result_vreg, 1)
        s.vrf_ordering[result_vreg] = accum_ordering

        reduce_ident = await s.get_instr_ident()
        reduce_kinstr = ReduceSync(
            dst=result_vreg, src=src_mask,
            op=SyncAggOp.MINU, width=32,
            n_elements=s.vl,
            sync_ident=reduce_ident,
            word_order=word_order,
            instr_ident=reduce_ident,
            src_is_mask=True,
        )
        await s.add_to_instruction_buffer(reduce_kinstr, span_id)
        kinstr_span_id = s.monitor.get_kinstr_span_id(reduce_ident)
        s.monitor.create_sync_local_span(
            reduce_ident, 0, -1, kinstr_span_id)
        s.synchronizer.local_event(
            reduce_ident, value=None,
            op=SyncAggOp.MINU, width=32)

        value_future = await s.read_register_element(
            result_vreg, element_index=0, element_width=accum_ew)
        s.scalar.write_reg_future(self.rd, value_future, span_id)

        await s.free_temp_regs(temps, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VmsFirstMask:
    """VMSBF.M / VMSIF.M / VMSOF.M - masks around the first active set bit.

    Decomposition:
      if vm == 0: tmp_mask = vs2 AND v0
      ReduceSync(MIN_EL_INDEX) on src mask -> result_vreg
      SetMaskBits(result_vreg, vd, mode)
    """
    vd: int
    vs2: int
    vm: int
    mode: kinstructions.SetMaskBitsMode
    mnemonic: str

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'{self.mnemonic}\tv{self.vd},v{self.vs2}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        assert s.vstart == 0, f'{self.mnemonic} requires vstart == 0'
        assert self.vd != self.vs2, (
            f'{self.mnemonic}: vd must not overlap vs2')
        assert self.vm == 1 or self.vd != 0, (
            f'{self.mnemonic}: masked form vd must not overlap v0')

        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        await s.await_vreg_write_pending(self.vd, 1)
        s.vrf_ordering[self.vd] = Ordering(s.word_order, 1)

        if s.vl > 0:
            await s.await_vreg_write_pending(self.vs2, 1)
            await s.ensure_vrf_ordering(self.vs2, 1, span_id)

            word_order = s.word_order
            accum_ew = 32
            accum_ordering = Ordering(word_order, accum_ew)
            mask_ordering = Ordering(word_order, 1)

            temps = s.alloc_temp_regs(1 if self.vm else 2)
            result_vreg = temps[0]

            if self.vm:
                src_mask = self.vs2
            else:
                tmp_mask = temps[1]
                await s.await_vreg_write_pending(tmp_mask, 1)
                await s.ensure_vrf_ordering(0, 1, span_id)
                logic_ident = await s.get_instr_ident()
                await s.add_to_instruction_buffer(
                    kinstructions.VmLogicMmOp(
                        op=kinstructions.VmLogicOp.AND,
                        dst=tmp_mask, src1=self.vs2, src2=0,
                        start_index=0, n_elements=s.vl,
                        word_order=word_order,
                        instr_ident=logic_ident,
                    ), span_id)
                s.vrf_ordering[tmp_mask] = mask_ordering
                src_mask = tmp_mask

            await s.await_vreg_write_pending(result_vreg, 1)
            s.vrf_ordering[result_vreg] = accum_ordering

            reduce_ident = await s.get_instr_ident()
            reduce_kinstr = ReduceSync(
                dst=result_vreg, src=src_mask,
                op=SyncAggOp.MINU, width=32,
                n_elements=s.vl,
                sync_ident=reduce_ident,
                word_order=word_order,
                instr_ident=reduce_ident,
                src_is_mask=True,
            )
            await s.add_to_instruction_buffer(reduce_kinstr, span_id)
            kinstr_span_id = s.monitor.get_kinstr_span_id(reduce_ident)
            s.monitor.create_sync_local_span(
                reduce_ident, 0, -1, kinstr_span_id)
            s.synchronizer.local_event(
                reduce_ident, value=None,
                op=SyncAggOp.MINU, width=32)

            set_ident = await s.get_instr_ident()
            await s.add_to_instruction_buffer(
                kinstructions.SetMaskBits(
                    mode=self.mode,
                    dst=self.vd,
                    src=result_vreg,
                    n_elements=s.vl,
                    word_order=word_order,
                    instr_ident=set_ident,
                    mask_reg=None if self.vm else 0,
                ), span_id)

            await s.free_temp_regs(temps, span_id)

        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VmvXs:
    """VMV.X.S - Vector Move to Scalar Register.

    x[rd] = vs2[0] (extract element 0 from vector register)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    rd: int
    vs2: int

    def __str__(self):
        return f'vmv.x.s\t{reg_name(self.rd)},v{self.vs2}'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)

        # Read element 0 from the vector register
        value_future = await s.read_register_element(self.vs2, element_index=0, element_width=element_width)
        s.scalar.write_reg_future(self.rd, value_future, span_id)
        s.pc += 4


@dataclass
class VfmvFs:
    """VFMV.F.S - Floating-Point Vector-to-Scalar Move.

    f[rd] = vs2[0] (extract element 0 into an FP scalar register).
    Ignores LMUL. Executes even if vstart >= vl or vl == 0.

    NaN-boxing (per RISC-V F spec, required when SEW < FLEN) is not applied
    here; we reuse LamletWaitingReadRegElement which sign-extends into 8
    bytes. This matches the existing zero-pad convention used by every
    other narrow-FP producer in the model. Broader FP-correctness fix is
    tracked in docs/TODO.md.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    (sec "Floating-Point Scalar Move Instructions")
    """
    rd: int
    vs2: int

    def __str__(self):
        return f'vfmv.f.s\t{freg_name(self.rd)},v{self.vs2}'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)

        value_future = await s.read_register_element(
            self.vs2, element_index=0, element_width=element_width)
        s.scalar.write_freg_future(self.rd, value_future, span_id)
        s.pc += 4


@dataclass
class VmvSx:
    """VMV.S.X - Vector Move from Scalar Register.

    vd[0] = x[rs1] (write scalar to element 0 of vector register)
    """
    vd: int
    rs1: int

    def __str__(self):
        return f'vmv.s.x\tv{self.vd},{reg_name(self.rs1)}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        await s.ensure_vrf_ordering(
            self.vd, element_width, span_id, allow_uninitialized=True)

        rs1_bytes = s.scalar.read_reg(self.rs1)
        scalar_val = int.from_bytes(rs1_bytes, byteorder='little', signed=True)

        ordering = s.vrf_ordering[self.vd]
        vw_index = 0 % s.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
            s.params, ordering.word_order, vw_index)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.WriteRegElement(
            dst=self.vd,
            element_index=0,
            element_width=element_width,
            ordering=ordering,
            value=scalar_val,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id, k_index)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VfmvSf:
    """VFMV.S.F - Floating-Point Scalar-to-Vector Move.

    vd[0] = f[rs1] (write FP scalar to element 0 of vector register).
    Ignores LMUL. Per spec: if vstart >= vl, no operation is performed.
    The masked encoding is reserved; only the unmasked form is decoded.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    (sec "Floating-Point Scalar Move Instructions")
    """
    vd: int
    rs1: int

    def __str__(self):
        return f'vfmv.s.f\tv{self.vd},{freg_name(self.rs1)}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        await s.scalar.wait_all_regs_ready(None, None, [], [self.rs1])

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        await s.ensure_vrf_ordering(
            self.vd, element_width, span_id, allow_uninitialized=True)

        # Per spec: vstart >= vl => no-op (destination register not updated).
        if s.vstart >= s.vl:
            s.monitor.finalize_children(span_id)
            s.pc += 4
            return

        rs1_bytes = s.scalar.read_freg(self.rs1)
        # Truncate the (zero-padded, today) freg bytes to SEW before sign-extending.
        # When proper NaN-boxing lands, this site will need a NaN-box check that
        # substitutes canonical qNaN on violation (see docs/TODO.md).
        eb = element_width // 8
        scalar_val = int.from_bytes(rs1_bytes[:eb], byteorder='little', signed=True)

        ordering = s.vrf_ordering[self.vd]
        vw_index = 0 % s.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
            s.params, ordering.word_order, vw_index)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.WriteRegElement(
            dst=self.vd,
            element_index=0,
            element_width=element_width,
            ordering=ordering,
            value=scalar_val,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id, k_index)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VmvNr:
    """Whole register move: copy nreg consecutive registers.

    vmvNr.v vd, vs2 — copies vs2..vs2+(nreg-1) to vd..vd+(nreg-1).
    No element width interpretation, no masking. Copies raw register bytes.
    """
    vd: int
    vs2: int
    nreg: int

    def __str__(self):
        return f'vmv{self.nreg}r.v\tv{self.vd},v{self.vs2}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        word_order = s.word_order

        for i in range(self.nreg):
            src_reg = self.vs2 + i
            dst_reg = self.vd + i
            assert s.vrf_ordering[src_reg] is not None, (
                f'vmv{self.nreg}r.v: source v{src_reg} has no ordering')
            copy_ew = s.vrf_ordering[src_reg].ew
            s.vrf_ordering[dst_reg] = s.vrf_ordering[src_reg]
            elements_per_vline = s.params.vline_bytes * 8 // copy_ew

            instr_ident = await s.get_instr_ident()
            kinstr = kinstructions.VUnaryOvOp(
                op=kinstructions.VUnaryOp.COPY,
                dst=dst_reg,
                src=src_reg,
                n_elements=elements_per_vline,
                dst_ew=copy_ew,
                src_ew=copy_ew,
                word_order=word_order,
                mask_reg=None,
                instr_ident=instr_ident,
            )
            await s.add_to_instruction_buffer(kinstr, span_id)

        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class Vreduction:
    """Generic vector reduction.

    vd[0] = reduce_op(vs1[0], vs2[*])
    Reduces all active elements of vs2 with element 0 of vs1 using the specified operation.

    Covers single-width integer, single-width float, widening integer, and widening float
    reductions (excluding ordered float reductions).
    """
    vd: int
    vs2: int
    vs1: int
    vm: int
    op: kinstructions.VRedOp

    _MNEMONIC = {
        kinstructions.VRedOp.SUM: 'vredsum',
        kinstructions.VRedOp.AND: 'vredand',
        kinstructions.VRedOp.OR: 'vredor',
        kinstructions.VRedOp.XOR: 'vredxor',
        kinstructions.VRedOp.MINU: 'vredminu',
        kinstructions.VRedOp.MIN: 'vredmin',
        kinstructions.VRedOp.MAXU: 'vredmaxu',
        kinstructions.VRedOp.MAX: 'vredmax',
        kinstructions.VRedOp.FSUM: 'vfredusum',
        kinstructions.VRedOp.FMIN: 'vfredmin',
        kinstructions.VRedOp.FMAX: 'vfredmax',
        kinstructions.VRedOp.WSUMU: 'vwredsumu',
        kinstructions.VRedOp.WSUM: 'vwredsum',
        kinstructions.VRedOp.FWSUM: 'vfwredusum',
    }

    _WIDENING = {
        kinstructions.VRedOp.WSUMU, kinstructions.VRedOp.WSUM,
        kinstructions.VRedOp.FWSUM,
    }

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        mnemonic = self._MNEMONIC[self.op]
        return f'{mnemonic}.vs\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        if s.vstart != 0:
            raise ValueError(f'{self._MNEMONIC[self.op]}.vs requires vstart == 0')

        if s.vl == 0:
            s.pc += 4
            return

        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        widening = self.op in self._WIDENING

        if widening:
            src_ew = element_width
            accum_ew = element_width * 2
        else:
            src_ew = element_width
            accum_ew = element_width

        mask_reg = 0 if not self.vm else None

        await s.await_vreg_write_pending(self.vs2, s.emul_for_eew(src_ew))
        await s.ensure_vrf_ordering(self.vs2, src_ew, span_id)
        assert s.vrf_ordering[self.vs1].ew == accum_ew  # vs1 is scalar, only element 0

        word_order = s.word_order
        await s.await_vreg_write_pending(self.vd, s.emul_for_eew(accum_ew))
        s.set_vrf_ordering(self.vd, accum_ew)
        if mask_reg is not None:
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)

        vlmul = (s.vtype >> 0) & 0x7
        if vlmul < 4:
            lmul = 1 << vlmul
        else:
            lmul = 1
        elements_in_vline = s.params.vline_bytes * 8 // src_ew
        vlmax = elements_in_vline * lmul
        assert s.vl <= vlmax, (
            f'{self._MNEMONIC[self.op]}.vs: vl={s.vl} exceeds vlmax={vlmax} '
            f'(ew={src_ew}, lmul={lmul}, elements_in_vline={elements_in_vline})')

        await s.handle_vreduction_instr(
            op=self.op,
            dst=self.vd,
            src_vector=self.vs2,
            src_scalar_reg=self.vs1,
            mask_reg=mask_reg,
            n_elements=s.vl,
            src_ew=src_ew,
            accum_ew=accum_ew,
            word_order=word_order,
            vlmax=vlmax,
            parent_span_id=span_id,
        )
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VArithVv:
    """Generic vector-vector arithmetic instruction.

    Used for vmul.vv, vmacc.vv, etc.
    """
    vd: int
    vs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        _ACCUM_OPS = kinstructions.ACCUM_OPS
        # Accumulator ops use vs1,vs2 order; others use vs2,vs1 order
        if self.op in _ACCUM_OPS:
            return f'v{self.op.value}.vv\tv{self.vd},v{self.vs1},v{self.vs2}{vm_str}'
        else:
            return f'v{self.op.value}.vv\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        _ACCUM_OPS = kinstructions.ACCUM_OPS
        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vs1, n_vlines)
        await s.ensure_vrf_ordering(self.vs1, element_width, span_id)
        await s.await_vreg_write_pending(self.vs2, n_vlines)
        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        if self.op in _ACCUM_OPS:
            await s.ensure_vrf_ordering(self.vd, element_width, span_id)
        s.set_vrf_ordering(self.vd, element_width)
        if mask_reg is not None:
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VArithVvOp(
            op=self.op,
            dst=self.vd,
            src1=self.vs1,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VArithVvFloat:
    """Floating-point vector-vector arithmetic instruction.

    Used for vfadd.vv, vfsub.vv, vfmul.vv, vfmacc.vv, etc.
    """
    vd: int
    vs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp

    _ACCUM_OPS = kinstructions.ACCUM_OPS

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'v{self.op.value}.vv\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vs1, n_vlines)
        await s.ensure_vrf_ordering(self.vs1, element_width, span_id)
        await s.await_vreg_write_pending(self.vs2, n_vlines)
        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        if self.op in self._ACCUM_OPS:
            await s.ensure_vrf_ordering(self.vd, element_width, span_id)
        s.set_vrf_ordering(self.vd, element_width)
        if mask_reg is not None:
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VArithVvOp(
            op=self.op,
            dst=self.vd,
            src1=self.vs1,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VArithVx:
    """Generic vector-scalar arithmetic instruction.

    Used for vmul.vx, vmacc.vx, etc.
    """
    vd: int
    rs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp

    _ACCUM_OPS = kinstructions.ACCUM_OPS

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        if self.op in self._ACCUM_OPS:
            return f'v{self.op.value}.vx\tv{self.vd},{reg_name(self.rs1)},v{self.vs2}{vm_str}'
        else:
            # vadd.vx, vmul.vx, etc: vd, vs2, rs1
            return f'v{self.op.value}.vx\tv{self.vd},v{self.vs2},{reg_name(self.rs1)}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vs2, n_vlines)
        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        if self.op in self._ACCUM_OPS:
            await s.ensure_vrf_ordering(self.vd, element_width, span_id)

        rs1_bytes = s.scalar.read_reg(self.rs1)

        s.set_vrf_ordering(self.vd, element_width)
        if mask_reg is not None:
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VArithVxOp(
            op=self.op,
            dst=self.vd,
            scalar_bytes=rs1_bytes,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VArithVi:
    """Generic vector-immediate arithmetic instruction.

    Used for vadd.vi, vand.vi, vor.vi, vxor.vi, vsll.vi, vsrl.vi, vsra.vi.
    """
    vd: int
    vs2: int
    simm5: int
    vm: int
    op: kinstructions.VArithOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'v{self.op.value}.vi\tv{self.vd},v{self.vs2},{self.simm5}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vs2, n_vlines)
        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)

        # Sign-extend the 5-bit immediate
        imm_val = self.simm5 if self.simm5 < 16 else self.simm5 - 32
        # Convert to bytes (using word_bytes to match scalar register size)
        imm_bytes = imm_val.to_bytes(s.params.word_bytes, byteorder='little', signed=True)

        await s.await_vreg_write_pending(self.vd, n_vlines)
        s.set_vrf_ordering(self.vd, element_width)
        if mask_reg is not None:
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VArithVxOp(
            op=self.op,
            dst=self.vd,
            scalar_bytes=imm_bytes,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VIndexedLoad:
    """Vector Load Indexed (vluxei/vloxei).

    Indexed (gather) load of elements from memory into a vector register.
    Element i is loaded from address (rs1 + vs2[i]).

    The index width (8/16/32/64) is encoded in the instruction.
    The data width comes from SEW in vtype.

    Reference: riscv-isa-manual/src/v-st-ext.adoc lines 1651-1679
    """
    vd: int
    rs1: int
    vs2: int
    vm: int
    index_width: int
    ordered: bool

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        op = 'vloxei' if self.ordered else 'vluxei'
        return f'{op}{self.index_width}.v\tv{self.vd},({reg_name(self.rs1)}),v{self.vs2}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        base_addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        mask_reg = None if self.vm else 0
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        vsew = (s.vtype >> 3) & 0x7
        data_ew = 8 << vsew

        # RVV permits vd==vs2 overlap for vluxei/vloxei when the dst EEW
        # equals the index EEW (per the §5.2 overlap rule). The kamlet
        # can't execute the gather with dst and index aliased to a single
        # preg, so copy vs2 into a scratch arch first.
        scratch_regs: list[int] | None = None
        index_reg = self.vs2
        if self.vd == self.vs2:
            scratch_regs = await _copy_vreg_to_scratch(
                s, self.vs2, self.index_width, s.vl, span_id)
            index_reg = scratch_regs[0]

        if self.ordered:
            result = await s.vload_indexed_ordered(
                self.vd, base_addr, index_reg, self.index_width, data_ew,
                s.vl, mask_reg, s.vstart, parent_span_id=span_id
            )
        else:
            result = await s.vload_indexed_unordered(
                self.vd, base_addr, index_reg, self.index_width, data_ew,
                s.vl, mask_reg, s.vstart, parent_span_id=span_id
            )

        if scratch_regs is not None:
            await s.free_temp_regs(scratch_regs, span_id)

        if s.maybe_trap_vector(result, is_store=False, fault_addr_fallback=base_addr):
            s.monitor.finalize_children(span_id)
            return
        s.vstart = 0
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VIndexedStore:
    """Vector Store Indexed (vsuxei/vsoxei).

    Indexed (scatter) store of elements from vector register to memory.
    Element i is stored to address (rs1 + vs2[i]).

    The index width (8/16/32/64) is encoded in the instruction.
    The data width comes from SEW in vtype.

    Reference: riscv-isa-manual/src/v-st-ext.adoc lines 1651-1679
    """
    vs3: int
    rs1: int
    vs2: int
    vm: int
    index_width: int
    ordered: bool

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        op = 'vsoxei' if self.ordered else 'vsuxei'
        return f'{op}{self.index_width}.v\tv{self.vs3},({reg_name(self.rs1)}),v{self.vs2}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        base_addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        mask_reg = None if self.vm else 0
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )
        vsew = (s.vtype >> 3) & 0x7
        data_ew = 8 << vsew
        if self.ordered:
            result = await s.vstore_indexed_ordered(
                self.vs3, base_addr, self.vs2, self.index_width, data_ew,
                s.vl, mask_reg, s.vstart, parent_span_id=span_id
            )
        else:
            result = await s.vstore_indexed_unordered(
                self.vs3, base_addr, self.vs2, self.index_width, data_ew,
                s.vl, mask_reg, s.vstart, parent_span_id=span_id
            )
        if s.maybe_trap_vector(result, is_store=True, fault_addr_fallback=base_addr):
            s.monitor.finalize_children(span_id)
            return
        s.vstart = 0
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class Vid:
    """VID.V - Vector Element Index.

    vd[i] = i (writes element index to each active element)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vid.v\tv{self.vd}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        await s.await_vreg_write_pending(self.vd, s.emul_for_eew(element_width))
        s.set_vrf_ordering(self.vd, element_width)

        mask_reg = None if self.vm else 0

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VidOp(
            dst=self.vd,
            n_elements=s.vl,
            element_width=element_width,
            word_order=s.word_order,
            mask_reg=mask_reg,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VUnary:
    """Unary vector operation with potentially different src/dst element widths.

    Used for vsext.vfN, vzext.vfN, vmv.v.v, and other unary operations.

    Width modes (controlled by `widening` and `narrowing`):
    - widening=True:  dst_ew = SEW, src_ew = SEW / factor (vzext, vsext)
    - narrowing=True: dst_ew = SEW, src_ew = SEW * factor
    - both False:     dst_ew = SEW / factor, src_ew = SEW
    """
    vd: int
    vs2: int
    vm: int
    op: kinstructions.VUnaryOp
    factor: int
    widening: bool
    mnemonic: str
    narrowing: bool = False

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'{self.mnemonic}\tv{self.vd},v{self.vs2}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        sew = 8 << vsew
        if self.narrowing:
            dst_ew = sew
            src_ew = sew * self.factor
        elif self.widening:
            dst_ew = sew
            src_ew = sew // self.factor
        else:
            src_ew = sew
            dst_ew = sew // self.factor
        assert src_ew >= 8 and dst_ew >= 8

        word_order = s.word_order
        mask_reg = None if self.vm else 0

        await s.await_vreg_write_pending(self.vd, s.emul_for_eew(dst_ew))
        s.set_vrf_ordering(self.vd, dst_ew)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VUnaryOvOp(
            op=self.op,
            dst=self.vd,
            src=self.vs2,
            n_elements=s.vl,
            dst_ew=dst_ew,
            src_ew=src_ew,
            word_order=word_order,
            mask_reg=mask_reg,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


class OvShape(Enum):
    """Width relationship for the Ov (width-asymmetric) arithmetic classes.

    BASE   — widening with both srcs at SEW (vw{add,sub,mul,mac}.vv/.vx,
             vfw*.vv/.vf): dst_ew = 2*SEW.
    WIDE   — widening with src2 already at 2*SEW (vw{add,sub}.wv/.wx,
             vfw{add,sub}.wv/.wf): dst_ew = 2*SEW.
    NARROW — narrowing with src2 at 2*SEW and dst at SEW (vnsrl, vnsra).
    """
    BASE = 'base'
    WIDE = 'wide'
    NARROW = 'narrow'


def _ov_widths(shape: OvShape, sew: int) -> tuple[int, int, int]:
    """Return (src1_ew, src2_ew, dst_ew) for the requested Ov shape."""
    if shape is OvShape.BASE:
        return sew, sew, sew * 2
    if shape is OvShape.WIDE:
        return sew, sew * 2, sew * 2
    if shape is OvShape.NARROW:
        return sew, sew * 2, sew
    raise ValueError(f"unknown Ov shape: {shape!r}")


@dataclass
class VArithVvOv:
    """Width-asymmetric binary vector-vector arithmetic.

    Used for the widening (vw{add,sub,mul,mac}{u}.vv/.wv, vfw*.vv/.wv) and
    narrowing-shift (vnsrl.wv, vnsra.wv) families. ``shape`` selects the
    width relationship between the operands; per-source signedness controls
    unpack format and the destination signedness convention.
    """
    vd: int
    vs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp
    shape: OvShape
    src1_signed: bool
    src2_signed: bool
    mnemonic: str

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'{self.mnemonic}\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        sew = 8 << vsew
        src1_ew, src2_ew, dst_ew = _ov_widths(self.shape, sew)

        mask_reg = None if self.vm else 0
        word_order = s.word_order

        await s.await_vreg_write_pending(self.vs1, s.emul_for_eew(src1_ew))
        await s.ensure_vrf_ordering(self.vs1, src1_ew, span_id)
        await s.await_vreg_write_pending(self.vs2, s.emul_for_eew(src2_ew))
        await s.ensure_vrf_ordering(self.vs2, src2_ew, span_id)
        await s.await_vreg_write_pending(self.vd, s.emul_for_eew(dst_ew))
        if self.op in kinstructions.ACCUM_OPS:
            await s.ensure_vrf_ordering(self.vd, dst_ew, span_id)
        s.set_vrf_ordering(self.vd, dst_ew)
        if mask_reg is not None:
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VArithVvOvOp(
            op=self.op,
            dst=self.vd,
            src1=self.vs1,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            src1_ew=src1_ew,
            src2_ew=src2_ew,
            dst_ew=dst_ew,
            src1_signed=self.src1_signed,
            src2_signed=self.src2_signed,
            word_order=word_order,
            instr_ident=instr_ident,
            is_float=self.op in kinstructions.FLOAT_OPS,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VArithVxOv:
    """Width-asymmetric binary vector-scalar arithmetic.

    Covers .vx/.wx (rs1 holds the scalar) and .wi (5-bit immediate) forms of
    the widening / narrowing arithmetic family. When ``is_imm`` is True,
    ``rs1`` carries the 5-bit immediate value and is sign- or zero-extended
    based on ``scalar_signed``.
    """
    vd: int
    rs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp
    shape: OvShape
    scalar_signed: bool
    src2_signed: bool
    mnemonic: str
    is_imm: bool = False

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        if self.is_imm:
            return f'{self.mnemonic}\tv{self.vd},v{self.vs2},0x{self.rs1:x}{vm_str}'
        return f'{self.mnemonic}\tv{self.vd},v{self.vs2},{reg_name(self.rs1)}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        sew = 8 << vsew
        src1_ew, src2_ew, dst_ew = _ov_widths(self.shape, sew)
        # Scalar uses src1 width.
        scalar_ew = src1_ew

        mask_reg = None if self.vm else 0
        word_order = s.word_order

        await s.await_vreg_write_pending(self.vs2, s.emul_for_eew(src2_ew))
        await s.ensure_vrf_ordering(self.vs2, src2_ew, span_id)
        await s.await_vreg_write_pending(self.vd, s.emul_for_eew(dst_ew))
        if self.op in kinstructions.ACCUM_OPS:
            await s.ensure_vrf_ordering(self.vd, dst_ew, span_id)
        if mask_reg is not None:
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)

        if self.is_imm:
            if self.scalar_signed:
                imm_val = self.rs1 if self.rs1 < 16 else self.rs1 - 32
                scalar_bytes = imm_val.to_bytes(
                    s.params.word_bytes, byteorder='little', signed=True)
            else:
                scalar_bytes = self.rs1.to_bytes(
                    s.params.word_bytes, byteorder='little', signed=False)
        else:
            await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
            scalar_bytes = s.scalar.read_reg(self.rs1)

        s.set_vrf_ordering(self.vd, dst_ew)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VArithVxOvOp(
            op=self.op,
            dst=self.vd,
            scalar_bytes=scalar_bytes,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            scalar_ew=scalar_ew,
            src2_ew=src2_ew,
            dst_ew=dst_ew,
            scalar_signed=self.scalar_signed,
            src2_signed=self.src2_signed,
            word_order=word_order,
            instr_ident=instr_ident,
            is_float=self.op in kinstructions.FLOAT_OPS,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


def _compute_vlmax(s: 'Oamlet', element_width: int) -> int:
    vlmul = (s.vtype >> 0) & 0x7
    if vlmul < 4:
        lmul = 1 << vlmul
    else:
        # Fractional LMUL is treated as 1 for VLMAX.
        lmul = 1
    elements_in_vline = s.params.vline_bytes * 8 // element_width
    return elements_in_vline * lmul


async def _copy_vreg_to_scratch(s: 'Oamlet', src_reg: int, ew: int,
                                n_elements: int, span_id: int) -> list[int]:
    """Copy src_reg into a fresh scratch arch group and return the group.

    Used to break a dst/src aliasing that RVV permits but that our
    micro-arch's non-local-access kinstrs (gathers, slides, indexed
    loads, ...) cannot safely execute — a single kinstr can't read from
    and write to the same preg because element-level read/write order
    isn't serialized. Caller is responsible for emitting
    `free_temp_regs(scratch_regs, span_id)` after the aliased-source op.
    """
    vline_bits = s.params.vline_bytes * 8
    n_vlines = (ew * n_elements + vline_bits - 1) // vline_bits
    scratch_regs = s.alloc_temp_reg_group(n_vlines)
    copy_ident = await s.get_instr_ident()
    await s.add_to_instruction_buffer(
        kinstructions.VUnaryOvOp(
            op=kinstructions.VUnaryOp.COPY,
            dst=scratch_regs[0],
            src=src_reg,
            n_elements=n_elements,
            dst_ew=ew,
            src_ew=ew,
            word_order=s.word_order,
            mask_reg=None,
            instr_ident=copy_ident,
        ), span_id)
    return scratch_regs


async def _dispatch_vslide(s: 'Oamlet', vd: int, vs2: int, offset: int,
                           direction: SlideDirection, vm: int, span_id: int) -> None:
    vsew = (s.vtype >> 3) & 0x7
    element_width = 8 << vsew
    word_order = s.word_order

    n_vlines = s.emul_for_eew(element_width)
    await s.await_vreg_write_pending(vs2, n_vlines)
    await s.ensure_vrf_ordering(vs2, element_width, span_id)
    await s.await_vreg_write_pending(vd, n_vlines)
    s.set_vrf_ordering(vd, element_width)

    mask_reg = None if vm else 0
    if mask_reg is not None:
        await s.ensure_vrf_ordering(mask_reg, 1, span_id)
    vlmax = _compute_vlmax(s, element_width)

    # Per RVV: vstart >= vl -> no-op.
    if s.vstart >= s.vl:
        return

    if direction == SlideDirection.UP:
        start_index = max(s.vstart, offset)
    else:
        start_index = s.vstart

    # Nothing to write (e.g. offset >= vl for slideup).
    if start_index >= s.vl:
        return

    # RVV allows vd == vs2 for vslidedown / vslide1down (only vslideup
    # and vslide1up forbid overlap). The kamlet-level RegSlide requires
    # distinct dst/vs2 pregs, so break the alias by copying vs2 into a
    # scratch arch first.
    scratch_regs = None
    if direction == SlideDirection.DOWN and vd == vs2:
        scratch_regs = await _copy_vreg_to_scratch(
            s, vs2, element_width, vlmax, span_id)
        vs2 = scratch_regs[0]

    await s.vslide(
        vd=vd,
        vs2=vs2,
        offset=offset,
        direction=direction,
        start_index=start_index,
        n_elements=s.vl,
        data_ew=element_width,
        word_order=word_order,
        vlmax=vlmax,
        mask_reg=mask_reg,
        parent_span_id=span_id,
    )

    if scratch_regs is not None:
        await s.free_temp_regs(scratch_regs, span_id)


@dataclass
class Vslide:
    """VSLIDEUP / VSLIDEDOWN (.VX / .VI) - Vector Slide by scalar/immediate offset.

    up:   vd[i+OFFSET] = vs2[i]   (i.e. vd[i] = vs2[i-OFFSET])  for i in [OFFSET, vl)
          Destination elements below OFFSET are unchanged.
          vd must not overlap vs2.
    down: vd[i] = vs2[i+OFFSET]   for i in [vstart, vl)
          vd[i] = 0               when i+OFFSET >= VLMAX
    OFFSET is zero-extended (unsigned).

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs2: int
    offset_src: int    # rs1 (for .vx) or uimm5 (for .vi)
    is_imm: bool
    vm: int
    direction: SlideDirection

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        mnemonic = ('vslideup' if self.direction == SlideDirection.UP
                    else 'vslidedown')
        suffix = 'vi' if self.is_imm else 'vx'
        offset_str = (str(self.offset_src) if self.is_imm
                      else reg_name(self.offset_src))
        return f'{mnemonic}.{suffix}\tv{self.vd},v{self.vs2},{offset_str}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        if self.is_imm:
            offset = self.offset_src & 0x1f
        else:
            await s.scalar.wait_all_regs_ready(None, None, [self.offset_src], [])
            rs1_bytes = s.scalar.read_reg(self.offset_src)
            offset = int.from_bytes(rs1_bytes, byteorder='little', signed=False)

        await _dispatch_vslide(s, self.vd, self.vs2, offset,
                               self.direction, self.vm, span_id)
        s.monitor.finalize_children(span_id)
        s.pc += 4


async def _inject_scalar_element(s: 'Oamlet', vd: int, element_index: int,
                                  element_width: int, scalar_val: int,
                                  span_id: int,
                                  mask_reg: int | None = None) -> None:
    """Write `scalar_val` into a single element of `vd` via WriteRegElement.

    vd's vrf_ordering must already be set. `element_index` is the logical RVV
    element index (may span multiple vlines when LMUL>1); this helper resolves
    it to (vline-offset, within-vline element, kamlet) before dispatching.

    When mask_reg is not None, the kamlet checks v0's bit for this element
    and suppresses the write if it is 0.
    """
    ordering = s.vrf_ordering[vd]
    elements_in_vline = s.params.vline_bytes * 8 // element_width
    v_offset = element_index // elements_in_vline
    ei_in_vline = element_index % elements_in_vline
    vw_index = ei_in_vline % s.params.j_in_l
    k_index, _ = addresses.vw_index_to_k_indices(
        s.params, ordering.word_order, vw_index)

    # Mask bit for the full logical element index lives at bit
    # (element_index // j_in_l) of the same jamlet's mask word.
    mask_index = element_index // s.params.j_in_l

    instr_ident = await s.get_instr_ident()
    kinstr = kinstructions.WriteRegElement(
        dst=vd + v_offset,
        element_index=ei_in_vline,
        element_width=element_width,
        ordering=ordering,
        value=scalar_val,
        instr_ident=instr_ident,
        mask_reg=mask_reg,
        mask_index=mask_index,
    )
    await s.add_to_instruction_buffer(kinstr, span_id, k_index)


@dataclass
class Vslide1:
    """VSLIDE1UP / VSLIDE1DOWN (.VX or .VF) - Vector Slide-1 with scalar inject.

    up:   vd[0]    = scalar (when vstart == 0); vd[i+1] = vs2[i] for the rest.
    down: vd[vl-1] = scalar (when vl > vstart); vd[i]   = vs2[i+1] for the rest.

    is_float=False: scalar = x[rs1] (integer register, .vx form).
    is_float=True:  scalar = f[rs1] (FP register, .vf form).

    For up, vd must not overlap vs2.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    (vslide1up.vx, vslide1down.vx, vfslide1up.vf, vfslide1down.vf)
    """
    vd: int
    vs2: int
    rs1: int
    vm: int
    direction: SlideDirection
    is_float: bool = False

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        if self.is_float:
            mnemonic = ('vfslide1up.vf' if self.direction == SlideDirection.UP
                        else 'vfslide1down.vf')
            scalar_name = freg_name(self.rs1)
        else:
            mnemonic = ('vslide1up.vx' if self.direction == SlideDirection.UP
                        else 'vslide1down.vx')
            scalar_name = reg_name(self.rs1)
        return f'{mnemonic}\tv{self.vd},v{self.vs2},{scalar_name}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        if self.is_float:
            await s.scalar.wait_all_regs_ready(None, None, [], [self.rs1])
            rs1_bytes = s.scalar.read_freg(self.rs1)
        else:
            await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
            rs1_bytes = s.scalar.read_reg(self.rs1)

        await _dispatch_vslide(s, self.vd, self.vs2, 1,
                               self.direction, self.vm, span_id)

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        # Per RVV: XLEN > SEW => use LSBs; XLEN < SEW => sign-extend.
        # Truncate rs1 to SEW bytes before sign-extending into a Python int.
        eb = element_width // 8
        scalar_val = int.from_bytes(
            rs1_bytes[:eb], byteorder='little', signed=True)

        # The boundary-lane inject is also gated by v0 when masked; the kamlet
        # tests the bit in WriteRegElement and drops the write if it's 0.
        inject_mask_reg = None if self.vm else 0

        # Boundary lane for the scalar inject:
        # - up: index 0, written only when vstart == 0 and vl >= 1.
        # - down: index vl-1, written only when vl > vstart.
        if self.direction == SlideDirection.UP:
            if s.vstart == 0 and s.vl >= 1:
                await _inject_scalar_element(
                    s, self.vd, 0, element_width, scalar_val, span_id,
                    mask_reg=inject_mask_reg)
        else:
            if s.vl > s.vstart and s.vl >= 1:
                await _inject_scalar_element(
                    s, self.vd, s.vl - 1, element_width, scalar_val, span_id,
                    mask_reg=inject_mask_reg)

        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class Vrgather:
    """VRGATHER.VV / VRGATHEREI16.VV - Vector Register Gather.

    vd[i] = (vs1[i] >= VLMAX) ? 0 : vs2[vs1[i]]

    Gathers elements from vs2 using indices in vs1.

    index_ew_fixed: None for vrgather.vv (index EEW = SEW); 16 for
    vrgatherei16.vv (index EEW = 16 regardless of SEW).

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs2: int
    vs1: int
    vm: int
    index_ew_fixed: int | None = None

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        mnemonic = 'vrgatherei16.vv' if self.index_ew_fixed == 16 else 'vrgather.vv'
        return f'{mnemonic}\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        data_ew = 8 << vsew
        index_ew = data_ew if self.index_ew_fixed is None else self.index_ew_fixed
        word_order = s.word_order

        index_n_vlines = s.emul_for_eew(index_ew)
        await s.await_vreg_write_pending(self.vs1, index_n_vlines)
        await s.ensure_vrf_ordering(self.vs1, index_ew, span_id)

        data_n_vlines = s.emul_for_eew(data_ew)
        await s.await_vreg_write_pending(self.vs2, data_n_vlines)
        await s.ensure_vrf_ordering(self.vs2, data_ew, span_id)

        await s.await_vreg_write_pending(self.vd, data_n_vlines)
        s.set_vrf_ordering(self.vd, data_ew)

        mask_reg = None if self.vm else 0
        if mask_reg is not None:
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)
        vlmax = _compute_vlmax(s, data_ew)

        await s.vrgather(
            vd=self.vd,
            vs2=self.vs2,
            vs1=self.vs1,
            start_index=s.vstart,
            n_elements=s.vl,
            index_ew=index_ew,
            data_ew=data_ew,
            word_order=word_order,
            vlmax=vlmax,
            mask_reg=mask_reg,
            parent_span_id=span_id,
        )
        s.monitor.finalize_children(span_id)
        s.pc += 4


@dataclass
class VrgatherVxVi:
    """VRGATHER.VX / .VI - Vector Register Gather with scalar/immediate index.

    vd[i] = (idx >= VLMAX) ? 0 : vs2[idx]
    where idx = x[rs1] (zero-extended) for .vx, or uimm5 for .vi.

    Decomposed at the lamlet. The rare ``idx >= vlmax`` case emits a
    VBroadcastOp of 0 directly. Otherwise the lamlet dispatches a ReadRegWord
    for vs2[idx] and immediately returns (pc += 4). The destination ``vd`` is
    marked write-pending so any later instruction touching vd blocks until
    the response arrives, at which point LamletWaitingVrgatherBroadcast
    appends a VBroadcastOp and clears the pending counter.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs2: int
    index_src: int    # rs1 (for .vx) or uimm5 (for .vi)
    is_imm: bool
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        if self.is_imm:
            return f'vrgather.vi\tv{self.vd},v{self.vs2},{self.index_src}{vm_str}'
        return f'vrgather.vx\tv{self.vd},v{self.vs2},{reg_name(self.index_src)}{vm_str}'

    async def update_state(self, s: 'Oamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = s.word_order

        n_vlines = s.emul_for_eew(element_width)
        await s.await_vreg_write_pending(self.vs2, n_vlines)
        await s.ensure_vrf_ordering(self.vs2, element_width, span_id)
        await s.await_vreg_write_pending(self.vd, n_vlines)
        s.set_vrf_ordering(self.vd, element_width)

        mask_reg = None if self.vm else 0
        if mask_reg is not None:
            await s.ensure_vrf_ordering(mask_reg, 1, span_id)
        vlmax = _compute_vlmax(s, element_width)

        # Per RVV: vstart >= vl -> no-op.
        if s.vstart >= s.vl:
            s.monitor.finalize_children(span_id)
            s.pc += 4
            return

        if self.is_imm:
            idx = self.index_src & 0x1f
        else:
            await s.scalar.wait_all_regs_ready(None, None, [self.index_src], [])
            rs1_bytes = s.scalar.read_reg(self.index_src)
            idx = int.from_bytes(rs1_bytes, byteorder='little', signed=False)

        if idx >= vlmax:
            # Out-of-range: broadcast 0 directly. No remote fetch needed.
            broadcast_ident = await ident_query.get_instr_ident(s)
            kinstr = kinstructions.VBroadcastOp(
                dst=self.vd,
                scalar=0,
                n_elements=s.vl,
                element_width=element_width,
                word_order=word_order,
                instr_ident=broadcast_ident,
                mask_reg=mask_reg,
            )
            await s.add_to_instruction_buffer(kinstr, span_id)
            s.monitor.finalize_children(span_id)
            s.pc += 4
            return

        eb = element_width // 8
        elements_in_vline = s.params.vline_bytes * 8 // element_width
        src_v = idx // elements_in_vline
        src_ve = idx % elements_in_vline
        src_vw = src_ve % s.params.j_in_l
        src_we = src_ve // s.params.j_in_l
        src_k, src_j_in_k = addresses.vw_index_to_k_indices(
            s.params, word_order, src_vw)
        src_byte_offset = src_we * eb

        s.mark_vreg_write_pending(self.vd, element_width)

        instr_ident = await ident_query.get_instr_ident(s)
        witem = LamletWaitingVrgatherBroadcast(
            instr_ident=instr_ident,
            vd=self.vd,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            mask_reg=mask_reg,
            src_byte_offset=src_byte_offset,
            span_id=span_id,
        )
        await s.add_witem(witem)
        read_kinstr = kinstructions.ReadRegWord(
            src=self.vs2 + src_v,
            j_in_k_index=src_j_in_k,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(read_kinstr, span_id, src_k)
        s.pc += 4
