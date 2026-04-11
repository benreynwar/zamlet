'''
Unordered indexed (scatter) store (vsuxei): element i is stored to address (base + index_vector[i]).

The index register contains byte offsets with element width index_ew.
The data element width comes from SEW (src_ordering.ew).

All elements are stored in parallel with no ordering guarantees.
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
    index_offset: int = 0

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): store_indexed.update_kamlet '
                     f'addr={hex(self.g_addr.addr)} ident={self.instr_ident}')
        src_ew = self.src_ordering.ew
        src_elements_in_vline = kamlet.params.vline_bytes * 8 // src_ew
        src_start_vline = self.start_index // src_elements_in_vline
        src_end_vline = (self.start_index + self.n_elements - 1) // src_elements_in_vline

        index_ew = self.index_ordering.ew
        index_elements_in_vline = kamlet.params.vline_bytes * 8 // index_ew
        index_start_vline = (self.start_index + self.index_offset) // index_elements_in_vline
        index_end_vline = (
            self.start_index + self.index_offset + self.n_elements - 1
        ) // index_elements_in_vline

        src_pregs = {
            v: kamlet.r(self.src + v) for v in range(src_start_vline, src_end_vline + 1)
        }
        index_pregs = {
            v: kamlet.r(self.index_reg + v)
            for v in range(index_start_vline, index_end_vline + 1)
        }
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None

        read_regs = list(src_pregs.values()) + list(index_pregs.values())
        if mask_preg is not None:
            read_regs.append(mask_preg)
        await kamlet.wait_for_rf_available(write_regs=[], read_regs=read_regs,
                                           instr_ident=self.instr_ident)
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)
        kamlet.monitor.add_event(span_id, "rf_ready")
        rf_read_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=[])
        witem = WaitingStoreIndexedUnordered(
            params=kamlet.params, instr=self, rf_ident=rf_read_ident,
            src_pregs=src_pregs, mask_preg=mask_preg, index_pregs=index_pregs,
            index_bound_bits=kamlet.index_bound_bits)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingStoreIndexedUnordered',
            read_regs=read_regs)
        await kamlet.cache_table.add_witem(witem=witem)


class WaitingStoreIndexedUnordered(WaitingStoreScatterBase):
    """Waiting item for unordered indexed stores."""

    def __init__(self, instr, params, src_pregs: dict[int, int],
                 mask_preg: int | None, index_pregs: dict[int, int],
                 rf_ident=None, index_bound_bits: int = 0):
        super().__init__(instr=instr, params=params, src_pregs=src_pregs,
                         mask_preg=mask_preg, rf_ident=rf_ident)
        # 0 = no bound, N = mask indices to lower N bits. Captured at creation time.
        self.index_bound_bits = index_bound_bits
        self.index_offset = instr.index_offset
        # Phys regs for the index vector, locked at start time, keyed by
        # absolute vline index (index_v).
        self.index_pregs = index_pregs

    def get_element_byte_offset(self, jamlet: 'Jamlet', element_index: int) -> int:
        """Read the byte offset from the index register for this element."""
        wb = jamlet.params.word_bytes
        index_ew = self.item.index_ordering.ew
        index_bytes = index_ew // 8

        adjusted_index = element_index + self.index_offset
        elements_in_vline = jamlet.params.vline_bytes * 8 // index_ew
        index_v = adjusted_index // elements_in_vline
        index_ve = adjusted_index % elements_in_vline
        index_we = index_ve // jamlet.params.j_in_l

        index_preg = self.index_pregs[index_v]
        byte_in_word = (index_we * index_bytes) % wb

        word_data = jamlet.rf_slice[index_preg * wb: (index_preg + 1) * wb]
        index_value = int.from_bytes(word_data[byte_in_word:byte_in_word + index_bytes],
                                     byteorder='little', signed=False)
        if self.index_bound_bits > 0:
            index_value &= (1 << self.index_bound_bits) - 1
        return index_value

    def get_additional_read_pregs(self) -> List[int]:
        """Return the index phys regs that were locked at start time."""
        return list(self.index_pregs.values())
