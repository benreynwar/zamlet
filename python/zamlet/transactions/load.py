'''
Load KInstr class.

admit() allocates dst phys regs and sets up Renamed state, deciding
simple vs notsimple (ew_match and aligned) for later dispatch.
execute() creates either a WaitingLoadSimple or WaitingLoadJ2JWords
waiting item and registers it with the cache table.
'''
from dataclasses import dataclass
from typing import TYPE_CHECKING
import logging

from zamlet import addresses
from zamlet.addresses import KMAddr
from zamlet.kamlet.kinstructions import KInstr, Renamed
from zamlet.transactions import load_simple, load_j2j_words

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet


logger = logging.getLogger(__name__)


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
    mask_reg: int | None
    writeset_ident: int
    instr_ident: int
    stride_bytes: int | None = None

    async def admit(self, kamlet: 'Kamlet') -> 'Load | None':
        ew_match = self.dst_ordering.ew == self.k_maddr.ordering.ew
        physical_vline_addr = self.k_maddr.to_physical_vline_addr()
        aligned = (physical_vline_addr.bit_addr
                   - self.start_index * self.k_maddr.ordering.ew) % (
                       kamlet.params.vline_bytes * 8) == 0
        simple = ew_match and aligned

        ew = self.dst_ordering.ew
        elements_in_vline = kamlet.params.vline_bytes * 8 // ew
        start_vline = self.start_index // elements_in_vline
        end_vline = (self.start_index + self.n_elements - 1) // elements_in_vline

        # Resolve mask phys BEFORE allocating dst phys so an arch overlap
        # (mask_reg == dst arch) resolves to the old phys.
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        exclude = {mask_preg} if mask_preg is not None else set()
        dst_preg_list = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=start_vline, end_vline=end_vline,
            start_index=self.start_index, n_elements=self.n_elements,
            elements_in_vline=elements_in_vline,
            mask_present=self.mask_reg is not None,
            exclude_reuse=exclude)
        dst_pregs = {start_vline + i: dst_preg_list[i]
                     for i in range(len(dst_preg_list))}
        new = self.rename(
            cache_is_read=True,
            writeset_ident=self.writeset_ident,
            needs_witem=1,
            dst_pregs=dst_pregs,
            mask_preg=mask_preg,
        )
        new._simple = simple
        new._start_vline = start_vline
        logger.debug(
            f'kamlet ({kamlet.min_x}, {kamlet.min_y}): Load.admit '
            f'addr={hex(self.k_maddr.addr)} ident={self.instr_ident} simple={simple}')
        return new

    async def execute(self, kamlet: 'Kamlet') -> None:
        r = self.renamed
        rf_write_ident = kamlet.rf_info.start(
            read_regs=r.read_pregs, write_regs=r.write_pregs)
        if self._simple:
            # WaitingLoadSimple expects dst_pregs as a list indexed by
            # vline_offset (relative to start_vline).
            start_vline = self._start_vline
            n_vlines = len(r.dst_pregs)
            dst_pregs_list = [r.dst_pregs[start_vline + i] for i in range(n_vlines)]
            witem = load_simple.WaitingLoadSimple(
                instr=self, dst_pregs=dst_pregs_list,
                mask_preg=r.mask_preg, rf_ident=rf_write_ident)
            kamlet.monitor.record_witem_created(
                self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingLoadSimple',
                read_regs=r.read_pregs, write_regs=r.write_pregs)
            kamlet.cache_table.add_witem_immediately(
                witem=witem, k_maddr=self.k_maddr)
        else:
            witem = load_j2j_words.WaitingLoadJ2JWords(
                params=kamlet.params, instr=self, rf_ident=rf_write_ident,
                dst_pregs=r.dst_pregs, mask_preg=r.mask_preg)
            kamlet.monitor.record_witem_created(
                self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingLoadJ2JWords',
                read_regs=r.read_pregs, write_regs=r.write_pregs)
            kamlet.cache_table.add_witem_immediately(
                witem=witem, k_maddr=self.k_maddr)
            for jamlet in kamlet.jamlets:
                for tag in range(kamlet.params.word_bytes):
                    load_j2j_words.init_dst_state(jamlet, witem, tag)
                    load_j2j_words.init_src_state(jamlet, witem, tag)
