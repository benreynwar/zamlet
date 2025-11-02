"""Vector extension instructions.

Reference: riscv-isa-manual/src/v-st-ext.adoc
"""

import logging
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING
import kinstructions
import addresses

from register_names import reg_name, freg_name

if TYPE_CHECKING:
    import state

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

    async def update_state(self, s: 'state.State'):
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
class Vle8V:
    """VLE8.V - Vector Load 8-bit Elements.

    Unit-stride load of 8-bit elements from memory into a vector register.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vle8.v\tv{self.vd},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        logger.debug(f'{s.clock.cycle}: waiting for ready regs')
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg=None
        else:
            mask_reg=0
        logger.debug(f'{s.clock.cycle}: do load')
        await s.vload(self.vd, addr, 8, s.vl, mask_reg)
        logger.debug(f'{s.clock.cycle}: kicked off load')
        s.pc += 4
        logger.debug(f'Loaded vector into vd={self.vd}')


@dataclass
class Vse8V:
    """VSE8.V - Vector Store 8-bit Elements.

    Unit-stride store of 8-bit elements from vector register to memory.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vs3: int
    rs1: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vse8.v\tv{self.vs3},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
        await s.vstore(self.vs3, addr, 8, s.vl, mask_reg)
        s.pc += 4
        logger.debug(f'Stored vector from vs3={self.vs3}')


@dataclass
class Vle16V:
    """VLE16.V - Vector Load 16-bit Elements.

    Unit-stride load of 16-bit elements from memory into a vector register.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vle16.v\tv{self.vd},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        logger.debug(f'{s.clock.cycle}: waiting for ready regs')
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg=None
        else:
            mask_reg=0
        logger.debug(f'{s.clock.cycle}: do load')
        await s.vload(self.vd, addr, 16, s.vl, mask_reg)
        logger.debug(f'{s.clock.cycle}: kicked off load')
        s.pc += 4
        logger.debug(f'Loaded vector into vd={self.vd}')


@dataclass
class Vse16V:
    """VSE16.V - Vector Store 16-bit Elements.

    Unit-stride store of 16-bit elements from vector register to memory.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vs3: int
    rs1: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vse16.v\tv{self.vs3},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
        await s.vstore(self.vs3, addr, 16, s.vl, mask_reg)
        s.pc += 4
        logger.debug(f'Stored vector from vs3={self.vs3}')


@dataclass
class Vle32V:
    """VLE32.V - Vector Load 32-bit Elements.

    Unit-stride load of 32-bit elements from memory into a vector register.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vle32.v\tv{self.vd},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        logger.debug(f'{s.clock.cycle}: waiting for ready regs')
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg=None
        else:
            mask_reg=0
        logger.debug(f'{s.clock.cycle}: do load')
        await s.vload(self.vd, addr, 32, s.vl, mask_reg)
        logger.debug(f'{s.clock.cycle}: kicked off load')
        s.pc += 4
        logger.debug(f'Loaded vector into vd={self.vd}')



@dataclass
class Vse32V:
    """VSE32.V - Vector Store 32-bit Elements.

    Unit-stride store of 32-bit elements from vector register to memory.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vs3: int
    rs1: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vse32.v\tv{self.vs3},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
        await s.vstore(self.vs3, addr, 32, s.vl, mask_reg)
        s.pc += 4
        logger.debug(f'Stored vector from vs3={self.vs3}')


@dataclass
class Vle64V:
    """VLE64.V - Vector Load 64-bit Elements.

    Unit-stride load of 64-bit elements from memory into a vector register.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vle64.v\tv{self.vd},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        logger.debug(f'{s.clock.cycle}: waiting for ready regs')
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg=None
        else:
            mask_reg=0
        logger.debug(f'{s.clock.cycle}: do load')
        await s.vload(self.vd, addr, 64, s.vl, mask_reg)
        logger.debug(f'{s.clock.cycle}: kicked off load')
        s.pc += 4
        logger.debug(f'Loaded vector into vd={self.vd}')


@dataclass
class Vse64V:
    """VSE64.V - Vector Store 64-bit Elements.

    Unit-stride store of 64-bit elements from vector register to memory.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vs3: int
    rs1: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vse64.v\tv{self.vs3},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
        await s.vstore(self.vs3, addr, 64, s.vl, mask_reg)
        s.pc += 4
        logger.debug(f'Stored vector from vs3={self.vs3}')


@dataclass
class VaddVx:
    """VADD.VX - Vector-Scalar Integer Add.

    vd[i] = vs2[i] + rs1

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int
    vs2: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vadd.vx\tv{self.vd},v{self.vs2},{reg_name(self.rs1)}{vm_str}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        element_width = 32
        assert s.vrf_ordering[self.vd].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        rs1_bytes = s.scalar.read_reg(self.rs1)
        scalar_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        logger.debug(f'VADD.VX: vd=v{self.vd}, rs1={reg_name(self.rs1)}={scalar_val}, vs2=v{self.vs2}, vl={s.vl}')

        kinstr = kinstructions.VaddVxOp(
            dst=self.vd,
            src=self.vs2,
            scalar=scalar_val,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            )
        await s.add_to_instruction_buffer(kinstr)
        s.pc += 4


@dataclass
class VfmaccVf:
    """VFMACC.VF - Vector Floating-Point Multiply-Accumulate.

    vd[i] = vd[i] + (rs1 * vs2[i])

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int
    vs2: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vfmacc.vf\tv{self.vd},{freg_name(self.rs1)},v{self.vs2}{vm_str}'

    async def update_state(self, s: 'state.State'):
        logger.debug(f'{s.clock.cycle}: VfmaccVf waiting for regs')
        await s.scalar.wait_all_regs_ready(None, None, [], [self.rs1])
        logger.debug(f'{s.clock.cycle}: VfmaccVf got regs')

        # Get element width from vtype (set by vsetvli)
        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew  # vsew: 0=e8, 1=e16, 2=e32, 3=e64
        word_order = addresses.WordOrder.STANDARD
        assert s.vrf_ordering[self.vd].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        # Read scalar with appropriate width (4 bytes for float, 8 for double)
        scalar_bytes = s.scalar.read_freg(self.rs1)
        scalar_byte_count = element_width // 8
        scalar_bits = int.from_bytes(scalar_bytes[:scalar_byte_count], byteorder='little', signed=False)

        if element_width == 64:
            scalar_value = struct.unpack('d', scalar_bytes[:8])[0]
        else:
            scalar_value = struct.unpack('f', scalar_bytes[:4])[0]

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        logger.debug(f'VFMACC.VF: vd=v{self.vd}, rs1={freg_name(self.rs1)}={scalar_value}, vs2=v{self.vs2}, vl={s.vl}, ew={element_width}')

        kinstr = kinstructions.VfmaccVfOp(
            dst=self.vd,
            src=self.vs2,
            scalar_bits=scalar_bits,
            mask_reg=mask_reg,
            n_elements=s.vl,
            word_order=word_order,
            element_width=element_width,
            )
        await s.add_to_instruction_buffer(kinstr)
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

    async def update_state(self, s: 'state.State'):
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
        from addresses import Ordering, WordOrder
        mask_ordering = Ordering(WordOrder.STANDARD, 1)
        for i in range(n_dst_vlines):
            s.vrf_ordering[self.vd + i] = mask_ordering

        kinstr = kinstructions.VmsleViOp(
            dst=self.vd,
            src=self.vs2,
            simm5=self.simm5,
            n_elements=s.vl,
            element_width=element_width,
            ordering=s.vrf_ordering[self.vs2],
        )
        await s.add_to_instruction_buffer(kinstr)
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

    async def update_state(self, s: 'state.State'):
        # Get ordering from source mask registers
        vs2_ordering = s.vrf_ordering[self.vs2]
        vs1_ordering = s.vrf_ordering[self.vs1]

        # Mask registers should have element width of 1
        assert vs2_ordering.ew == 1
        assert vs1_ordering.ew == 1

        # Set ordering for destination mask register to match source
        s.vrf_ordering[self.vd] = vs2_ordering

        kinstr = kinstructions.VmnandMmOp(
            dst=self.vd,
            src1=self.vs2,
            src2=self.vs1,
        )
        await s.add_to_instruction_buffer(kinstr)
        s.pc += 4
