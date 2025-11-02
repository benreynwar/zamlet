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

import addresses
from addresses import KMAddr


logger = logging.getLogger(__name__)


class KInstr:
    pass


@dataclass
class WriteImmBytes(KInstr):
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
class ReadBytes(KInstr):
    """
    This instruction reads from the VPU memory.
    The scalar processor receives a response packet.
    """
    k_maddr: KMAddr
    size: int
    ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_read_bytes_instr(self)

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
class ZeroLines(KInstr):
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
class DiscardLines(KInstr):
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


@dataclass
class Load(KInstr):
    dst: int
    k_maddr: KMAddr  # An address in the kamlet address space
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    mask_reg: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_instr(self)

    #async def update_kamlet(self, kamlet):
    #    logger.debug(f'{kamlet.clock.cycle}: kamlet ({kamlet.min_x} {kamlet.min_y}): Load dst=v{self.dst}')
    #    params = kamlet.params
    #    bytes_per_jamlet = params.vline_bytes // params.j_in_l * self.n_vlines
    #    vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
    #    vreg_base_offset = self.dst * vreg_bytes_per_jamlet
    #    assert bytes_per_jamlet == vreg_bytes_per_jamlet * self.n_vlines
    #    sram_offset = self.j_saddr.addr
    #    for jamlet in kamlet.jamlets:
    #        jamlet.rf_slice[vreg_base_offset: vreg_base_offset + bytes_per_jamlet] = jamlet.sram[sram_offset: sram_offset + bytes_per_jamlet]


@dataclass
class Store(KInstr):
    src: int
    k_maddr: KMAddr  # An address in the kamlet address space
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    mask_reg: int

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
class VaddVxOp(KInstr):
    dst: int
    src: int
    scalar: int
    mask_reg: int
    n_elements: int
    element_width: int

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        regs = [self.src+index for index in range(n_vlines)]
        regs += [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(regs)
        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): VaddVx dst=v{self.dst} src=v{self.src} scalar={self.scalar}')
        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src_offset = self.src * vreg_bytes_per_jamlet
        dst_offset = self.dst * vreg_bytes_per_jamlet
        elem_bytes = self.element_width // 8

        assert self.mask_reg is None

        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        word_order = addresses.WordOrder.STANDARD

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(self.n_elements, self.element_width, word_order, self.mask_reg, vline_index, j_in_k_index, index_in_j)

                    if valid_element and mask_bit:
                        src_bytes = jamlet.rf_slice[src_offset + byte_offset:src_offset + byte_offset + elem_bytes]
                        src_val = int.from_bytes(src_bytes, byteorder='little', signed=True)
                        result = src_val + self.scalar
                        result_bytes = result.to_bytes(elem_bytes, byteorder='little', signed=True)
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + elem_bytes] = result_bytes


@dataclass
class VfmaccVfOp(KInstr):
    dst: int
    src: int
    scalar_bits: int
    mask_reg: int
    n_elements: int
    word_order: addresses.WordOrder
    element_width: int

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        regs = [self.src+index for index in range(n_vlines)]
        regs += [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(regs)
        import struct
        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): VfmaccVf dst=v{self.dst} src=v{self.src}')
        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src_offset = self.src * vreg_bytes_per_jamlet
        dst_offset = self.dst * vreg_bytes_per_jamlet
        elem_bytes = self.element_width // 8

        assert self.mask_reg is None

        if self.element_width == 64:
            scalar_val = struct.unpack('d', struct.pack('Q', self.scalar_bits))[0]
        else:
            scalar_val = struct.unpack('f', struct.pack('I', self.scalar_bits & 0xffffffff))[0]

        src_elements = []
        old_elements = []
        result_elements = []

        if self.element_width == 64:
            fmt_code = 'd'
        else:
            fmt_code = 'f'

        eb = self.element_width//8
        wb = kamlet.params.word_bytes

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                for index_in_j in range(wb//eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(self.n_elements, self.element_width, self.word_order, self.mask_reg, vline_index, j_in_k_index, index_in_j)

                    src_bytes = jamlet.rf_slice[src_offset + byte_offset:src_offset + byte_offset + elem_bytes]
                    src_val = struct.unpack(fmt_code, src_bytes)[0]
                    #src_elements.append(src_val)

                    dst_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + elem_bytes]
                    acc_val = struct.unpack(fmt_code, dst_bytes)[0]
                    #old_elements.append(acc_val)

                    result = acc_val + (scalar_val * src_val)
                    #result_elements.append(result)
                    result_bytes = struct.pack(fmt_code, result)

                    if valid_element and mask_bit:
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + elem_bytes] = result_bytes

        #if kamlet.min_x == 0 and kamlet.min_y == 0:
        #    logger.debug(f'VfmaccVfOp scalar {scalar_val} src {src_elements} old {old_elements} -> dst {result_elements}')
        #logger.debug(f'VfmaccVfOp scalar {scalar_val} src {src_elements} old {old_elements} -> dst {result_elements}')


@dataclass
class VmsleViOp(KInstr):
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

        await kamlet.wait_for_rf_available(src_regs+dst_regs)
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
                result_bit = 1 if src_val <= sign_extended_imm else 0
                src_values.append(src_val)
                results.append(result_bit)
                dst_bit_addr = base_dst_bit_addr + element_in_jamlet
                dst_byte_addr = dst_bit_addr//8
                dst_bit_offset = dst_bit_addr % 8
                if result_bit:
                    jamlet.rf_slice[dst_byte_addr] |= (1 << dst_bit_offset)
                else:
                    jamlet.rf_slice[dst_byte_addr] &= ~(1 << dst_bit_offset)
        logger.info(f'kamlet: VmsleViOp: srcs = {src_values}, results = {results}')


@dataclass
class VmnandMmOp(KInstr):
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
            old_bytes = []
            new_bytes = []
            for byte_offset in range(wb):
                src1_byte = jamlet.rf_slice[self.src1 * wb + byte_offset]
                src2_byte = jamlet.rf_slice[self.src2 * wb + byte_offset]
                old_bytes.append(src1_byte)
                result_byte = ~(src1_byte & src2_byte) & 0xff
                new_bytes.append(result_byte)
                jamlet.rf_slice[self.dst * wb + byte_offset] = result_byte
            logger.info(f'kamlet ({kamlet.min_x} {kamlet.min_y}) jamlet {j_idx}: VmnandMm old_bytes={old_bytes} new_bytes={new_bytes}')
