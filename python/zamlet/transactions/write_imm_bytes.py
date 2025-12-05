'''
Write Immediate Bytes Transaction

Handles immediate byte writes to cache memory. This is used during initialization
to write data directly to the VPU memory without going through the register file.

Flow:
1. Kamlet receives WriteImmBytes instruction
2. Check if cache line is ready for writing (can_write)
3. If yes, write bytes directly to SRAM
4. If no, create WaitingWriteImmBytes, wait for cache line
5. When cache ready, write bytes to SRAM and mark cache line as MODIFIED
'''
from typing import TYPE_CHECKING
import logging

from zamlet.waiting_item import WaitingItemRequiresCache
from zamlet.kamlet import kinstructions

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.kamlet.cache_table import CacheState

logger = logging.getLogger(__name__)


class WaitingWriteImmBytes(WaitingItemRequiresCache):

    cache_is_write = True

    def __init__(self, instr: kinstructions.WriteImmBytes):
        super().__init__(item=instr, instr_ident=instr.instr_ident)

    def ready(self) -> bool:
        return self.cache_is_avail

    async def finalize(self, kamlet: 'Kamlet') -> None:
        instr = self.item
        assert isinstance(instr, kinstructions.WriteImmBytes)
        do_write_imm_bytes(kamlet, instr)


def do_write_imm_bytes(kamlet: 'Kamlet', instr: kinstructions.WriteImmBytes) -> None:
    """
    Write immediate bytes to cache.

    The bytes must all be within one word.
    """
    from zamlet.kamlet import cache_table

    assert instr.k_maddr.bit_addr % 8 == 0
    if instr.k_maddr.k_index == kamlet.k_index:
        assert kamlet.cache_table.can_write(instr.k_maddr)
        j_saddr = instr.k_maddr.to_j_saddr(kamlet.cache_table)
        jamlet = kamlet.jamlets[j_saddr.j_in_k_index]
        size = len(instr.imm)
        jamlet.sram[j_saddr.addr: j_saddr.addr + size] = instr.imm
        cache_state = kamlet.cache_table.get_state(instr.k_maddr)
        cache_state.state = cache_table.CacheState.MODIFIED
    kamlet.monitor.complete_kinstr_exec(instr.instr_ident, kamlet.min_x, kamlet.min_y)
