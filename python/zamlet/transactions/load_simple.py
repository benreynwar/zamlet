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
from zamlet.transactions.helpers import get_offsets_and_masks

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.jamlet.jamlet import Jamlet
    from zamlet.transactions.load import Load

logger = logging.getLogger(__name__)


class WaitingLoadSimple(WaitingItemRequiresCache):

    cache_is_read = True

    def __init__(self, instr: 'Load', dst_pregs: list[int],
                 mask_preg: int | None, rf_ident: int | None = None):
        super().__init__(
            item=instr, instr_ident=instr.instr_ident,
            writeset_ident=instr.writeset_ident, rf_ident=rf_ident)
        # Phys regs locked at start time, indexed by vline_offset (the offset
        # from the start_vline of the operation). The kamlet's rename table
        # may rotate the dst arch by the time finalize runs.
        self.dst_pregs = dst_pregs
        self.mask_preg = mask_preg

    def ready(self) -> bool:
        return self.cache_is_avail

    async def finalize(self, kamlet: 'Kamlet') -> None:
        instr = self.item
        if not kamlet.cache_table.can_read(instr.k_maddr, writeset_ident=self.writeset_ident):
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
            f'dst_pregs={self.dst_pregs} mask_preg={self.mask_preg} '
            f'rf_ident={self.rf_ident}')

        for jamlet in kamlet.jamlets:
            do_load_simple(jamlet, instr, self.dst_pregs, self.mask_preg)

        read_regs = [self.mask_preg] if self.mask_preg is not None else []

        logger.debug(
            f'>>>>>>>>>>> {kamlet.clock.cycle}: kamlet ({kamlet.min_x},{kamlet.min_y}): '
            f'LOAD_SIMPLE FINISH instr_ident={instr.instr_ident} '
            f'dst_pregs={self.dst_pregs} read_regs={read_regs}')

        assert self.rf_ident is not None
        kamlet.rf_info.finish(
            self.rf_ident, write_regs=self.dst_pregs, read_regs=read_regs)


def do_load_simple(jamlet: 'Jamlet', instr: 'Load',
                   dst_pregs: list[int], mask_preg: int | None) -> None:
    """
    Copy data from cache to register file for an aligned load.

    This is called when the load is aligned to local kamlet memory
    and the data is already in the cache.

    dst_pregs is indexed by vline_offset (relative to first_vline).
    """
    assert jamlet.cache_table.can_read(instr.k_maddr, writeset_ident=instr.writeset_ident)
    slot = jamlet.cache_table.addr_to_slot(instr.k_maddr)

    dst_ordering = instr.dst_ordering
    src_ordering = instr.k_maddr.ordering
    assert dst_ordering == src_ordering

    vline_offsets_and_masks = get_offsets_and_masks(
        jamlet, instr.start_index, instr.n_elements, instr.dst_ordering, mask_preg)

    params = jamlet.params
    vline_bytes_per_kamlet = params.word_bytes * params.j_in_k
    base_vline = (instr.k_maddr.addr % params.cache_line_bytes) // vline_bytes_per_kamlet
    cache_line_bytes_per_jamlet = params.cache_line_bytes // params.j_in_k
    word_bytes = params.word_bytes

    witem_span_id = jamlet.monitor.get_witem_span_id(
        instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
    for vline_offset, mask in vline_offsets_and_masks:
        rf_word_addr = dst_pregs[vline_offset]
        assert vline_offset * word_bytes < cache_line_bytes_per_jamlet - (word_bytes - 1)
        sram_addr = slot * cache_line_bytes_per_jamlet + (base_vline + vline_offset) * word_bytes
        new_word = jamlet.sram[sram_addr: sram_addr + word_bytes]
        old_word = jamlet.rf_slice[rf_word_addr * word_bytes: (rf_word_addr + 1) * word_bytes]
        updated_word = utils.update_bytes_word(old_word=old_word, new_word=new_word, mask=mask)
        jamlet.write_vreg(
            rf_word_addr, 0, updated_word,
            span_id=witem_span_id,
            event_details={'mask': f'0x{mask:016x}', 'vline_offset': vline_offset},
        )
        logger.debug(
            f'{jamlet.clock.cycle}: RF_WRITE LOAD_SIMPLE: jamlet ({jamlet.x},{jamlet.y}) '
            f'rf[{rf_word_addr}] old={old_word.hex()} new={updated_word.hex()} '
            f'instr_ident={instr.instr_ident} mask=0x{mask:016x}')
