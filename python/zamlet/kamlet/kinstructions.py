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
from dataclasses import dataclass
from enum import Enum

from zamlet import addresses
from zamlet.addresses import KMAddr, GlobalAddress
from zamlet.params import LamletParams
from zamlet.monitor import CompletionType, SpanType


logger = logging.getLogger(__name__)


class VArithOp(Enum):
    ADD = "add"
    MUL = "mul"
    MACC = "macc"


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
    def create_span(self, monitor, parent_span_id: int) -> int:
        """Create a span for this kinstr. Override for custom completion type."""
        return monitor.create_span(
            span_type=SpanType.KINSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            parent_span_id=parent_span_id,
            instr_type=type(self).__name__,
            instr_ident=self.instr_ident,
        )


@dataclass
class WriteImmBytes(KInstr):
    """
    This instruction writes an immediate to the VPU memory.
    The scalar processor does not receive a response.
    """
    k_maddr: KMAddr
    imm: bytes
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_write_imm_bytes_instr(self)


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
class ReadByte(KInstr):
    """
    This instruction reads from the VPU memory.
    The scalar processor receives a response packet.
    """
    k_maddr: KMAddr
    instr_ident: int

    async def update_kamlet(self, kamlet: 'Kamlet'):
        await kamlet.handle_read_byte_instr(self)

#@dataclass
#class ReadLine(KInstr):
#    k_maddr: KMAddr      # An address in the kamlet memory space (~40 bits)  
#    j_saddr: JSAddr      # An address in the kamlet sram space   (12-16 bit)
#    n_cache_lines: int   # The number of cache lines to read.    (4 bits)
#    ident: int           # Used for tagging responses with       (5 bits)
#    # This is tough to fit in 64 bits with the opcode.
#    # 38 + 12 + 4 + 5 = 59 bits + 5 for opcode
#    # So it is doable.  Good for now.
#
#    async def update_kamlet(self, kamlet):
#        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): ReadLine')
#        future = await kamlet.handle_read_line_instruction(self)


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


#@dataclass
#class Store(KInstr):
#    src: int
#    j_saddr: JSAddr  # An address in the jamlet sram space
#    n_vlines: int
#
#    async def update_kamlet(self, kamlet):
#        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): Store src=v{self.src}')
#        params = kamlet.params
#        bytes_per_jamlet = params.vline_bytes // params.j_in_l * self.n_vlines
#        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
#        vreg_base_offset = self.src * vreg_bytes_per_jamlet
#        assert bytes_per_jamlet == vreg_bytes_per_jamlet * self.n_vlines
#        sram_offset = self.j_saddr.addr
#        for jamlet in kamlet.jamlets:
#            #logger.debug(f'storing {[int(x) for x in jamlet.rf_slice[vreg_base_offset: vreg_base_offset + bytes_per_jamlet]]}')
#            jamlet.sram[sram_offset: sram_offset + bytes_per_jamlet] = jamlet.rf_slice[vreg_base_offset: vreg_base_offset + bytes_per_jamlet]


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
        kamlet.monitor.complete_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


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
        kamlet.monitor.complete_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


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
        kamlet.monitor.complete_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


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
        kamlet.monitor.complete_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class ReadRegElement(KInstr):
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
                        src1_val = int.from_bytes(src1_bytes, byteorder='little', signed=True)
                        src2_bytes = jamlet.rf_slice[src2_offset + byte_offset:src2_offset + byte_offset + eb]
                        src2_val = int.from_bytes(src2_bytes, byteorder='little', signed=True)

                        if self.op == VArithOp.ADD:
                            result = src1_val + src2_val
                        elif self.op == VArithOp.MUL:
                            result = src1_val * src2_val
                        elif self.op == VArithOp.MACC:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = int.from_bytes(acc_bytes, byteorder='little', signed=True)
                            result = (src1_val * src2_val) + acc_val
                        else:
                            assert NotImplementedError()

                        result_bytes = result.to_bytes(eb, byteorder='little', signed=True)
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = result_bytes
        kamlet.monitor.complete_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


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
        kamlet.monitor.complete_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


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
