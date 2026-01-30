"""
Handler for READ_REG_ELEMENT_REQ/RESP/DROP messages.

Used by vrgather to read register elements from remote jamlets.
"""

import logging
from typing import List, Any, TYPE_CHECKING

from zamlet.message import MessageType, RegElementHeader, SendType
from zamlet.transactions import register_handler

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


@register_handler(MessageType.READ_REG_ELEMENT_REQ)
async def handle_read_reg_element_req(jamlet: 'Jamlet', packet: List[Any]) -> None:
    """Handle READ_REG_ELEMENT_REQ: read from register file and respond."""
    header = packet[0]
    assert isinstance(header, RegElementHeader)

    # Check if the parent instruction exists on this jamlet - if not, the data
    # may not have been written yet, so we need to drop and retry later
    parent_witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    if parent_witem is None:
        await _send_drop(jamlet, header)
        return

    wb = jamlet.params.word_bytes

    # Read the requested bytes from local rf_slice, pad to word width
    offset = header.src_reg * wb + header.src_byte_offset
    data = bytes(jamlet.rf_slice[offset:offset + header.n_bytes])
    data = data + bytes(wb - len(data))

    # Send response back
    resp_header = RegElementHeader(
        target_x=header.source_x,
        target_y=header.source_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        message_type=MessageType.READ_REG_ELEMENT_RESP,
        send_type=SendType.SINGLE,
        length=2,
        tag=header.tag,
        ident=header.ident,
        src_reg=header.src_reg,
        src_byte_offset=header.src_byte_offset,
        n_bytes=header.n_bytes,
    )
    resp_packet = [resp_header, data]

    # Look up transaction (requester is source, we are dest)
    transaction_span_id = jamlet.monitor.get_transaction_span_id(
        header.ident, header.tag,
        header.source_x, header.source_y, jamlet.x, jamlet.y)
    assert transaction_span_id is not None
    await jamlet.send_packet(resp_packet, parent_span_id=transaction_span_id)

    logger.debug(f'{jamlet.clock.cycle}: jamlet ({jamlet.x},{jamlet.y}): '
                 f'READ_REG_ELEMENT_REQ reg={header.src_reg} offset={header.src_byte_offset} '
                 f'n_bytes={header.n_bytes} -> ({header.source_x},{header.source_y}) '
                 f'data={data.hex()}')


@register_handler(MessageType.READ_REG_ELEMENT_RESP)
def handle_read_reg_element_resp(jamlet: 'Jamlet', packet: List[Any]) -> None:
    """Handle READ_REG_ELEMENT_RESP: forward to waiting item."""
    header = packet[0]
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    witem.process_response(jamlet, packet)


@register_handler(MessageType.READ_REG_ELEMENT_DROP)
def handle_read_reg_element_drop(jamlet: 'Jamlet', packet: List[Any]) -> None:
    """Handle READ_REG_ELEMENT_DROP: forward to waiting item for retry."""
    header = packet[0]
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    witem.process_drop(jamlet, packet)


async def _send_drop(jamlet: 'Jamlet', header: RegElementHeader) -> None:
    """Send READ_REG_ELEMENT_DROP indicating request couldn't be handled yet."""
    drop_header = RegElementHeader(
        target_x=header.source_x,
        target_y=header.source_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        message_type=MessageType.READ_REG_ELEMENT_DROP,
        send_type=SendType.SINGLE,
        length=1,
        tag=header.tag,
        ident=header.ident,
        src_reg=header.src_reg,
        src_byte_offset=header.src_byte_offset,
        n_bytes=header.n_bytes,
    )
    # Look up transaction (requester is source, we are dest)
    transaction_span_id = jamlet.monitor.get_transaction_span_id(
        header.ident, header.tag,
        header.source_x, header.source_y, jamlet.x, jamlet.y)
    assert transaction_span_id is not None
    await jamlet.send_packet([drop_header], parent_span_id=transaction_span_id,
                             drop_reason='parent_not_ready')
    logger.debug(f'{jamlet.clock.cycle}: jamlet ({jamlet.x},{jamlet.y}): '
                 f'READ_REG_ELEMENT_DROP -> ({header.source_x},{header.source_y}) '
                 f'tag={header.tag} (parent not ready)')
