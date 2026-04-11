'''
Strided (gather) load: element i is loaded from address (base + i * stride_bytes).

Similar to indexed loads but the offset is computed as (element_index * stride)
instead of read from a register.
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
class LoadStride(KInstr):
    """
    A load from the VPU memory into a vector register.
    The g_addr is the base address (element 0's location).

    stride_bytes: byte stride between elements. None = unit stride (ew/8 bytes).

    n_elements is limited to j_in_l
    This is because if we have multiple elements for one jamlet that it
    gets hard to keep track of the meta information (i.e. like the ew of the src page).
    If we have only one element for each jamlet we can track this information simply
    in the Waiting Item.
    """
    dst: int
    g_addr: addresses.GlobalAddress
    start_index: int
    n_elements: int
    dst_ordering: addresses.Ordering
    mask_reg: int | None
    writeset_ident: int
    instr_ident: int
    stride_bytes: int | None = None

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): load_stride.update_kamlet '
                     f'addr={hex(self.g_addr.addr)} ident={self.instr_ident}')
        ew = self.dst_ordering.ew
        elements_in_vline = kamlet.params.vline_bytes * 8 // ew
        start_vline = self.start_index // elements_in_vline
        end_vline = (self.start_index + self.n_elements - 1) // elements_in_vline

        # Resolve src/mask phys lookups BEFORE allocating dst phys, so an
        # arch overlap (mask_reg == dst arch) resolves to the old phys.
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        dst_preg_list = kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=start_vline, end_vline=end_vline,
            start_index=self.start_index, n_elements=self.n_elements,
            elements_in_vline=elements_in_vline,
            mask_present=self.mask_reg is not None)
        dst_pregs = {start_vline + i: dst_preg_list[i] for i in range(len(dst_preg_list))}

        read_regs = [mask_preg] if mask_preg is not None else []
        write_regs = list(dst_pregs.values())
        await kamlet.wait_for_rf_available(write_regs=write_regs, read_regs=read_regs,
                                           instr_ident=self.instr_ident)
        rf_write_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=write_regs)
        witem = WaitingLoadStride(
            params=kamlet.params, instr=self, rf_ident=rf_write_ident,
            dst_pregs=dst_pregs, mask_preg=mask_preg)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingLoadStride',
            read_regs=read_regs, write_regs=write_regs)
        await kamlet.cache_table.add_witem(witem=witem)


class WaitingLoadStride(WaitingLoadGatherBase):
    """Waiting item for strided loads."""

    def get_element_byte_offset(self, jamlet: 'Jamlet', element_index: int) -> int:
        """Compute byte offset as element_index * stride_bytes."""
        instr = self.item
        return element_index * instr.stride_bytes

    def get_additional_read_pregs(self) -> List[int]:
        """No additional registers to read for strided loads."""
        return []
