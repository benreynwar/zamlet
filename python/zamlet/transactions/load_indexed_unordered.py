'''
Unordered indexed (gather) load (vluxei): element i is loaded from address (base + index_vector[i]).

The index register contains byte offsets with element width index_ew.
The data element width comes from SEW (dst_ordering.ew).

All elements are loaded in parallel with no ordering guarantees.
'''

from typing import List, TYPE_CHECKING
from dataclasses import dataclass
import logging

from zamlet import addresses
from zamlet.kamlet.kinstructions import KInstr
from zamlet.transactions.load_gather_base import WaitingLoadGatherBase

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet


logger = logging.getLogger(__name__)


@dataclass
class LoadIndexedUnordered(KInstr):
    """
    An indexed load from memory into a vector register.

    Each element i is loaded from address (g_addr + index_reg[i]).
    The index register contains byte offsets.

    n_elements is limited to j_in_l (same as LoadStride).
    """
    dst: int
    g_addr: addresses.GlobalAddress
    index_reg: int
    index_ordering: addresses.Ordering
    start_index: int
    n_elements: int
    dst_ordering: addresses.Ordering
    mask_reg: int | None
    writeset_ident: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): load_indexed.update_kamlet '
                     f'addr={hex(self.g_addr.addr)} ident={self.instr_ident}')
        dst_regs = kamlet.get_regs(
            start_index=self.start_index, n_elements=self.n_elements,
            ew=self.dst_ordering.ew, base_reg=self.dst)
        index_regs = kamlet.get_regs(
            start_index=self.start_index, n_elements=self.n_elements,
            ew=self.index_ordering.ew, base_reg=self.index_reg)
        overlap = set(dst_regs) & set(index_regs)
        assert not overlap, \
            f"dst_regs {dst_regs} overlaps with index_regs {index_regs}: {overlap}"
        read_regs = list(index_regs)
        if self.mask_reg is not None:
            read_regs.append(self.mask_reg)
            assert self.mask_reg not in dst_regs, \
                f"mask_reg {self.mask_reg} overlaps with dst_regs {dst_regs}"
        await kamlet.wait_for_rf_available(write_regs=dst_regs, read_regs=read_regs,
                                           instr_ident=self.instr_ident)
        rf_write_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=dst_regs)
        witem = WaitingLoadIndexedUnordered(
            params=kamlet.params, instr=self, rf_ident=rf_write_ident)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingLoadIndexedUnordered')
        await kamlet.cache_table.add_witem(witem=witem)


class WaitingLoadIndexedUnordered(WaitingLoadGatherBase):
    """Waiting item for unordered indexed loads."""

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
