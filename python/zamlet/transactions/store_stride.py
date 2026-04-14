'''
Strided (scatter) store: element i is stored to address (base + i * stride_bytes).

Similar to indexed stores but the offset is computed as (element_index * stride)
instead of read from a register.
'''

from typing import List, TYPE_CHECKING
from dataclasses import dataclass
import logging

from zamlet import addresses
from zamlet.kamlet.kinstructions import KInstr, Renamed
from zamlet.transactions.store_scatter_base import WaitingStoreScatterBase

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet


logger = logging.getLogger(__name__)


@dataclass
class StoreStride(KInstr):
    """
    A store from a vector register to VPU memory with stride.
    The g_addr is the base address (element 0's location).

    stride_bytes: byte stride between elements in memory.

    n_elements is limited to j_in_l (same constraint as LoadStride).
    """
    src: int
    g_addr: addresses.GlobalAddress
    start_index: int
    n_elements: int
    src_ordering: addresses.Ordering
    mask_reg: int | None
    writeset_ident: int
    instr_ident: int
    stride_bytes: int

    async def admit(self, kamlet) -> 'StoreStride | None':
        ew = self.src_ordering.ew
        elements_in_vline = kamlet.params.vline_bytes * 8 // ew
        start_vline = self.start_index // elements_in_vline
        end_vline = (self.start_index + self.n_elements - 1) // elements_in_vline

        src_pregs = {v: kamlet.r(self.src + v) for v in range(start_vline, end_vline + 1)}
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        return self.rename(
            writes_all_memory=True, writeset_ident=self.writeset_ident,
            needs_witem=1,
            src_pregs=src_pregs, mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): store_stride.execute '
                     f'addr={hex(self.g_addr.addr)} ident={self.instr_ident}')
        rf_read_ident = kamlet.rf_info.start(
            read_regs=r.read_pregs, write_regs=r.write_pregs)
        witem = WaitingStoreStride(
            params=kamlet.params, instr=self, rf_ident=rf_read_ident,
            src_pregs=r.src_pregs, mask_preg=r.mask_preg)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingStoreStride',
            read_regs=r.read_pregs)
        kamlet.cache_table.add_witem_immediately(witem=witem)


class WaitingStoreStride(WaitingStoreScatterBase):
    """Waiting item for strided stores."""

    def get_element_byte_offset(self, jamlet: 'Jamlet', element_index: int) -> int:
        """Compute byte offset as element_index * stride_bytes."""
        instr = self.item
        return element_index * instr.stride_bytes

    def get_additional_read_pregs(self) -> List[int]:
        """No additional registers to read for strided stores."""
        return []
