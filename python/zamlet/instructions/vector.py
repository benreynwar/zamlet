"""Vector extension instructions.

Reference: riscv-isa-manual/src/v-st-ext.adoc
"""

import logging
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zamlet.oamlet.oamlet import Oamlet

from zamlet.kamlet import kinstructions
from zamlet import addresses
from zamlet.addresses import Ordering, WordOrder
from zamlet.register_names import reg_name, freg_name
from zamlet.monitor import CompletionType, SpanType
from zamlet.lamlet.unordered import remap_reg_ew

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

    async def update_state(self, s: 'Oamlet'):
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

        lmul_strs = ['m1', 'm2', 'm4', 'm8', 'reserved', 'mf8', 'mf4', 'mf2']
        sew_strs = ['e8', 'e16', 'e32', 'e64', 'e128', 'e256', 'e512', 'e1024']

        lmul_str = lmul_strs[vlmul]
        sew_str = sew_strs[vsew]
        ta_str = 'ta' if vta else 'tu'
        ma_str = 'ma' if vma else 'mu'

        return f'vsetivli\t{reg_name(self.rd)},{self.uimm},{sew_str},{lmul_str},{ta_str},{ma_str}'

    async def update_state(self, s: 'Oamlet'):
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
        await s.vload(self.vd, addr, ordering, s.vl, mask_reg, s.vstart,
                       parent_span_id=span_id, emul=emul)
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
        await s.vload(self.vd, addr, ordering, n_elements, None, 0,
                       parent_span_id=span_id, emul=self.nreg)
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
        await s.vstore(
            self.vs3, addr, ordering, s.vl, mask_reg, s.vstart,
            parent_span_id=span_id, emul=emul)
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
        await s.vstore(self.vs3, addr, ordering, n_elements, None, 0,
                       parent_span_id=span_id, emul=self.nreg)
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
        await s.vload(self.vd, addr, ordering, s.vl, mask_reg, s.vstart,
                       parent_span_id=span_id, emul=emul, stride_bytes=stride)
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
        await s.vstore(self.vs3, addr, ordering, s.vl, mask_reg, s.vstart,
                       parent_span_id=span_id, emul=emul, stride_bytes=stride)
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

    async def update_state(self, s: 'Oamlet'):
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
        s.assert_vrf_ordering(self.vs2, element_width)
        if self.op in self._ACCUM_OPS:
            s.assert_vrf_ordering(self.vd, element_width)

        s.set_vrf_ordering(self.vd, element_width)

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

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_src_vline = vline_bytes * 8 // element_width
        n_src_vlines = (s.vl + elements_in_src_vline - 1) // elements_in_src_vline

        for i in range(n_src_vlines):
            assert s.vrf_ordering[self.vs2 + i].ew == element_width

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

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_src_vline = vline_bytes * 8 // element_width
        n_src_vlines = (s.vl + elements_in_src_vline - 1) // elements_in_src_vline

        for i in range(n_src_vlines):
            assert s.vrf_ordering[self.vs2 + i].ew == element_width
            assert s.vrf_ordering[self.vs1 + i].ew == element_width

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

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_src_vline = vline_bytes * 8 // element_width
        n_src_vlines = (s.vl + elements_in_src_vline - 1) // elements_in_src_vline

        for i in range(n_src_vlines):
            assert s.vrf_ordering[self.vs2 + i].ew == element_width

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

    async def update_state(self, s: 'Oamlet'):
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

        s.assert_vrf_ordering(self.vs2, element_width)
        s.set_vrf_ordering(self.vd, element_width)

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

        s.assert_vrf_ordering(self.vs2, element_width)
        s.assert_vrf_ordering(self.vs1, element_width)
        s.set_vrf_ordering(self.vd, element_width)

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

        # Step 2: copy vs1 to vd where v0 mask is set
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

        s.assert_vrf_ordering(self.vs2, element_width)
        s.set_vrf_ordering(self.vd, element_width)

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
class VmvXs:
    """VMV.X.S - Vector Move to Scalar Register.

    x[rd] = vs2[0] (extract element 0 from vector register)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    rd: int
    vs2: int

    def __str__(self):
        return f'vmv.x.s\t{reg_name(self.rd)},v{self.vs2}'

    async def update_state(self, s: 'Oamlet'):
        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        assert s.vrf_ordering[self.vs2].ew == element_width

        # Read element 0 from the vector register
        value_future = await s.read_register_element(self.vs2, element_index=0, element_width=element_width)
        s.scalar.write_reg_future(self.rd, value_future)
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

        if s.vrf_ordering[self.vd] is None:
            s.set_vrf_ordering(self.vd, element_width)
        elif s.vrf_ordering[self.vd].ew != element_width:
            # Register has data at a different ew. Remap in-place so the data layout
            # matches the current SEW before we write element 0.
            logger.warning(
                f'vmv.s.x v{self.vd}: ew mismatch, remapping from '
                f'{s.vrf_ordering[self.vd].ew} to {element_width}')
            dst_ordering = Ordering(s.word_order, element_width)
            await remap_reg_ew(
                s, [self.vd], [self.vd], dst_ordering, span_id)
            s.set_vrf_ordering(self.vd, element_width)

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

        s.assert_vrf_ordering(self.vs2, src_ew)
        assert s.vrf_ordering[self.vs1].ew == accum_ew  # vs1 is scalar, only element 0

        word_order = s.word_order
        s.set_vrf_ordering(self.vd, accum_ew)

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

        s.assert_vrf_ordering(self.vs1, element_width)
        s.assert_vrf_ordering(self.vs2, element_width)
        if self.op in _ACCUM_OPS:
            s.assert_vrf_ordering(self.vd, element_width)

        s.set_vrf_ordering(self.vd, element_width)

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

        s.assert_vrf_ordering(self.vs1, element_width)
        s.assert_vrf_ordering(self.vs2, element_width)
        if self.op in self._ACCUM_OPS:
            s.assert_vrf_ordering(self.vd, element_width)

        s.set_vrf_ordering(self.vd, element_width)

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

        s.assert_vrf_ordering(self.vs2, element_width)
        if self.op in self._ACCUM_OPS:
            s.assert_vrf_ordering(self.vd, element_width)

        rs1_bytes = s.scalar.read_reg(self.rs1)

        s.set_vrf_ordering(self.vd, element_width)

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

        s.assert_vrf_ordering(self.vs2, element_width)

        # Sign-extend the 5-bit immediate
        imm_val = self.simm5 if self.simm5 < 16 else self.simm5 - 32
        # Convert to bytes (using word_bytes to match scalar register size)
        imm_bytes = imm_val.to_bytes(s.params.word_bytes, byteorder='little', signed=True)

        s.set_vrf_ordering(self.vd, element_width)

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

    Used for vsext.vfN, vzext.vfN, vnsrl.wi, vmv.v.v, and other unary operations.

    Width modes (controlled by `widening` and `narrowing`):
    - widening=True:  dst_ew = SEW, src_ew = SEW / factor (vzext, vsext)
    - narrowing=True: dst_ew = SEW, src_ew = SEW * factor (vnsrl)
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
    shift_amount: int = 0

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        if self.shift_amount:
            return (f'{self.mnemonic}\tv{self.vd},v{self.vs2},'
                    f'0x{self.shift_amount:x}{vm_str}')
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
            shift_amount=self.shift_amount,
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

        s.assert_vrf_ordering(self.vs1, element_width)
        s.assert_vrf_ordering(self.vs2, element_width)

        s.set_vrf_ordering(self.vd, element_width)

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
