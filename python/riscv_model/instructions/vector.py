"""Vector extension instructions.

Reference: riscv-isa-manual/src/v-st-ext.adoc
"""

import logging
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING
import kinstructions

from register_names import reg_name, freg_name

if TYPE_CHECKING:
    import state

logger = logging.getLogger(__name__)


def compute_emul(eew_bits: int, s: 'state.State') -> tuple[float, int]:
    """Compute EMUL (effective LMUL) for vector memory operations.

    Returns: (emul_float, emul_int) where emul_int = max(1, int(emul_float))
    """
    vsew = (s.vtype >> 3) & 0x7
    sew = 8 << vsew
    vlmul = s.vtype & 0x7
    if vlmul <= 3:
        lmul = 1 << vlmul
    else:
        lmul = 1.0 / (1 << (8 - vlmul))

    emul = (eew_bits / sew) * lmul
    emul_int = max(1, int(emul))
    return emul, emul_int


def is_masked(s: 'state.State', i: int, vm: int) -> bool:
    """Check if element i is masked out (returns True if masked out)."""
    if vm:
        return False

    mask_bit_idx = i
    mask_byte_idx = mask_bit_idx // 8
    mask_bit_offset = mask_bit_idx % 8
    mask_byte = s.vpu_logical.vrf[0][mask_byte_idx]
    return not (mask_byte & (1 << mask_bit_offset))


def get_vreg_location(vreg_base: int, elem_idx: int, elem_width_bytes: int,
                      s: 'state.State') -> tuple[int, int]:
    """Get (vreg_num, offset) for element at given index.

    Handles register groups when EMUL > 1.
    """
    byte_offset = elem_idx * elem_width_bytes
    vreg_num = vreg_base + byte_offset // s.params.maxvl_bytes
    elem_offset = byte_offset % s.params.maxvl_bytes
    return vreg_num, elem_offset


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
        await s.scalar.wait_all_regs_ready([self.rs1], [])
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

        if avl <= vlmax:
            s.vl = avl
        else:
            s.vl = vlmax

        vl_bytes = s.vl.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, vl_bytes)
        logger.info(f'Set vl to {s.vl}')
        s.pc += 4


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
        await s.scalar.wait_all_regs_ready([self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg=None
        else:
            mask_reg=0
        await s.vload(self.vd, addr, 32, s.vl, mask_reg)
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
        await s.scalar.wait_all_regs_ready([self.rs1], [])
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
        await s.scalar.wait_all_regs_ready([self.rs1], [])
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        element_width = 32
        assert s.vrf_ordering[self.vd].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        rs1_bytes = s.scalar.read_reg(self.rs1)
        scalar_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        logger.info(f'VADD.VX: vd=v{self.vd}, rs1={reg_name(self.rs1)}={scalar_val}, vs2=v{self.vs2}, vl={s.vl}')

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        assert (s.vl * element_width) % (vline_bytes * 8) == 0
        n_vlines = (s.vl * element_width)//(vline_bytes * 8)

        kinstr = kinstructions.VaddVxOp(
            dst=self.vd,
            src=self.vs2,
            scalar=scalar_val,
            mask_reg=mask_reg,
            n_vlines=n_vlines,
            )
        await s.send_instruction(kinstr)
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
        await s.scalar.wait_all_regs_ready([], [self.rs1])
        scalar_bytes = s.scalar.read_freg(self.rs1)
        scalar_bits = int.from_bytes(scalar_bytes[:4], byteorder='little', signed=False)

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        element_width = 32
        assert s.vrf_ordering[self.vd].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        logger.debug(f'VFMACC.VF: vd=v{self.vd}, rs1={freg_name(self.rs1)}={scalar_bits}, vs2=v{self.vs2}, vl={s.vl}')

        vline_bytes = s.params.word_bytes * s.params.j_in_l
        assert (s.vl * element_width) % (vline_bytes * 8) == 0
        n_vlines = (s.vl * element_width)//(vline_bytes * 8)

        kinstr = kinstructions.VfmaccVfOp(
            dst=self.vd,
            src=self.vs2,
            scalar_bits=scalar_bits,
            mask_reg=mask_reg,
            n_vlines=n_vlines,
            )
        await s.send_instruction(kinstr)
        s.pc += 4
