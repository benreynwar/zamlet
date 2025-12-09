'''
Indexed (gather) load: element i is loaded from address (base + index_vector[i]).

The index register contains byte offsets with element width index_ew.
The data element width comes from SEW (dst_ordering.ew).

Ordered vs Unordered:
- Unordered (vluxei): All elements loaded in parallel, no ordering guarantees
- Ordered (vloxei): For VPU memory, same as unordered (no side effects).
  For scalar memory, lamlet buffers requests and processes in element order after sync.
'''

from typing import List, TYPE_CHECKING
from dataclasses import dataclass
import logging

from zamlet import addresses
from zamlet.kamlet.kinstructions import KInstr
from zamlet.kamlet.cache_table import SendState
from zamlet.message import TaggedHeader, ReadMemWordHeader, MessageType, SendType
from zamlet.transactions.load_gather_base import WaitingLoadGatherBase
from zamlet.transactions import register_handler

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet


logger = logging.getLogger(__name__)


@dataclass
class LoadIndexedUnordered(KInstr):
    """
    An indexed load from memory into a vector register.

    Each element i is loaded from address (g_addr + index_reg[i]).
    The index register contains byte offsets.

    When ordered=True and accessing scalar memory, lamlet buffers requests
    and processes them in element order after sync.

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
    ordered: bool = False

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): load_indexed.update_kamlet '
                     f'addr={hex(self.g_addr.addr)} ident={self.instr_ident} ordered={self.ordered}')
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
    """Waiting item for indexed loads.

    When instr.ordered=True and accessing scalar memory:
    - Receives ACK instead of RESP initially
    - Waits for sync before receiving data
    """

    def is_ordered(self) -> bool:
        """Return True if this is an ordered operation."""
        return getattr(self.item, 'ordered', False)

    def _ready_to_synchronize(self) -> bool:
        """Ready to sync when all states are ACKED or COMPLETE."""
        return all(state in (SendState.ACKED, SendState.COMPLETE)
                   for state in self.transaction_states)

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

    def process_ack(self, jamlet: 'Jamlet', packet) -> None:
        """Handle READ_MEM_WORD_ACK: scalar request buffered, waiting for data after sync."""
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        tag = header.tag
        state_idx = self._state_index(jamlet.j_in_k_index, tag)
        assert self.transaction_states[state_idx] == SendState.WAITING_FOR_RESPONSE
        self.transaction_states[state_idx] = SendState.ACKED
        logger.debug(f'{jamlet.clock.cycle}: WaitingLoadIndexedUnordered process_ack: '
                     f'jamlet ({jamlet.x},{jamlet.y}) ident={self.instr_ident} tag={tag}')


@register_handler(MessageType.READ_MEM_WORD_ACK)
def handle_ack(jamlet: 'Jamlet', packet: List) -> None:
    """Handle READ_MEM_WORD_ACK: find waiting item and process ACK."""
    header = packet[0]
    parent_ident = (header.ident - header.tag - 1) % jamlet.params.max_response_tags
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(parent_ident)
    if hasattr(witem, 'process_ack'):
        witem.process_ack(jamlet, packet)
    else:
        raise ValueError(f"Unexpected ACK for witem type {type(witem).__name__}")
