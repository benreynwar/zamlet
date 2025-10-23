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

'''
Instructions for sending to a kamlet
'''

import logging
from dataclasses import dataclass

from addresses import JSAddr, KMAddr

logger = logging.getLogger(__name__)


class KInstr:
    pass


@dataclass
class WriteImmByteToSRAM(KInstr):
    j_saddr: JSAddr
    imm: int

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): WriteImmByteToSRAM')
        assert 0 <= self.imm < (1 << 8)
        assert self.j_saddr.bit_addr % 8 == 0
        jamlet = kamlet.jamlets[self.j_saddr.j_in_k_index]
        jamlet.sram[self.j_saddr.addr] = self.imm


@dataclass
class ReadByteFromSRAM(KInstr):
    j_saddr: JSAddr
    target_x: int
    target_y: int

    async def update_kamlet(self, kamlet):
        assert self.j_saddr.bit_addr % 8 == 0
        if self.j_saddr.k_index == kamlet.k_index:
            jamlet = kamlet.jamlets[self.j_saddr.j_in_k_index]
            await jamlet.read_byte_from_sram(self)
            logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): ReadByteFromSRAM - here ({kamlet.k_index})')
        else:
            logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): ReadByteFromSRAM - not here ({kamlet.k_index})')


@dataclass
class ReadLine(KInstr):
    k_maddr: KMAddr  # An address in the kamlet memory space
    j_saddr: JSAddr    # An address in the kamlet sram space
    n_cache_lines: int   # The number of cache lines to read.

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): ReadLine')
        for jamlet in kamlet.jamlets:
            await jamlet.read_line(self.k_maddr, self.j_saddr, self.n_cache_lines)

@dataclass
class ZeroLine(KInstr):
    j_saddr: JSAddr    # An address in the kamlet sram space
    n_cache_lines: int   # The number of cache lines to read.

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): ZeroLine')
        params = kamlet.params
        n_bytes = self.n_cache_lines * params.cache_line_bytes // params.j_in_k
        for jamlet in kamlet.jamlets:
            for index in range(n_bytes):
                jamlet.sram[self.j_saddr.addr+index] = 0


@dataclass
class WriteLine(KInstr):
    k_maddr: KMAddr  # An address in the kamlet memory space
    j_saddr: JSAddr    # An address in the kamlet sram space
    n_cache_lines: int   # The number of cache lines to read.

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x} {kamlet.min_y}): WriteLine')
        for jamlet in kamlet.jamlets:
            await jamlet.write_line(self.k_maddr, self.j_saddr, self.n_cache_lines)


@dataclass
class Load(KInstr):
    dst: int
    j_saddr: JSAddr  # An address in the jamlet sram space
    n_vlines: int   # The number of address from each jamlet sram to load
    
