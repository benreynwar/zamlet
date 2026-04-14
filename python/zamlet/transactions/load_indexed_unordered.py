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
from zamlet.kamlet.kinstructions import KInstr, Renamed
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
    index_offset: int = 0

    async def admit(self, kamlet) -> 'LoadIndexedUnordered | None':
        dst_ew = self.dst_ordering.ew
        dst_elements_in_vline = kamlet.params.vline_bytes * 8 // dst_ew
        dst_start_vline = self.start_index // dst_elements_in_vline
        dst_end_vline = (self.start_index + self.n_elements - 1) // dst_elements_in_vline

        index_ew = self.index_ordering.ew
        index_elements_in_vline = kamlet.params.vline_bytes * 8 // index_ew
        index_start_vline = (
            (self.start_index + self.index_offset) // index_elements_in_vline
        )
        index_end_vline = (
            (self.start_index + self.index_offset + self.n_elements - 1)
            // index_elements_in_vline
        )

        # Resolve src/mask phys lookups BEFORE allocating dst phys, so an
        # arch overlap (e.g. mask_reg == dst arch) resolves to the old phys.
        index_pregs = {v: kamlet.r(self.index_reg + v)
                       for v in range(index_start_vline, index_end_vline + 1)}
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None

        dst_preg_list = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=dst_start_vline, end_vline=dst_end_vline,
            start_index=self.start_index, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline,
            mask_present=self.mask_reg is not None)
        dst_pregs = {dst_start_vline + i: p for i, p in enumerate(dst_preg_list)}

        dst_values = set(dst_pregs.values())
        overlap = dst_values & set(index_pregs.values())
        assert not overlap, \
            f"dst_pregs {dst_pregs} overlaps with index_pregs {index_pregs}: {overlap}"
        if mask_preg is not None:
            assert mask_preg not in dst_values, \
                f"mask_preg {mask_preg} overlaps with dst_pregs {dst_pregs}"

        return self.rename(
            reads_all_memory=True, writeset_ident=self.writeset_ident,
            needs_witem=1,
            dst_pregs=dst_pregs, src2_pregs=index_pregs,
            mask_preg=mask_preg, index_bound_bits=kamlet.index_bound_bits,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        logger.debug(
            f'kamlet ({kamlet.min_x}, {kamlet.min_y}): load_indexed.execute '
            f'addr={hex(self.g_addr.addr)} ident={self.instr_ident}')
        rf_write_ident = kamlet.rf_info.start(
            read_regs=r.read_pregs, write_regs=r.write_pregs)
        witem = WaitingLoadIndexedUnordered(
            params=kamlet.params, instr=self, rf_ident=rf_write_ident,
            dst_pregs=r.dst_pregs, mask_preg=r.mask_preg,
            index_pregs=r.src2_pregs,
            index_bound_bits=r.index_bound_bits)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y,
            'WaitingLoadIndexedUnordered',
            read_regs=r.read_pregs, write_regs=r.write_pregs)
        kamlet.cache_table.add_witem_immediately(witem=witem)


class WaitingLoadIndexedUnordered(WaitingLoadGatherBase):
    """Waiting item for unordered indexed loads."""

    def __init__(self, instr, params, dst_pregs: dict[int, int],
                 mask_preg: int | None, index_pregs: dict[int, int],
                 rf_ident=None, index_bound_bits: int = 0):
        super().__init__(instr=instr, params=params, dst_pregs=dst_pregs,
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
