"""Vector extension instructions.

Reference: riscv-isa-manual/src/v-st-ext.adoc
"""

import logging
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zamlet.lamlet.lamlet import Lamlet

from zamlet.kamlet import kinstructions
from zamlet import addresses
from zamlet.addresses import Ordering, WordOrder
from zamlet.register_names import reg_name, freg_name
from zamlet.monitor import CompletionType, SpanType

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

        lmul_strs = ['m1', 'm2', 'm4', 'm8', 'mf8', 'mf4', 'mf2', 'reserved']
        sew_strs = ['e8', 'e16', 'e32', 'e64', 'e128', 'e256', 'e512', 'e1024']

        lmul_str = lmul_strs[vlmul]
        sew_str = sew_strs[vsew]
        ta_str = 'ta' if vta else 'tu'
        ma_str = 'ma' if vma else 'mu'

        return f'vsetvli\t{reg_name(self.rd)},{reg_name(self.rs1)},{sew_str},{lmul_str},{ta_str},{ma_str}'

    async def update_state(self, s: 'Lamlet'):
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

        # When both rd and rs1 are x0, keep existing vl (only update vtype).
        # Per RISC-V V spec section "AVL encoding":
        # "When rs1=x0 and rd=x0, the instructions operate as if the current
        # vector length in vl is used as the AVL"
        # Reference: riscv-isa-manual/src/v-st-ext.adoc
        if self.rd == 0 and self.rs1 == 0:
            pass  # vl stays unchanged
        elif avl <= vlmax:
            s.vl = avl
        else:
            s.vl = vlmax

        vl_bytes = s.vl.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, vl_bytes)
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

        lmul_strs = ['m1', 'm2', 'm4', 'm8', 'mf8', 'mf4', 'mf2', 'reserved']
        sew_strs = ['e8', 'e16', 'e32', 'e64', 'e128', 'e256', 'e512', 'e1024']

        lmul_str = lmul_strs[vlmul]
        sew_str = sew_strs[vsew]
        ta_str = 'ta' if vta else 'tu'
        ma_str = 'ma' if vma else 'mu'

        return f'vsetivli\t{reg_name(self.rd)},{self.uimm},{sew_str},{lmul_str},{ta_str},{ma_str}'

    async def update_state(self, s: 'Lamlet'):
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
        s.scalar.write_reg(self.rd, vl_bytes)
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

    async def update_state(self, s: 'Lamlet'):
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
        await s.vload(self.vd, addr, ordering, s.vl, mask_reg, s.vstart, parent_span_id=span_id)
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

    async def update_state(self, s: 'Lamlet'):
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
        await s.vload(self.vd, addr, ordering, n_elements, None, 0, parent_span_id=span_id)
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

    async def update_state(self, s: 'Lamlet'):
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
        await s.vstore(self.vs3, addr, ordering, s.vl, mask_reg, s.vstart, parent_span_id=span_id)
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

    async def update_state(self, s: 'Lamlet'):
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
        await s.vstore(self.vs3, addr, ordering, n_elements, None, 0, parent_span_id=span_id)
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

    async def update_state(self, s: 'Lamlet'):
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
        await s.vload(self.vd, addr, ordering, s.vl, mask_reg, s.vstart, parent_span_id=span_id,
                      stride_bytes=stride)
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

    async def update_state(self, s: 'Lamlet'):
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
        await s.vstore(self.vs3, addr, ordering, s.vl, mask_reg, s.vstart, parent_span_id=span_id,
                       stride_bytes=stride)
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

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
        logger.debug(f'{s.clock.cycle}: VLSEG{self.nf}E{self.element_width}.V: '
                    f'vd=v{self.vd}, addr=0x{addr:x}, vl={s.vl}, nf={self.nf}, '
                    f'masked={not self.vm}, mask_reg={mask_reg}')
        ordering = addresses.Ordering(s.word_order, self.element_width)
        await s.vsegload(self.vd, addr, ordering, s.vl, mask_reg, s.vstart, self.nf)
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

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
        logger.debug(f'{s.clock.cycle}: VSSEG{self.nf}E{self.element_width}.V: '
                    f'vs3=v{self.vs3}, addr=0x{addr:x}, vl={s.vl}, nf={self.nf}, '
                    f'masked={not self.vm}, mask_reg={mask_reg}')
        ordering = addresses.Ordering(s.word_order, self.element_width)
        await s.vsegstore(self.vs3, addr, ordering, s.vl, mask_reg, s.vstart, self.nf)
        s.pc += 4
        logger.debug(f'Stored segment from vs3=v{self.vs3} through v{self.vs3 + self.nf - 1}')


@dataclass
class VArithVxFloat:
    """Generic vector-scalar floating-point arithmetic instruction.

    Used for vfmacc.vf, etc.
    """
    vd: int
    rs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vf{self.op.value}.vf\tv{self.vd},{freg_name(self.rs1)},v{self.vs2}{vm_str}'

    async def update_state(self, s: 'Lamlet'):
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
        assert s.vrf_ordering[self.vd].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        scalar_bytes = s.scalar.read_freg(self.rs1)

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

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
class VmsleVi:
    """VMSLE.VI - Vector Mask Set Less Than or Equal Immediate.

    vd.mask[i] = (vs2[i] <= simm5) ? 1 : 0

    Note: vmslt.vi is a pseudoinstruction that maps to vmsle.vi with imm-1.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs2: int
    simm5: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vmsle.vi\tv{self.vd},v{self.vs2},{self.simm5}{vm_str}'

    async def update_state(self, s: 'Lamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        # Calculate number of source registers needed
        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_src_vline = vline_bytes * 8 // element_width
        n_src_vlines = (s.vl + elements_in_src_vline - 1) // elements_in_src_vline

        # Check all source registers in group have correct element width
        for i in range(n_src_vlines):
            assert s.vrf_ordering[self.vs2 + i].ew == element_width

        # Calculate number of destination mask registers needed
        elements_in_dst_vline = vline_bytes * 8  # 1 bit per element
        n_dst_vlines = (s.vl + elements_in_dst_vline - 1) // elements_in_dst_vline

        # Set ordering for destination mask register(s) - masks are 1-bit elements
        mask_ordering = Ordering(s.word_order, 1)
        for i in range(n_dst_vlines):
            s.vrf_ordering[self.vd + i] = mask_ordering

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VmsleViOp(
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
class VmnandMm:
    """VMNAND.MM - Vector Mask NAND.

    vd.mask[i] = !(vs2.mask[i] && vs1.mask[i])

    Pseudoinstruction vmnot.m vd, vs => vmnand.mm vd, vs, vs

    Note: Mask logical operations are always unmasked.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs2: int
    vs1: int

    def __str__(self):
        if self.vs2 == self.vs1:
            return f'vmnot.m\tv{self.vd},v{self.vs2}'
        return f'vmnand.mm\tv{self.vd},v{self.vs2},v{self.vs1}'

    async def update_state(self, s: 'Lamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        # Get ordering from source mask registers
        vs2_ordering = s.vrf_ordering[self.vs2]
        vs1_ordering = s.vrf_ordering[self.vs1]

        # Mask registers should have element width of 1
        assert vs2_ordering.ew == 1
        assert vs1_ordering.ew == 1

        # Set ordering for destination mask register to match source
        s.vrf_ordering[self.vd] = vs2_ordering

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VmnandMmOp(
            dst=self.vd,
            src1=self.vs2,
            src2=self.vs1,
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

    async def update_state(self, s: 'Lamlet'):
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

        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

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

    async def update_state(self, s: 'Lamlet'):
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

        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

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
class VmvVv:
    """VMV.V.V - Vector Move Vector Register.

    vd[i] = vs1[i] (copy vector register to all active elements)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs1: int

    def __str__(self):
        return f'vmv.v.v\tv{self.vd},v{self.vs1}'

    async def update_state(self, s: 'Lamlet'):
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

        assert s.vrf_ordering[self.vs1].ew == element_width

        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        instr_ident = await s.get_instr_ident()
        kinstr = kinstructions.VmvVvOp(
            dst=self.vd,
            src=self.vs1,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            instr_ident=instr_ident,
        )
        await s.add_to_instruction_buffer(kinstr, span_id)
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

    async def update_state(self, s: 'Lamlet'):
        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        assert s.vrf_ordering[self.vs2].ew == element_width

        # Read element 0 from the vector register
        value_future = await s.read_register_element(self.vs2, element_index=0, element_width=element_width)
        s.scalar.write_reg_future(self.rd, value_future)
        s.pc += 4


@dataclass
class VreductionVs:
    """Generic Vector Single-Width Integer Reduction.

    vd[0] = reduce_op(vs1[0], vs2[*])
    Reduces all active elements of vs2 with element 0 of vs1 using the specified operation.

    Used for vredsum.vs, vredmax.vs, vredmin.vs, etc.

    Reference: riscv-isa-manual/src/v-st-ext.adoc Section 15.3
    """
    vd: int
    vs2: int
    vs1: int
    vm: int
    op: kinstructions.VRedOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        op_name = f'vred{self.op.value}'
        return f'{op_name}.vs\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Lamlet'):
        if s.vstart != 0:
            raise ValueError(f'vred{self.op.value}.vs requires vstart == 0')

        if s.vl == 0:
            s.pc += 4
            return

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        if not self.vm:
            mask_reg = 0
        else:
            mask_reg = None

        assert s.vrf_ordering[self.vs2].ew == element_width
        assert s.vrf_ordering[self.vs1].ew == element_width

        word_order = s.word_order
        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        await s.handle_vreduction_vs_instr(
            op=self.op,
            dst=self.vd,
            src_vector=self.vs2,
            src_scalar_reg=self.vs1,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
        )
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
        # MACC uses vs1,vs2 order; MUL uses vs2,vs1 order
        if self.op == kinstructions.VArithOp.MACC:
            return f'v{self.op.value}.vv\tv{self.vd},v{self.vs1},v{self.vs2}{vm_str}'
        else:
            return f'v{self.op.value}.vv\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Lamlet'):
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

        if self.op == kinstructions.VArithOp.MACC and self.vd not in s.vrf_ordering:
            s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        assert s.vrf_ordering[self.vs1].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        if self.op != kinstructions.VArithOp.MACC:
            s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

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

    Used for vfadd.vv, vfsub.vv, vfmul.vv, etc.
    """
    vd: int
    vs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vf{self.op.value[1:]}.vv\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Lamlet'):
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

        assert s.vrf_ordering[self.vs1].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

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

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        if self.op == kinstructions.VArithOp.MACC:
            # vmacc.vx vd, rs1, vs2 (accumulator instructions have scalar first)
            return f'v{self.op.value}.vx\tv{self.vd},{reg_name(self.rs1)},v{self.vs2}{vm_str}'
        else:
            # vadd.vx, vmul.vx, etc: vd, vs2, rs1
            return f'v{self.op.value}.vx\tv{self.vd},v{self.vs2},{reg_name(self.rs1)}{vm_str}'

    async def update_state(self, s: 'Lamlet'):
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

        if self.op == kinstructions.VArithOp.MACC and self.vd not in s.vrf_ordering:
            s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        assert s.vrf_ordering[self.vs2].ew == element_width
        if self.op == kinstructions.VArithOp.MACC:
            assert s.vrf_ordering[self.vd].ew == element_width

        rs1_bytes = s.scalar.read_reg(self.rs1)

        if self.op != kinstructions.VArithOp.MACC:
            s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

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

    async def update_state(self, s: 'Lamlet'):
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

        assert s.vrf_ordering[self.vs2].ew == element_width

        # Sign-extend the 5-bit immediate
        imm_val = self.simm5 if self.simm5 < 16 else self.simm5 - 32
        # Convert to bytes (using word_bytes to match scalar register size)
        imm_bytes = imm_val.to_bytes(s.params.word_bytes, byteorder='little', signed=True)

        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

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

    async def update_state(self, s: 'Lamlet'):
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
            await s.vload_indexed_ordered(
                self.vd, base_addr, self.vs2, self.index_width, data_ew,
                s.vl, mask_reg, s.vstart, parent_span_id=span_id
            )
        else:
            await s.vload_indexed_unordered(
                self.vd, base_addr, self.vs2, self.index_width, data_ew,
                s.vl, mask_reg, s.vstart, parent_span_id=span_id
            )
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

    async def update_state(self, s: 'Lamlet'):
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
            await s.vstore_indexed_ordered(
                self.vs3, base_addr, self.vs2, self.index_width, data_ew,
                s.vl, mask_reg, s.vstart, parent_span_id=span_id
            )
        else:
            await s.vstore_indexed_unordered(
                self.vs3, base_addr, self.vs2, self.index_width, data_ew,
                s.vl, mask_reg, s.vstart, parent_span_id=span_id
            )
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

    async def update_state(self, s: 'Lamlet'):
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=str(self),
            pc=s.pc,
        )

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        s.vrf_ordering[self.vd] = addresses.Ordering(s.word_order, element_width)

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
class Vrgather:
    """VRGATHER.VV - Vector Register Gather.

    vd[i] = (vs1[i] >= VLMAX) ? 0 : vs2[vs1[i]]

    Gathers elements from vs2 using indices in vs1.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs2: int
    vs1: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vrgather.vv\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'Lamlet'):
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

        assert s.vrf_ordering[self.vs1].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        mask_reg = None if self.vm else 0

        # Compute VLMAX
        vlmul = (s.vtype >> 0) & 0x7
        if vlmul < 4:
            lmul = 1 << vlmul
        else:
            lmul = 1  # fractional LMUL treated as 1 for VLMAX
        elements_in_vline = s.params.vline_bytes * 8 // element_width
        vlmax = elements_in_vline * lmul

        # For vrgather.vv, both index and data use the same SEW
        # For vrgatherei16, index_ew would be 16
        await s.vrgather(
            vd=self.vd,
            vs2=self.vs2,
            vs1=self.vs1,
            start_index=s.vstart,
            n_elements=s.vl,
            index_ew=element_width,
            data_ew=element_width,
            word_order=word_order,
            vlmax=vlmax,
            mask_reg=mask_reg,
            parent_span_id=span_id,
        )
        s.monitor.finalize_children(span_id)
        s.pc += 4
