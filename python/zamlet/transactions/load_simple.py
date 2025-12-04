'''
Load Simple Transaction

Handles aligned vector loads where data is copied directly from cache to register file
within a single kamlet. No J2J messaging required - this is the fast path for aligned loads.

Flow:
1. Kamlet receives Load instruction
2. Check if data is in cache (can_read)
3. If yes, copy directly from cache to register file
4. If no, create WaitingLoadSimple, request cache line from memory
5. When cache ready, copy from cache to register file
'''
from typing import TYPE_CHECKING
import logging

from zamlet import utils
from zamlet.waiting_item import WaitingItemRequiresCache
from zamlet.kamlet import kinstructions
from zamlet.transactions.helpers import get_offsets_and_masks

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


class WaitingLoadSimple(WaitingItemRequiresCache):

    cache_is_read = True

    def __init__(self, instr: kinstructions.Load, rf_ident: int | None = None):
        super().__init__(
            item=instr, writeset_ident=instr.writeset_ident, rf_ident=rf_ident)

    def ready(self) -> bool:
        return self.cache_is_avail

    async def finalize(self, kamlet: 'Kamlet') -> None:
        instr = self.item
        assert isinstance(instr, kinstructions.Load)
        if not kamlet.cache_table.can_read(instr.k_maddr):
            logger.error(
                f'{kamlet.clock.cycle}: kamlet ({kamlet.min_x},{kamlet.min_y}): LOAD_SIMPLE '
                f'FINALIZE FAILED instr_ident={instr.instr_ident} '
                f'k_maddr.addr=0x{instr.k_maddr.addr:x} cache_slot={self.cache_slot} '
                f'writeset_ident={self.writeset_ident}'
            )
            assert False, f'can_read failed for instr_ident={instr.instr_ident}'

        logger.debug(
            f'{kamlet.clock.cycle}: kamlet ({kamlet.min_x},{kamlet.min_y}): LOAD_SIMPLE '
            f'instr_ident={instr.instr_ident} dst=v{instr.dst} '
            f'mask_reg={instr.mask_reg} rf_ident={self.rf_ident}')

        for jamlet in kamlet.jamlets:
            do_load_simple(jamlet, instr)

        dst_regs = kamlet.get_regs(
            start_index=instr.start_index, n_elements=instr.n_elements,
            ew=instr.dst_ordering.ew, base_reg=instr.dst)
        read_regs = [instr.mask_reg] if instr.mask_reg is not None else []

        logger.debug(
            f'>>>>>>>>>>> {kamlet.clock.cycle}: kamlet ({kamlet.min_x},{kamlet.min_y}): '
            f'LOAD_SIMPLE FINISH instr_ident={instr.instr_ident} '
            f'dst_regs={dst_regs} read_regs={read_regs}')

        assert self.rf_ident is not None
        kamlet.rf_info.finish(self.rf_ident, write_regs=dst_regs, read_regs=read_regs)


def do_load_simple(jamlet: 'Jamlet', instr: kinstructions.Load) -> None:
    """
    Copy data from cache to register file for an aligned load.

    This is called when the load is aligned to local kamlet memory
    and the data is already in the cache.
    """
    assert jamlet.cache_table.can_read(instr.k_maddr)
    slot = jamlet.cache_table.addr_to_slot(instr.k_maddr)

    dst_ordering = instr.dst_ordering
    src_ordering = instr.k_maddr.ordering
    assert dst_ordering == src_ordering

    vline_offsets_and_masks = get_offsets_and_masks(
        jamlet, instr.start_index, instr.n_elements, instr.dst_ordering, instr.mask_reg)

    params = jamlet.params
    vline_bytes_per_kamlet = params.word_bytes * params.j_in_k
    base_vline = (instr.k_maddr.addr % params.cache_line_bytes) // vline_bytes_per_kamlet
    cache_line_bytes_per_jamlet = params.cache_line_bytes // params.j_in_k
    word_bytes = params.word_bytes
    elements_in_vline = params.vline_bytes * 8 // instr.dst_ordering.ew
    first_vline = instr.start_index // elements_in_vline

    for vline_offset, mask in vline_offsets_and_masks:
        rf_word_addr = instr.dst + first_vline + vline_offset
        assert vline_offset * word_bytes < cache_line_bytes_per_jamlet - (word_bytes - 1)
        sram_addr = slot * cache_line_bytes_per_jamlet + (base_vline + vline_offset) * word_bytes
        new_word = jamlet.sram[sram_addr: sram_addr + word_bytes]
        old_word = jamlet.rf_slice[rf_word_addr * word_bytes: (rf_word_addr + 1) * word_bytes]
        updated_word = utils.update_bytes_word(old_word=old_word, new_word=new_word, mask=mask)
        jamlet.rf_slice[rf_word_addr * word_bytes: (rf_word_addr + 1) * word_bytes] = updated_word
        logger.debug(
            f'{jamlet.clock.cycle}: RF_WRITE LOAD_SIMPLE: jamlet ({jamlet.x},{jamlet.y}) '
            f'rf[{rf_word_addr}] old={old_word.hex()} new={updated_word.hex()} '
            f'instr_ident={instr.instr_ident} mask=0x{mask:016x}')
