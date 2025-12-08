'''
Read Byte Transaction

Handles single byte reads from cache memory. This is used by the scalar processor
to read individual bytes from VPU memory.

Flow:
1. Kamlet receives ReadByte instruction
2. Check if cache line is ready for reading (can_read)
3. If yes, read byte from SRAM and send response
4. If no, create WaitingReadByte, wait for cache line
5. When cache ready, read byte from SRAM and send READ_BYTE_RESP to scalar processor
'''
from typing import TYPE_CHECKING
import logging
from dataclasses import dataclass

from zamlet.addresses import KMAddr
from zamlet.waiting_item import WaitingItemRequiresCache
from zamlet.kamlet import kinstructions
from zamlet.message import MessageType, SendType, ValueHeader

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


@dataclass
class ReadByte(kinstructions.TrackedKInstr):
    """
    This instruction reads from the VPU memory.
    The scalar processor receives a response packet.
    """
    k_maddr: KMAddr
    instr_ident: int

    async def update_kamlet(self, kamlet: 'Kamlet'):
        """
        Reads a byte from memory.
        It first makes sure that we've got the cache line ready.
        """
        if not kamlet.cache_table.can_read(self.k_maddr):
            witem = WaitingReadByte(self)
            kamlet.monitor.record_witem_created(
                self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingReadByte')
            await kamlet.cache_table.add_witem(witem=witem, k_maddr=self.k_maddr)
        else:
            await do_read_byte(kamlet, self)
            kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


class WaitingReadByte(WaitingItemRequiresCache):

    cache_is_read = True

    def __init__(self, instr: ReadByte):
        super().__init__(item=instr, instr_ident=instr.instr_ident)

    def ready(self) -> bool:
        return self.cache_is_avail

    async def finalize(self, kamlet: 'Kamlet') -> None:
        instr = self.item
        assert isinstance(instr, ReadByte)
        await do_read_byte(kamlet, instr)


async def do_read_byte(kamlet: 'Kamlet', instr: ReadByte) -> None:
    """
    Read a byte from cache and send response to scalar processor.
    """
    assert instr.k_maddr.bit_addr % 8 == 0
    if instr.k_maddr.k_index == kamlet.k_index:
        assert kamlet.cache_table.can_read(instr.k_maddr)
        j_saddr = instr.k_maddr.to_j_saddr(kamlet.cache_table)
        jamlet = kamlet.jamlets[j_saddr.j_in_k_index]
        await send_read_byte_resp(jamlet, instr, j_saddr.addr)


async def send_read_byte_resp(
    jamlet: 'Jamlet', instr: ReadByte, sram_address: int
) -> None:
    """
    Read a byte from SRAM and send READ_BYTE_RESP to scalar processor.
    """
    value = bytes([jamlet.sram[sram_address]])
    logger.debug(f'{jamlet.clock.cycle}: READ_BYTE: jamlet ({jamlet.x},{jamlet.y}) '
                 f'ident={instr.instr_ident} k_maddr=0x{instr.k_maddr.addr:x} '
                 f'sram[{sram_address}] value=0x{value[0]:02x}')
    header = ValueHeader(
        message_type=MessageType.READ_BYTE_RESP,
        send_type=SendType.SINGLE,
        value=value,
        target_x=jamlet.front_x,
        target_y=jamlet.front_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        length=1,
        ident=instr.instr_ident,
    )
    packet = [header]
    # Get kinstr span as parent for message (not witem or kinstr_exec, since those complete before response arrives)
    kinstr_span_id = jamlet.monitor.get_kinstr_span_id(instr.instr_ident)
    await jamlet.send_packet(packet, parent_span_id=kinstr_span_id)
