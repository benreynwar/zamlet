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

from addresses import JSAddr

logger = logging.getLogger(__name__)


@dataclass
class WriteImmByteToSRAM:
    j_saddr: JSAddr
    imm: int

    def update_kamlet(self, kamlet):
        assert 0 <= self.imm < (1 << 8)
        assert self.j_saddr.bit_addr % 8 == 0
        jamlet = kamlet.jamlets[j_saddr.j_in_k_index]
        jamlet.sram[self.j_addr.addr] = self.imm


@dataclass
class ReadByteFromSRAM:
    j_saddr: JSAddr


@dataclass
class ReadLine:
    k_memory_address: int  # An address in the kamlet memory space
    k_sram_address: int    # An address in the kamlet sram space
    n_cache_lines: int   # The number of cache lines to read.


@dataclass
class WriteLine:
    k_memory_address: int  # An address in the kamlet memory space
    k_sram_address: int    # An address in the kamlet sram space
    n_cache_lines: int   # The number of cache lines to read.

@dataclass
class Load:
    dst: int
    j_sram_address: int  # An address in the jamlet sram space
    n_vlines: int   # The number of address from each jamlet sram to load
    
