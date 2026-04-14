'''
Store KInstr class.

admit() collects src phys regs and sets up Renamed state, deciding
simple vs notsimple (ew_match and aligned) for later dispatch.
execute() creates either a WaitingStoreSimple or WaitingStoreJ2JWords
waiting item and registers it with the cache table.
'''
from dataclasses import dataclass
from typing import TYPE_CHECKING
import logging

from zamlet import addresses
from zamlet.addresses import KMAddr
from zamlet.kamlet.kinstructions import KInstr, Renamed
from zamlet.transactions import store_simple, store_j2j_words

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet


logger = logging.getLogger(__name__)


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

    async def admit(self, kamlet: 'Kamlet') -> 'Store | None':
        ew_match = self.src_ordering.ew == self.k_maddr.ordering.ew
        physical_vline_addr = self.k_maddr.to_physical_vline_addr()
        aligned = (physical_vline_addr.bit_addr
                   - self.start_index * self.k_maddr.ordering.ew) % (
                       kamlet.params.vline_bytes * 8) == 0
        simple = ew_match and aligned

        ew = self.src_ordering.ew
        elements_in_vline = kamlet.params.vline_bytes * 8 // ew
        start_vline = self.start_index // elements_in_vline
        end_vline = (self.start_index + self.n_elements - 1) // elements_in_vline

        src_pregs = {v: kamlet.r(self.src + v)
                     for v in range(start_vline, end_vline + 1)}
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        new = self.rename(
            cache_is_write=True,
            writeset_ident=self.writeset_ident,
            needs_witem=1,
            src_pregs=src_pregs,
            mask_preg=mask_preg,
        )
        new._simple = simple
        new._start_vline = start_vline
        logger.debug(
            f'kamlet ({kamlet.min_x}, {kamlet.min_y}): Store.admit '
            f'addr={hex(self.k_maddr.addr)} ident={self.instr_ident} simple={simple}')
        return new

    async def execute(self, kamlet: 'Kamlet') -> None:
        r = self.renamed
        rf_read_ident = kamlet.rf_info.start(
            read_regs=r.read_pregs, write_regs=r.write_pregs)
        if self._simple:
            # WaitingStoreSimple expects src_pregs as a list indexed by
            # vline_offset (relative to start_vline).
            start_vline = self._start_vline
            n_vlines = len(r.src_pregs)
            src_pregs_list = [r.src_pregs[start_vline + i] for i in range(n_vlines)]
            witem = store_simple.WaitingStoreSimple(
                instr=self, src_pregs=src_pregs_list,
                mask_preg=r.mask_preg, rf_ident=rf_read_ident)
            kamlet.monitor.record_witem_created(
                self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingStoreSimple',
                read_regs=r.read_pregs)
            kamlet.cache_table.add_witem_immediately(
                witem=witem, k_maddr=self.k_maddr)
        else:
            witem = store_j2j_words.WaitingStoreJ2JWords(
                params=kamlet.params, instr=self, rf_ident=rf_read_ident,
                src_pregs=r.src_pregs, mask_preg=r.mask_preg)
            kamlet.monitor.record_witem_created(
                self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingStoreJ2JWords',
                read_regs=r.read_pregs)
            kamlet.cache_table.add_witem_immediately(
                witem=witem, k_maddr=self.k_maddr)
            for jamlet in kamlet.jamlets:
                for tag in range(kamlet.params.word_bytes):
                    store_j2j_words.init_dst_state(jamlet, witem, tag)
                    store_j2j_words.init_src_state(jamlet, witem, tag)
