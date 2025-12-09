'''
Indexed (scatter) store: element i is stored to address (base + index_vector[i]).

The index register contains byte offsets with element width index_ew.
The data element width comes from SEW (src_ordering.ew).
'''

from typing import List, TYPE_CHECKING
from dataclasses import dataclass
import logging

from zamlet import addresses
from zamlet.kamlet.kinstructions import KInstr
from zamlet.transactions.store_scatter_base import WaitingStoreScatterBase

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet


logger = logging.getLogger(__name__)


@dataclass
class StoreIndexedUnordered(KInstr):
    """
    An unordered indexed store from a vector register to VPU memory.

    Each element i is stored to address (g_addr + index_reg[i]).
    The index register contains byte offsets.

    n_elements is limited to j_in_l (same as StoreStride).
    """
    src: int
    g_addr: addresses.GlobalAddress
    index_reg: int
    index_ordering: addresses.Ordering
    start_index: int
    n_elements: int
    src_ordering: addresses.Ordering
    mask_reg: int | None
    writeset_ident: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): store_indexed.update_kamlet '
                     f'addr={hex(self.g_addr.addr)} ident={self.instr_ident}')
        src_regs = kamlet.get_regs(
            start_index=self.start_index, n_elements=self.n_elements,
            ew=self.src_ordering.ew, base_reg=self.src)
        index_regs = kamlet.get_regs(
            start_index=self.start_index, n_elements=self.n_elements,
            ew=self.index_ordering.ew, base_reg=self.index_reg)
        read_regs = list(src_regs) + list(index_regs)
        if self.mask_reg is not None:
            read_regs.append(self.mask_reg)
        await kamlet.wait_for_rf_available(write_regs=[], read_regs=read_regs,
                                           instr_ident=self.instr_ident)
        rf_read_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=[])
        witem = WaitingStoreIndexedUnordered(
            params=kamlet.params, instr=self, rf_ident=rf_read_ident)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingStoreIndexedUnordered')
        await kamlet.cache_table.add_witem(witem=witem)


class WaitingStoreIndexedUnordered(WaitingStoreScatterBase):
    """Waiting item for unordered indexed stores."""

    def get_element_byte_offset(self, jamlet: 'Jamlet', element_index: int) -> int:
        """Read the byte offset from the index register for this element."""
        instr = self.item
        wb = jamlet.params.word_bytes
        index_ew = instr.index_ordering.ew
        index_bytes = index_ew // 8

        elements_in_vline = jamlet.params.vline_bytes * 8 // index_ew
        index_v = element_index // elements_in_vline
        index_ve = element_index % elements_in_vline
        index_we = index_ve // jamlet.params.j_in_l

        index_reg = instr.index_reg + index_v
        byte_in_word = (index_we * index_bytes) % wb

        word_data = jamlet.rf_slice[index_reg * wb: (index_reg + 1) * wb]
        index_value = int.from_bytes(word_data[byte_in_word:byte_in_word + index_bytes],
                                     byteorder='little', signed=False)
        return index_value

    def get_additional_read_regs(self, kamlet) -> List[int]:
        """Return the index registers that need to be read."""
        instr = self.item
        index_regs = kamlet.get_regs(
            start_index=instr.start_index, n_elements=instr.n_elements,
            ew=instr.index_ordering.ew, base_reg=instr.index_reg)
        return list(index_regs)
