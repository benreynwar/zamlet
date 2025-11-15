from dataclasses import dataclass

from params import LamletParams
import kinstructions
import ew_convert
import addresses
from message import MessageType, SendType, Header


@dataclass
class ReadWordsResponseInfo:
    """
    What to do with the data from a read response.
    """
    # Apply this to a new word or to the last word.
    new_word: bool
    # How many its to shift left.
    shift_left: int
    # Bit mask to use.
    bit_mask: int


def handle_vload_instr(
        params: LamletParams, kinstr: kinstructions.Load, dst_vw_index: int,
        start_element: int, n_elements: int,
        ):
    dst_ew = kinstr.dst_ordering.ew
    src_ew = kinstr.k_maddr.ordering.ew
    offset = kinstr.maddr.addr % params.vline_bytes
    messages = ew_convert.create_messages(
            params=params, src_ew=src_ew, dst_ew=dst_ew, offset=offset*8,
            start_element=start_element, n_elements=n_elements)[dst_vw_index]
    by_vw_index = {}
    for message in messages:
        if message.vw_index not in by_vw_index:
            by_vw_index[message.vw_index] = []
        by_vw_index[message.vw_index].append(message)
    infos = []
    packets = []
    for src_vw_index, vw_messages in by_vw_index.items():
        by_v_index = {}
        for message in vw_messages:
            if message.v_index not in by_v_index:
                by_v_index[message.v_index] = []
            by_v_index[message.v_index].append(message)
        v_indices = sorted(list(by_v_index.keys()))
        last_v_index = None
        for v_index in v_indices:
            if last_v_index is None or last_v_index != v_index:
                assert v_index == last_v_index + 1
            info = ReadWordsResponseInfo(
                new_word=last_v_index != v_index,
                shift_left=by_v_index[v_index].shift,
                bit_mask=by_v_index[v_index].bit_mask,
                )
            last_v_index = v_index
            infos.append(info)
        src_x, src_y = addresses.vw_index_to_j_coords(params, kinstr.word_order, src_vw_index)
        this_x, this_y = addresses.vw_index_to_j_coords(
                params, kinstr.dst_ordering.word_order, dst_vw_index)
        header = Header(
            target_x=src_x,
            target_y=src_y,
            source_x=this_x,
            source_y=this_y,
            length=2,
            message_type=MessageType.READ_WORDS,
            send_type=SendType.SINGLE,
            ident=kinstr.ident,
            words_requested=len(by_v_index),
            )
        address = kinstr.addr
        packets.append([header, address])
    return packets, infos
