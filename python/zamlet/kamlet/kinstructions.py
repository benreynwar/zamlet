'''
Opcode = 6 bit

registers can point at the register file, or at received messages

Load             dst (6 bit)    sram (12 bit)  mask (5 bit)  length (3) sp_or_mem (1) = 33 bit  if mem it needs an address too
Store            src (6 bit)    sram (12 bit)  mask (5 bit)  length (3) sp_or_mem (1) = 33 bit  if mem it needs an address too
Read Line        sram (12 bit)  memory (64 memory) length (3)  = 21 + 64 bit
Write Line       sram (12 bit)  memory (64 memory) length (3)  = 21 + 64 bit   + 1 bit for if evicting
Operation        dst (6 bit) src1 (6 bit) src2 (6 bit)  mask (5 bit) (length 3) = 24 bit
Send             src (6 bit)    target (6 bit) mask (5 bit)  length (3)  =  26 bit
'''

import logging
import struct
from dataclasses import dataclass
from enum import Enum

from zamlet import addresses
from zamlet.addresses import KMAddr, GlobalAddress
from zamlet.params import LamletParams
from zamlet.monitor import CompletionType, SpanType


logger = logging.getLogger(__name__)


class VArithOp(Enum):
    # Integer
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    MACC = "macc"
    AND = "and"
    OR = "or"
    XOR = "xor"
    SLL = "sll"
    SRL = "srl"
    SRA = "sra"
    MIN = "min"
    MAX = "max"
    MINU = "minu"
    MAXU = "maxu"
    # Float
    FADD = "fadd"
    FSUB = "fsub"
    FMUL = "fmul"
    FDIV = "fdiv"
    FMACC = "fmacc"
    FMIN = "fmin"
    FMAX = "fmax"


class VRedOp(Enum):
    SUM = "sum"
    MAXU = "maxu"
    MAX = "max"
    MINU = "minu"
    MIN = "min"
    AND = "and"
    OR = "or"
    XOR = "xor"


class KInstr:
    @property
    def finalize_after_send(self) -> bool:
        """Whether to finalize children after sending the instruction to kamlets.

        Override to return False if additional children (like response messages)
        will be added later.
        """
        return True

    def create_span(self, monitor, parent_span_id: int) -> int:
        """Create a span for this kinstr."""
        return monitor.create_span(
            span_type=SpanType.KINSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            parent_span_id=parent_span_id,
            instr_type=type(self).__name__,
            instr_ident=self.instr_ident,
        )


class TrackedKInstr(KInstr):
    """KInstr subclass for instructions where lamlet waits for a response."""
    def create_span(self, monitor, parent_span_id: int) -> int:
        return monitor.create_span(
            span_type=SpanType.KINSTR,
            component="lamlet",
            completion_type=CompletionType.TRACKED,
            parent_span_id=parent_span_id,
            instr_type=type(self).__name__,
            instr_ident=self.instr_ident,
        )


@dataclass
class LoadImmByte(KInstr):
    """
    This instruction writes an immediate to a byte of a vector register.
    """
    dst: addresses.RegAddr
    imm: int
    # Which bits of the byte we write.
    bit_mask: int
    # An identifier. Writes with the same writeset_ident are guaranteed not to clash.
    writeset_ident: int
    mask_reg: int
    # Offset of the mask in the mask register (in multiples of j_in_l)
    # Needed since we may be writing into the middle of a vector group.
    mask_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_imm_byte_instr(self)


@dataclass
class LoadWord(KInstr):
    """
    This instruction load a word from memory to a location in a vector register.
    """
    dst: addresses.RegAddr
    src: KMAddr
    # Which bytes to the word we write
    byte_mask: int
    # An identifier. Writes with the same writeset_ident are guaranteed not to clash.
    writeset_ident: int
    mask_reg: int
    mask_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_word_instr(self)


@dataclass
class LoadImmWord(KInstr):
    """
    This instruction writes an immediate to a byte of a vector register.
    """
    dst: addresses.RegAddr
    imm: bytes
    # Which bytes of the word we write
    byte_mask: int
    # An identifier. Writes with the same writeset_ident are guaranteed not to clash.
    writeset_ident: int
    mask_reg: int
    mask_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_imm_word_instr(self)

@dataclass
class StoreWord(KInstr):
    """
    This instruction stores a word from a vector register to memory.
    """
    src: addresses.RegAddr
    dst: KMAddr
    # Which bytes of the word we write
    byte_mask: int
    # An identifier. Writes with the same writeset_ident are guaranteed not to clash.
    writeset_ident: int
    mask_reg: int
    mask_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_store_word_instr(self)


@dataclass
class Load(KInstr):
    """
    A load from the VPU memory into a vector register.
    The k_maddr points to the location of the start_index element.

    stride_bytes: byte stride between elements. None = unit stride (ew/8 bytes).
    """
    dst: int
    # The address of the start_index element in the kamlet address space.
    k_maddr: KMAddr
    start_index: int
    n_elements: int
    dst_ordering: addresses.Ordering  # src ordering is held in k_maddr
    mask_reg: int|None
    writeset_ident: int
    instr_ident: int
    stride_bytes: int|None = None

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_instr(self)


@dataclass
class Store(KInstr):
    """
    A store from a vector register to VPU memory.

    stride_bytes: byte stride between elements. None = unit stride (ew/8 bytes).
    """
    src: int
    k_maddr: KMAddr  # An address in the kamlet address space
    start_index: int
    n_elements: int
    src_ordering: addresses.Ordering
    mask_reg: int
    writeset_ident: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_store_instr(self)


@dataclass
class VmsleViOp(KInstr):
    dst: int
    src: int
    simm5: int
    n_elements: int
    element_width: int
    ordering: addresses.Ordering
    instr_ident: int

    async def update_kamlet(self, kamlet):
        elements_in_src_vline = kamlet.params.vline_bytes * 8 // self.element_width
        n_src_vlines = (self.n_elements + elements_in_src_vline - 1)//elements_in_src_vline
        src_regs = [self.src+index for index in range(n_src_vlines)]

        elements_in_dst_vline = kamlet.params.vline_bytes * 8
        n_dst_vlines = (self.n_elements + elements_in_dst_vline - 1)//elements_in_dst_vline
        dst_regs = [self.dst+index for index in range(n_dst_vlines)]

        await kamlet.wait_for_rf_available(read_regs=src_regs, write_regs=dst_regs,
                                           instr_ident=self.instr_ident)
        sign_extended_imm = self.simm5 if self.simm5 < 16 else self.simm5 - 32

        base_src_bit_addr = self.src * kamlet.params.word_bytes * 8
        base_dst_bit_addr = self.dst * kamlet.params.word_bytes * 8

        for element_index in range(self.n_elements):
            vw_index = element_index % kamlet.params.j_in_l
            k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                kamlet.params, self.ordering.word_order, vw_index)
            element_in_jamlet = element_index // kamlet.params.j_in_l
            if k_index == kamlet.k_index:
                jamlet = kamlet.jamlets[j_in_k_index]
                src_bit_addr = base_src_bit_addr + element_in_jamlet * self.element_width
                assert src_bit_addr % 8 == 0
                src_bytes = jamlet.rf_slice[src_bit_addr//8:src_bit_addr//8 + self.element_width//8]
                src_val = int.from_bytes(src_bytes, byteorder='little', signed=True)
                result_bit = 1 if src_val <= sign_extended_imm else 0
                dst_bit_addr = base_dst_bit_addr + element_in_jamlet
                dst_byte_addr = dst_bit_addr // 8
                dst_bit_offset = dst_bit_addr % 8
                if result_bit:
                    jamlet.rf_slice[dst_byte_addr] |= (1 << dst_bit_offset)
                else:
                    jamlet.rf_slice[dst_byte_addr] &= ~(1 << dst_bit_offset)
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VmnandMmOp(KInstr):
    dst: int
    src1: int
    src2: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        read_regs = []
        if self.src1 != self.dst:
            read_regs.append(self.src1)
        if self.src2 != self.dst and self.src2 not in read_regs:
            read_regs.append(self.src2)
        await kamlet.wait_for_rf_available(read_regs=read_regs, write_regs=[self.dst],
                                           instr_ident=self.instr_ident)

        wb = kamlet.params.word_bytes
        for jamlet in kamlet.jamlets:
            for byte_offset in range(wb):
                src1_byte = jamlet.rf_slice[self.src1 * wb + byte_offset]
                src2_byte = jamlet.rf_slice[self.src2 * wb + byte_offset]
                result_byte = ~(src1_byte & src2_byte) & 0xff
                jamlet.rf_slice[self.dst * wb + byte_offset] = result_byte
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VBroadcastOp(KInstr):
    """Broadcast a scalar value to all elements of a vector register.

    Used for vmv.v.i, vmv.v.x instructions.
    """
    dst: int
    scalar: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        dst_regs = [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(write_regs=dst_regs, instr_ident=self.instr_ident)

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order, None,
                        vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element:
                        result_bytes = self.scalar.to_bytes(eb, byteorder='little', signed=True)
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = result_bytes
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VmvVvOp(KInstr):
    dst: int
    src: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        src_regs = [self.src+index for index in range(n_vlines)]
        dst_regs = [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(read_regs=src_regs, write_regs=dst_regs,
                                           instr_ident=self.instr_ident)

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src_offset = self.src * vreg_bytes_per_jamlet
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order, None,
                        vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element:
                        src_bytes = jamlet.rf_slice[src_offset + byte_offset:src_offset + byte_offset + eb]
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = src_bytes
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class ReadRegElement(TrackedKInstr):
    rd: int
    src: int
    element_index: int
    element_width: int
    ident: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_read_reg_element_instr(self)


@dataclass
class VArithVvOp(KInstr):
    op: VArithOp
    dst: int
    src1: int
    src2: int
    mask_reg: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        src_regs = [self.src1+index for index in range(n_vlines)]
        src_regs += [self.src2+index for index in range(n_vlines)]
        dst_regs = [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(read_regs=src_regs, write_regs=dst_regs,
                                           instr_ident=self.instr_ident)

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src1_offset = self.src1 * vreg_bytes_per_jamlet
        src2_offset = self.src2 * vreg_bytes_per_jamlet
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order, self.mask_reg,
                        vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element and mask_bit:
                        src1_bytes = jamlet.rf_slice[src1_offset + byte_offset:src1_offset + byte_offset + eb]
                        src2_bytes = jamlet.rf_slice[src2_offset + byte_offset:src2_offset + byte_offset + eb]
                        float_ops = (VArithOp.FADD, VArithOp.FSUB, VArithOp.FMUL, VArithOp.FDIV,
                                     VArithOp.FMACC, VArithOp.FMIN, VArithOp.FMAX)
                        signed_int_ops = (VArithOp.ADD, VArithOp.SUB, VArithOp.MUL, VArithOp.MACC,
                                          VArithOp.AND, VArithOp.OR, VArithOp.XOR,
                                          VArithOp.SLL, VArithOp.SRA, VArithOp.MIN, VArithOp.MAX)
                        unsigned_int_ops = (VArithOp.MINU, VArithOp.MAXU, VArithOp.SRL)
                        if self.op in float_ops:
                            fmt = {8: 'd', 4: 'f', 2: 'e'}[eb]
                        elif self.op in signed_int_ops:
                            fmt = {8: '<q', 4: '<i', 2: '<h', 1: '<b'}[eb]
                        elif self.op in unsigned_int_ops:
                            fmt = {8: '<Q', 4: '<I', 2: '<H', 1: '<B'}[eb]
                        else:
                            raise NotImplementedError(f"Unknown op: {self.op}")
                        src1_val = struct.unpack(fmt, src1_bytes)[0]
                        src2_val = struct.unpack(fmt, src2_bytes)[0]

                        if self.op == VArithOp.ADD:
                            result = src1_val + src2_val
                        elif self.op == VArithOp.SUB:
                            result = src2_val - src1_val
                        elif self.op == VArithOp.MUL:
                            result = src1_val * src2_val
                        elif self.op == VArithOp.MACC:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = struct.unpack(fmt, acc_bytes)[0]
                            result = (src1_val * src2_val) + acc_val
                        elif self.op == VArithOp.AND:
                            result = src1_val & src2_val
                        elif self.op == VArithOp.OR:
                            result = src1_val | src2_val
                        elif self.op == VArithOp.XOR:
                            result = src1_val ^ src2_val
                        elif self.op == VArithOp.SLL:
                            result = src2_val << (src1_val & (eb * 8 - 1))
                        elif self.op == VArithOp.SRL:
                            result = src2_val >> (src1_val & (eb * 8 - 1))
                        elif self.op == VArithOp.SRA:
                            result = src2_val >> (src1_val & (eb * 8 - 1))
                        elif self.op == VArithOp.MIN:
                            result = min(src1_val, src2_val)
                        elif self.op == VArithOp.MAX:
                            result = max(src1_val, src2_val)
                        elif self.op == VArithOp.MINU:
                            result = min(src1_val, src2_val)
                        elif self.op == VArithOp.MAXU:
                            result = max(src1_val, src2_val)
                        elif self.op == VArithOp.FADD:
                            result = src2_val + src1_val
                        elif self.op == VArithOp.FSUB:
                            result = src2_val - src1_val
                        elif self.op == VArithOp.FMUL:
                            result = src2_val * src1_val
                        elif self.op == VArithOp.FDIV:
                            result = src2_val / src1_val
                        elif self.op == VArithOp.FMACC:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = struct.unpack(fmt, acc_bytes)[0]
                            result = (src1_val * src2_val) + acc_val
                        elif self.op == VArithOp.FMIN:
                            result = min(src1_val, src2_val)
                        elif self.op == VArithOp.FMAX:
                            result = max(src1_val, src2_val)
                        else:
                            raise NotImplementedError(f"Unknown op: {self.op}")

                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = struct.pack(fmt, result)
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VArithVxOp(KInstr):
    op: VArithOp
    dst: int
    scalar_bytes: bytes
    src2: int
    mask_reg: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int
    is_float: bool = False

    async def update_kamlet(self, kamlet):
        import struct
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        src_regs = [self.src2+index for index in range(n_vlines)]
        dst_regs = [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(read_regs=src_regs, write_regs=dst_regs,
                                           instr_ident=self.instr_ident)

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src2_offset = self.src2 * vreg_bytes_per_jamlet
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes

        if self.is_float:
            fmt_code = 'd' if self.element_width == 64 else 'f'
            unpack = lambda b: struct.unpack(fmt_code, b)[0]
            pack = lambda v: struct.pack(fmt_code, v)
        else:
            unpack = lambda b: int.from_bytes(b, byteorder='little', signed=True)
            pack = lambda v: v.to_bytes(eb, byteorder='little', signed=True)

        scalar_val = unpack(self.scalar_bytes[:eb])
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order,
                        self.mask_reg, vline_index, j_in_k_index, index_in_j)
                    if valid_element and mask_bit:
                        src2_bytes = jamlet.rf_slice[src2_offset + byte_offset:src2_offset + byte_offset + eb]
                        src2_val = unpack(src2_bytes)

                        if self.op == VArithOp.ADD:
                            result = src2_val + scalar_val
                        elif self.op == VArithOp.MUL:
                            result = src2_val * scalar_val
                        elif self.op == VArithOp.MACC:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = unpack(acc_bytes)
                            result = acc_val + (scalar_val * src2_val)

                        result_bytes = pack(result)
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = result_bytes
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VreductionVsOp(KInstr):
    op: VRedOp
    dst: int
    src_vector: int
    src_scalar_reg: int
    mask_reg: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_vreduction_vs_instr(self)


