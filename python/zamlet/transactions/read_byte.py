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

from zamlet.waiting_item import WaitingItemRequiresCache
from zamlet.kamlet import kinstructions
from zamlet.message import MessageType, SendType, ValueHeader

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


class WaitingReadByte(WaitingItemRequiresCache):

    cache_is_read = True

    def __init__(self, instr: kinstructions.ReadByte):
        super().__init__(item=instr, instr_ident=instr.instr_ident)

    def ready(self) -> bool:
        return self.cache_is_avail

    async def finalize(self, kamlet: 'Kamlet') -> None:
        instr = self.item
        assert isinstance(instr, kinstructions.ReadByte)
        await do_read_byte(kamlet, instr)


async def do_read_byte(kamlet: 'Kamlet', instr: kinstructions.ReadByte) -> None:
    """
    Read a byte from cache and send response to scalar processor.
    """
    logger.debug(f'do_read_byte')
    assert instr.k_maddr.bit_addr % 8 == 0
    if instr.k_maddr.k_index != kamlet.k_index:
        return

    assert kamlet.cache_table.can_read(instr.k_maddr)
    j_saddr = instr.k_maddr.to_j_saddr(kamlet.cache_table)
    jamlet = kamlet.jamlets[j_saddr.j_in_k_index]
    await send_read_byte_resp(jamlet, instr, j_saddr.addr)


async def send_read_byte_resp(
    jamlet: 'Jamlet', instr: kinstructions.ReadByte, sram_address: int
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
    send_queue = jamlet.send_queues[header.message_type]
    while not send_queue.can_append():
        await jamlet.clock.next_cycle
    logger.debug(f'jamlet ({jamlet.x}, {jamlet.y}) appending a packet')
    send_queue.append(packet)
    logger.debug(f'jamlet ({jamlet.x}, {jamlet.y}) sent response')
