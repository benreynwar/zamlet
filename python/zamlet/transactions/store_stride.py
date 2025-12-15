'''
Strided (scatter) store: element i is stored to address (base + i * stride_bytes).

Similar to indexed stores but the offset is computed as (element_index * stride)
instead of read from a register.
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

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): store_stride.update_kamlet '
                     f'addr={hex(self.g_addr.addr)} ident={self.instr_ident}')
        src_regs = kamlet.get_regs(
            start_index=self.start_index, n_elements=self.n_elements,
            ew=self.src_ordering.ew, base_reg=self.src)
        if self.mask_reg is not None:
            read_regs = src_regs + [self.mask_reg]
        else:
            read_regs = src_regs
        await kamlet.wait_for_rf_available(write_regs=[], read_regs=read_regs,
                                           instr_ident=self.instr_ident)
        rf_read_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=[])
        witem = WaitingStoreStride(
            params=kamlet.params, instr=self, rf_ident=rf_read_ident)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingStoreStride',
            read_regs=read_regs)
        await kamlet.cache_table.add_witem(witem=witem)


class WaitingStoreStride(WaitingStoreScatterBase):
    """Waiting item for strided stores."""

    def get_element_byte_offset(self, jamlet: 'Jamlet', element_index: int) -> int:
        """Compute byte offset as element_index * stride_bytes."""
        instr = self.item
        return element_index * instr.stride_bytes

    def get_additional_read_regs(self, kamlet) -> List[int]:
        """No additional registers to read for strided stores."""
        return []
