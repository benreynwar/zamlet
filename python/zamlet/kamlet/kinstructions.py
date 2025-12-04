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
    pass


class LocalKInstr(KInstr):
    @property
    def instr_ident(self) -> int | None:
        return None


@dataclass
class WriteImmBytes(LocalKInstr):
    """
    This instruction writes an immediate to the VPU memory.
    The scalar processor does not receive a response.
    """
    k_maddr: KMAddr
    imm: bytes

    async def update_kamlet(self, kamlet):
        await kamlet.handle_write_imm_bytes_instr(self)
        #logger.error(f'Writing {int(self.imm[0])} to {hex(self.k_maddr.addr)}')


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
class ZeroLines(LocalKInstr):
    """
    Sets an entire cache line to 0.
    This is useful since we can create a cache line in the SRAM
    without having to load from memory.
    """
    k_maddr: KMAddr
    n_cache_lines: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_zero_lines_instr(self)


@dataclass
class DiscardLines(LocalKInstr):
    """
    Throws away cache lines.
    Says we will never use this data so you don't need to flush to
    memory and you can free those cache slots.
    """
    k_maddr: KMAddr
    n_cache_lines: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_discard_lines_instr(self)


#@dataclass
#class WriteLine(KInstr):
#    k_maddr: KMAddr  # An address in the kamlet memory space
#    j_saddr: JSAddr    # An address in the kamlet sram space
#    n_cache_lines: int   # The number of cache lines to read.
#    ident: int   # An identifier that we will use to tag responses with.
#
#    async def update_kamlet(self, kamlet):
#        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): WriteLine')
#        future = await kamlet.handle_write_line_instruction(self)


"""
We can have several differnt kinds of aligned loads.

The load is aligned with a vline:
    straightforward case.

The load is not aligned
    we might access an extra cache line
    we probably need an extra cycle read from the sram cache
    we need to mix data from different cache words to make the register
    words.
    we need to do a barrel shift of the vector
    We'll split this into a unaligned load and a vector barrel shift.
"""


@dataclass
class ExpectRead(LocalKInstr):
    """
    An instruction that let's the kamlet know to expect a read.
    This is used to update the cache state so that this kamlet
    doesn't process a write before the read completes.

    We if we send a load instruction to a single kamlet, we should
    send a ExpectRead instruction to the kamlet that it will be
    reading the cache from.
    """

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_aligned_instr(self)


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
class VmsleViOp(LocalKInstr):
    dst: int
    src: int
    simm5: int
    n_elements: int
    element_width: int
    ordering: addresses.Ordering

    async def update_kamlet(self, kamlet):

        elements_in_src_vline = kamlet.params.vline_bytes * 8 // self.element_width
        n_src_vlines = (self.n_elements + elements_in_src_vline - 1)//elements_in_src_vline
        src_regs = [self.src+index for index in range(n_src_vlines)]

        elements_in_dst_vline = kamlet.params.vline_bytes * 8
        n_dst_vlines = (self.n_elements + elements_in_dst_vline - 1)//elements_in_dst_vline
        dst_regs = [self.dst+index for index in range(n_dst_vlines)]

        logger.debug(f'kamlet {(kamlet.min_x, kamlet.min_y)}: waiting for regs {src_regs} + {dst_regs} to be avail')
        await kamlet.wait_for_rf_available(read_regs=src_regs, write_regs=dst_regs)
        logger.debug(f'kamlet {(kamlet.min_x, kamlet.min_y)}: regs are avail')
        logger.info(f'kamlet ({kamlet.min_x} {kamlet.min_y}): VmsleVi dst=v{self.dst} src=v{self.src} imm={self.simm5}')
        sign_extended_imm = self.simm5 if self.simm5 < 16 else self.simm5 - 32

        src_values = []
        results = []

        base_src_bit_addr = self.src * kamlet.params.word_bytes * 8
        base_dst_bit_addr = self.dst * kamlet.params.word_bytes * 8

        for element_index in range(self.n_elements):
            vw_index = element_index % kamlet.params.j_in_l
            k_index, j_in_k_index = addresses.vw_index_to_k_indices(kamlet.params, self.ordering.word_order, vw_index)
            element_in_jamlet = element_index//kamlet.params.j_in_l
            if k_index == kamlet.k_index:
                jamlet = kamlet.jamlets[j_in_k_index]
                src_bit_addr = base_src_bit_addr + element_in_jamlet * self.element_width
                assert src_bit_addr % 8 == 0
                src_bytes = jamlet.rf_slice[src_bit_addr//8:src_bit_addr//8 + self.element_width//8]
                src_val = int.from_bytes(src_bytes, byteorder='little', signed=True)
                logger.debug(f'{kamlet.clock.cycle}: VmsleViOp READ: elem={element_index}, src_addr={src_bit_addr}, bytes={src_bytes.hex()}, val={src_val}')
                result_bit = 1 if src_val <= sign_extended_imm else 0
                src_values.append(src_val)
                results.append(result_bit)
                dst_bit_addr = base_dst_bit_addr + element_in_jamlet
                dst_byte_addr = dst_bit_addr//8
                dst_bit_offset = dst_bit_addr % 8
                logger.debug(f'{kamlet.clock.cycle}: VmsleViOp RESULT: elem={element_index}, val={src_val}, result={result_bit}, dst_byte={dst_byte_addr}, dst_bit={dst_bit_offset}')
                old_byte = jamlet.rf_slice[dst_byte_addr]
                if result_bit:
                    jamlet.rf_slice[dst_byte_addr] |= (1 << dst_bit_offset)
                else:
                    jamlet.rf_slice[dst_byte_addr] &= ~(1 << dst_bit_offset)
                new_byte = jamlet.rf_slice[dst_byte_addr]
                dst_reg = dst_byte_addr // kamlet.params.word_bytes
                logger.debug(
                    f'{kamlet.clock.cycle}: RF_WRITE VmsleViOp: jamlet ({jamlet.x},{jamlet.y}) '
                    f'rf[{dst_reg}] byte {dst_byte_addr % kamlet.params.word_bytes} old={old_byte:02x} new={new_byte:02x}'
                )
        logger.info(f'kamlet: VmsleViOp: srcs = {src_values}, results = {results}')


@dataclass
class VmnandMmOp(LocalKInstr):
    dst: int
    src1: int
    src2: int

    async def update_kamlet(self, kamlet):
        read_regs = []
        if self.src1 != self.dst:
            read_regs.append(self.src1)
        if self.src2 != self.dst and self.src2 not in read_regs:
            read_regs.append(self.src2)
        await kamlet.wait_for_rf_available(read_regs=read_regs, write_regs=[self.dst])
        logger.info(f'kamlet ({kamlet.min_x} {kamlet.min_y}): VmnandMm dst=v{self.dst} src1=v{self.src1} src2=v{self.src2}')

        wb = kamlet.params.word_bytes
        for j_idx, jamlet in enumerate(kamlet.jamlets):
            old_word = jamlet.rf_slice[self.dst * wb:(self.dst + 1) * wb]
            for byte_offset in range(wb):
                src1_byte = jamlet.rf_slice[self.src1 * wb + byte_offset]
                src2_byte = jamlet.rf_slice[self.src2 * wb + byte_offset]
                result_byte = ~(src1_byte & src2_byte) & 0xff
                jamlet.rf_slice[self.dst * wb + byte_offset] = result_byte
            new_word = jamlet.rf_slice[self.dst * wb:(self.dst + 1) * wb]
            logger.debug(
                f'{kamlet.clock.cycle}: RF_WRITE VmnandMmOp: jamlet ({jamlet.x},{jamlet.y}) '
                f'rf[{self.dst}] old={old_word.hex()} new={new_word.hex()}'
            )


@dataclass
class VBroadcastOp(LocalKInstr):
    """Broadcast a scalar value to all elements of a vector register.

    Used for vmv.v.i, vmv.v.x instructions.
    """
    dst: int
    scalar: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        dst_regs = [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(write_regs=dst_regs)

        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): VBroadcast dst=v{self.dst} scalar={self.scalar}')

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes

        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                dst_reg = self.dst + vline_index
                old_word = jamlet.rf_slice[dst_reg * wb:(dst_reg + 1) * wb]
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order, None,
                        vline_index, j_in_k_index, index_in_j
                    )

                    if valid_element:
                        result_bytes = self.scalar.to_bytes(eb, byteorder='little', signed=True)
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = result_bytes
                new_word = jamlet.rf_slice[dst_reg * wb:(dst_reg + 1) * wb]
                if old_word != new_word:
                    logger.debug(
                        f'{kamlet.clock.cycle}: RF_WRITE VBroadcastOp: jamlet ({jamlet.x},{jamlet.y}) '
                        f'rf[{dst_reg}] old={old_word.hex()} new={new_word.hex()}'
                    )


@dataclass
class VmvVvOp(LocalKInstr):
    dst: int
    src: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        src_regs = [self.src+index for index in range(n_vlines)]
        dst_regs = [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(read_regs=src_regs, write_regs=dst_regs)

        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): VmvVv dst=v{self.dst} src=v{self.src}')

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src_offset = self.src * vreg_bytes_per_jamlet
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes

        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                dst_reg = self.dst + vline_index
                old_word = jamlet.rf_slice[dst_reg * wb:(dst_reg + 1) * wb]
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order, None,
                        vline_index, j_in_k_index, index_in_j
                    )

                    if valid_element:
                        src_bytes = jamlet.rf_slice[src_offset + byte_offset:src_offset + byte_offset + eb]
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = src_bytes
                new_word = jamlet.rf_slice[dst_reg * wb:(dst_reg + 1) * wb]
                if old_word != new_word:
                    logger.debug(
                        f'{kamlet.clock.cycle}: RF_WRITE VmvVvOp: jamlet ({jamlet.x},{jamlet.y}) '
                        f'rf[{dst_reg}] old={old_word.hex()} new={new_word.hex()}'
                    )


@dataclass
class ReadRegElement(LocalKInstr):
    rd: int
    src: int
    element_index: int
    element_width: int
    ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_read_reg_element_instr(self)


@dataclass
class VArithVvOp(LocalKInstr):
    op: VArithOp
    dst: int
    src1: int
    src2: int
    mask_reg: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        regs = [self.src1+index for index in range(n_vlines)]
        regs += [self.src2+index for index in range(n_vlines)]
        regs += [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(regs)

        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): V{self.op.value}Vv dst=v{self.dst} src1=v{self.src1} src2=v{self.src2}')
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
                dst_reg = self.dst + vline_index
                old_word = jamlet.rf_slice[dst_reg * wb:(dst_reg + 1) * wb]
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
                new_word = jamlet.rf_slice[dst_reg * wb:(dst_reg + 1) * wb]
                if old_word != new_word:
                    logger.debug(
                        f'{kamlet.clock.cycle}: RF_WRITE VArithVvOp({self.op.value}): '
                        f'jamlet ({jamlet.x},{jamlet.y}) rf[{dst_reg}] '
                        f'old={old_word.hex()} new={new_word.hex()}'
                    )


@dataclass
class VArithVxOp(LocalKInstr):
    op: VArithOp
    dst: int
    scalar_bytes: bytes
    src2: int
    mask_reg: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    is_float: bool = False

    async def update_kamlet(self, kamlet):
        import struct
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        regs = [self.src2+index for index in range(n_vlines)]
        regs += [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(regs)

        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): V{self.op.value}Vx dst=v{self.dst} src2=v{self.src2} float={self.is_float}')
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
                    valid_element, mask_bit = kamlet.get_is_active(start_index, self.n_elements, self.element_width, self.word_order, self.mask_reg, vline_index, j_in_k_index, index_in_j)

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


@dataclass
class VreductionVsOp(LocalKInstr):
    op: VRedOp
    dst: int
    src_vector: int
    src_scalar_reg: int
    mask_reg: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder

    async def update_kamlet(self, kamlet):
        await kamlet.handle_vreduction_vs_instr(self)
