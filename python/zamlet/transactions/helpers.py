'''
Helper functions shared across transaction modules.
'''
from typing import List, Tuple, TYPE_CHECKING

from zamlet import addresses, utils

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet


def read_element(jamlet: 'Jamlet', reg: int, element_index: int, ew: int) -> bytes:
    """Read a single element from a jamlet's register file.

    Args:
        jamlet: The jamlet with the register file
        reg: Base register number
        element_index: Global element index (across all jamlets)
        ew: Element width in bits

    Returns:
        The element data as bytes
    """
    wb = jamlet.params.word_bytes
    element_bytes = ew // 8
    elements_in_vline = jamlet.params.vline_bytes * 8 // ew

    element_in_jamlet = element_index // jamlet.params.j_in_l
    vline_index = element_in_jamlet // (wb * 8 // ew)
    element_in_word = element_in_jamlet % (wb * 8 // ew)

    src_reg = reg + vline_index
    byte_offset = element_in_word * element_bytes

    word_data = jamlet.rf_slice[src_reg * wb: (src_reg + 1) * wb]
    return word_data[byte_offset:byte_offset + element_bytes]


def get_offsets_and_masks(
    jamlet: 'Jamlet',
    start_index: int,
    n_elements: int,
    ordering: addresses.Ordering,
    mask_reg: int | None
) -> List[Tuple[int, int]]:
    """
    Calculate vline offsets and element masks for aligned load/store operations.

    Returns a list of (vline_offset, mask) tuples where:
    - vline_offset: offset from the first vline
    - mask: bitmask indicating which bits in the word to read/write

    Args:
        jamlet: The jamlet performing the operation
        start_index: First element index being transferred
        n_elements: Number of elements being transferred
        ordering: Element width and word ordering
        mask_reg: Optional mask register number (None means all elements active)
    """
    params = jamlet.params
    word_bytes = params.word_bytes

    if mask_reg is not None:
        mask_word = int.from_bytes(
            jamlet.rf_slice[mask_reg * word_bytes: (mask_reg + 1) * word_bytes],
            byteorder='little')
    else:
        mask_word = (1 << (word_bytes * 8)) - 1

    vw_index = addresses.j_coords_to_vw_index(
        params, ordering.word_order, jamlet.x, jamlet.y)
    ww = params.word_bytes * 8
    elements_in_word = ww // ordering.ew
    elements_in_vline = params.vline_bytes * 8 // ordering.ew

    offsets_and_masks = []
    first_vline = start_index // elements_in_vline

    for vline_index in range(first_vline, (start_index + n_elements - 1) // elements_in_vline + 1):
        bit_mask = []
        for we in range(elements_in_word):
            element_index = vline_index * elements_in_vline + we * params.j_in_l + vw_index
            if start_index <= element_index < start_index + n_elements:
                bit_index = element_index // params.j_in_l
                element_mask_bit = (mask_word >> bit_index) & 1
                if element_mask_bit:
                    bit_mask += [1] * ordering.ew
                else:
                    bit_mask += [0] * ordering.ew
            else:
                bit_mask += [0] * ordering.ew
        mask = utils.list_of_uints_to_uint(bit_mask, width=1)
        offsets_and_masks.append((vline_index - first_vline, mask))

    return offsets_and_masks
