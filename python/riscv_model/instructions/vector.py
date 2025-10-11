"""Vector extension instructions.

Reference: riscv-isa-manual/src/v-st-ext.adoc
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from register_names import reg_name, freg_name

if TYPE_CHECKING:
    import state


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
    reg_size_bytes = s.params.maxvl_words * s.params.word_width_bytes
    byte_offset = elem_idx * elem_width_bytes
    vreg_num = vreg_base + byte_offset // reg_size_bytes
    elem_offset = byte_offset % reg_size_bytes
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

    def update_state(self, s: 'state.State'):
        avl = s.scalar.read_reg(self.rs1)

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

        vlen_bits = s.params.maxvl_words * s.params.word_width_bytes * 8
        vlmax = int((vlen_bits / sew) * lmul)

        if avl <= vlmax:
            s.vl = avl
        else:
            s.vl = vlmax

        s.scalar.write_reg(self.rd, s.vl)
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

    def update_state(self, s: 'state.State'):
        addr = s.scalar.read_reg(self.rs1)
        elem_width_bytes = 4

        for i in range(s.vl):
            if is_masked(s, i, self.vm):
                continue

            elem_addr = addr + i * elem_width_bytes
            elem_bytes = s.get_memory(elem_addr, elem_width_bytes)

            vreg_num, elem_offset = get_vreg_location(self.vd, i, elem_width_bytes, s)
            s.vpu_logical.vrf[vreg_num][elem_offset:elem_offset+elem_width_bytes] = elem_bytes

        s.pc += 4


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

    def update_state(self, s: 'state.State'):
        addr = s.scalar.read_reg(self.rs1)
        elem_width_bytes = 4

        for i in range(s.vl):
            if is_masked(s, i, self.vm):
                continue

            vreg_num, elem_offset = get_vreg_location(self.vs3, i, elem_width_bytes, s)
            elem_bytes = s.vpu_logical.vrf[vreg_num][elem_offset:elem_offset+elem_width_bytes]

            elem_addr = addr + i * elem_width_bytes
            s.set_memory(elem_addr, elem_bytes)

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

    def update_state(self, s: 'state.State'):
        import struct

        scalar_bits = s.scalar.read_freg(self.rs1)
        scalar_val = struct.unpack('f', struct.pack('I', scalar_bits & 0xffffffff))[0]
        elem_width_bytes = 4

        for i in range(s.vl):
            if is_masked(s, i, self.vm):
                continue

            vreg_vs2, offset_vs2 = get_vreg_location(self.vs2, i, elem_width_bytes, s)
            vec_elem_bytes = s.vpu_logical.vrf[vreg_vs2][offset_vs2:offset_vs2+elem_width_bytes]
            vec_val = struct.unpack('f', vec_elem_bytes)[0]

            vreg_vd, offset_vd = get_vreg_location(self.vd, i, elem_width_bytes, s)
            acc_elem_bytes = s.vpu_logical.vrf[vreg_vd][offset_vd:offset_vd+elem_width_bytes]
            acc_val = struct.unpack('f', acc_elem_bytes)[0]

            result = acc_val + (scalar_val * vec_val)
            result_bytes = struct.pack('f', result)

            s.vpu_logical.vrf[vreg_vd][offset_vd:offset_vd+elem_width_bytes] = result_bytes

        s.pc += 4
