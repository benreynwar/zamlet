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
    n_vlines: int

    async def update_kamlet(self, kamlet):
        regs = [self.dst+index for index in range(self.n_vlines)]
        await kamlet.wait_for_rf_available(regs)
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
    n_vlines: int

    async def update_kamlet(self, kamlet):
        regs = [self.src+index for index in range(self.n_vlines)]
        await kamlet.wait_for_rf_available(regs)
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
    n_vlines: int

    async def update_kamlet(self, kamlet):
        regs = [self.src+index for index in range(self.n_vlines)]
        regs += [self.dst+index for index in range(self.n_vlines)]
        await kamlet.wait_for_rf_available(regs)
        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): VaddVx dst=v{self.dst} src=v{self.src} scalar={self.scalar}')
        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src_offset = self.src * vreg_bytes_per_jamlet
        dst_offset = self.dst * vreg_bytes_per_jamlet
        elem_bytes = 4

        assert self.mask_reg is None

        src_elements = []
        for byte_offset in range(0, self.n_vlines*vreg_bytes_per_jamlet, elem_bytes):
            for jamlet in kamlet.jamlets:
                src_bytes = jamlet.rf_slice[src_offset + byte_offset:src_offset + byte_offset + elem_bytes]
                src_val = int.from_bytes(src_bytes, byteorder='little', signed=True)
                src_elements.append(src_val)
        dst_elements = [src_val + self.scalar for src_val in src_elements]
        logger.debug(f'src {src_elements} -> dst {dst_elements}')

        for byte_offset in range(0, self.n_vlines*vreg_bytes_per_jamlet, elem_bytes):
            for jamlet in kamlet.jamlets:
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
    n_vlines: int
    element_width: int

    async def update_kamlet(self, kamlet):
        regs = [self.src+index for index in range(self.n_vlines)]
        regs += [self.dst+index for index in range(self.n_vlines)]
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

        for byte_offset in range(0, vreg_bytes_per_jamlet*self.n_vlines, elem_bytes):
            for jamlet in kamlet.jamlets:
                src_bytes = jamlet.rf_slice[src_offset + byte_offset:src_offset + byte_offset + elem_bytes]
                src_val = struct.unpack(fmt_code, src_bytes)[0]
                src_elements.append(src_val)

                dst_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + elem_bytes]
                acc_val = struct.unpack(fmt_code, dst_bytes)[0]
                old_elements.append(acc_val)

                result = acc_val + (scalar_val * src_val)
                result_elements.append(result)
                result_bytes = struct.pack(fmt_code, result)
                jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + elem_bytes] = result_bytes

        if kamlet.min_x == 0 and kamlet.min_y == 0:
            logger.debug(f'VfmaccVfOp scalar {scalar_val} src {src_elements} old {old_elements} -> dst {result_elements}')
        logger.debug(f'VfmaccVfOp scalar {scalar_val} src {src_elements} old {old_elements} -> dst {result_elements}')

