from typing import List

from zamlet import utils
from zamlet.params import LamletParams


def get_from_list(l, index, default):
    if index < len(l):
        return l[index]
    else:
        return default


def mask_bits_to_ew64_bytes(params: LamletParams, bits: List[bool]):
    """
    Convert mask bits to ew=64 byte layout for loading into a mask register.

    Each jamlet gets word_bytes (8 bytes = 64 bits) for its mask.
    Bits are distributed across jamlets: bit i goes to jamlet (i % j_in_l).
    Output is word_bytes for jamlet 0, then word_bytes for jamlet 1, etc.
    """
    j_in_l = params.j_in_l
    wb = params.word_bytes
    max_bits_per_jamlet = wb * 8  # 64 bits per jamlet
    assert len(bits) <= j_in_l * max_bits_per_jamlet

    byts = bytearray()
    for jamlet_idx in range(j_in_l):
        # Collect bits for this jamlet: elements jamlet_idx, jamlet_idx+j_in_l, ...
        jamlet_bits = [get_from_list(bits, jamlet_idx + offset * j_in_l, False)
                       for offset in range(max_bits_per_jamlet)]
        # Pack into 64-bit int, then split into 8 bytes (little-endian)
        bits_int = utils.list_of_uints_to_uint([1 if b else 0 for b in jamlet_bits], width=1)
        byte_list = utils.uint_to_list_of_uints(bits_int, width=8, size=wb)
        byts.extend(byte_list)
    return byts



