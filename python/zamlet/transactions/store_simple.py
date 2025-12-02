'''
Store Simple Transaction

Handles aligned vector stores where data is copied directly from register file to cache
within a single kamlet. No J2J messaging required - this is the fast path for aligned stores.

Flow:
1. Kamlet receives Store instruction
2. Check if cache line is available for writing (can_write)
3. If yes, copy directly from register file to cache
4. If no, create WaitingStoreSimple, request cache line from memory
5. When cache ready, copy from register file to cache
'''
from typing import TYPE_CHECKING
import logging

from zamlet import utils
from zamlet.waiting_item import WaitingItemRequiresCache
from zamlet.kamlet import kinstructions
from zamlet.kamlet.cache_table import CacheState
from zamlet.transactions.helpers import get_offsets_and_masks

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


class WaitingStoreSimple(WaitingItemRequiresCache):

    cache_is_write = True

    def __init__(self, instr: kinstructions.Store, rf_ident: int | None = None):
        super().__init__(
            item=instr, writeset_ident=instr.writeset_ident, rf_ident=rf_ident)

    def ready(self) -> bool:
        return self.cache_is_avail

    async def finalize(self, kamlet: 'Kamlet') -> None:
        instr = self.item
        assert isinstance(instr, kinstructions.Store)
        assert kamlet.cache_table.can_write(instr.k_maddr)

        for jamlet in kamlet.jamlets:
            do_store_simple(jamlet, instr)

        cache_state = kamlet.cache_table.get_state(instr.k_maddr)
        cache_state.state = CacheState.MODIFIED

        src_regs = kamlet.get_regs(
            start_index=instr.start_index, n_elements=instr.n_elements,
            ew=instr.src_ordering.ew, base_reg=instr.src)
        read_regs = src_regs + ([instr.mask_reg] if instr.mask_reg is not None else [])

        assert self.rf_ident is not None
        kamlet.rf_info.finish(self.rf_ident, read_regs=read_regs)


def do_store_simple(jamlet: 'Jamlet', instr: kinstructions.Store) -> None:
    """
    Copy data from register file to cache for an aligned store.

    This is called when the store is aligned to local kamlet memory
    and the cache line is available for writing.
    """
    assert jamlet.cache_table.can_write(instr.k_maddr)
    slot = jamlet.cache_table.addr_to_slot(instr.k_maddr)

    dst_ordering = instr.k_maddr.ordering
    src_ordering = instr.src_ordering
    assert dst_ordering == src_ordering

    vline_offsets_and_masks = get_offsets_and_masks(
        jamlet, instr.start_index, instr.n_elements, instr.src_ordering, instr.mask_reg)

    params = jamlet.params
    word_bytes = params.word_bytes
    vline_bytes_per_kamlet = params.word_bytes * params.j_in_k
    base_vline = (instr.k_maddr.addr % params.cache_line_bytes) // vline_bytes_per_kamlet
    cache_line_bytes_per_jamlet = params.cache_line_bytes // params.j_in_k
    elements_in_vline = params.vline_bytes * 8 // instr.src_ordering.ew
    first_vline = instr.start_index // elements_in_vline

    for vline_offset, mask in vline_offsets_and_masks:
        rf_word_addr = instr.src + first_vline + vline_offset
        sram_addr = slot * cache_line_bytes_per_jamlet + (base_vline + vline_offset) * word_bytes
        new_word = jamlet.rf_slice[rf_word_addr * word_bytes: (rf_word_addr + 1) * word_bytes]
        old_word = jamlet.sram[sram_addr: sram_addr + word_bytes]
        updated_word = utils.update_bytes_word(old_word=old_word, new_word=new_word, mask=mask)
        jamlet.sram[sram_addr: sram_addr + word_bytes] = updated_word
        logger.debug(
            f'{jamlet.clock.cycle}: CACHE_WRITE STORE_SIMPLE: jamlet ({jamlet.x},{jamlet.y}) '
            f'sram[{sram_addr}] old={old_word.hex()} new={updated_word.hex()} '
            f'from rf[{rf_word_addr}] mask=0x{mask:016x}')
