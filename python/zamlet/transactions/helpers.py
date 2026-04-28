'''
Helper functions shared across transaction modules.
'''
from typing import List, Tuple, TYPE_CHECKING

from zamlet import addresses, utils

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet


def read_element(jamlet: 'Jamlet', preg: int, element_index: int, ew: int) -> bytes:
    """Read a single element from a single phys register.

    The caller is responsible for resolving the correct phys register for the
    vline that owns this element. Under kamlet-side rename, adjacent vlines
    may map to non-adjacent phys regs, so this helper cannot recover the
    phys for vline N by adding N to a base phys.

    Args:
        jamlet: The jamlet with the register file
        preg: Phys register holding the vline that contains this element
        element_index: Global element index (across all jamlets) — used only
            to compute which element-within-word to read
        ew: Element width in bits

    Returns:
        The element data as bytes
    """
    wb = jamlet.params.word_bytes
    element_bytes = ew // 8

    element_in_jamlet = element_index // jamlet.params.j_in_l
    element_in_word = element_in_jamlet % (wb * 8 // ew)
    byte_offset = element_in_word * element_bytes

    word_data = jamlet.rf_slice[preg * wb: (preg + 1) * wb]
    return word_data[byte_offset:byte_offset + element_bytes]


def get_offsets_and_masks(
    jamlet: 'Jamlet',
    start_index: int,
    n_elements: int,
    ordering: addresses.Ordering,
    mask_reg: int | None,
    vta: bool,
    vma: bool,
) -> List[Tuple[int, int, int]]:
    """
    Calculate vline offsets, active masks, and agnostic masks for an
    aligned load/store.

    Returns a list of (vline_offset, active_mask, agnostic_mask) tuples:
    - vline_offset: offset from the first vline
    - active_mask: 1-bits where the new value should be written (active body
      elements owned by this jamlet's word)
    - agnostic_mask: 1-bits where 0xFF should be written instead of the old
      value. Disjoint from active_mask. Always 0 when vta=vma=False.

    Per the RVV vta/vma policy:
    - prestart (element_index < start_index): undisturbed, never agnostic
    - active (in body, mask_bit=1): in active_mask
    - inactive body (in body, mask_bit=0): agnostic if vma else undisturbed
    - tail (element_index >= start_index + n_elements): agnostic if vta
      else undisturbed

    Stores ignore agnostic_mask (memory writes have no undisturbed/agnostic
    semantics). Loads use both: the active_mask drives the bulk write, and
    the agnostic_mask substitutes 0xFF for old-value bytes in those
    positions.
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
        params, ordering.word_order, jamlet.jx, jamlet.jy)
    ww = params.word_bytes * 8
    elements_in_word = ww // ordering.ew
    elements_in_vline = params.vline_bytes * 8 // ordering.ew

    offsets_and_masks = []
    first_vline = start_index // elements_in_vline

    for vline_index in range(first_vline, (start_index + n_elements - 1) // elements_in_vline + 1):
        active_bits = []
        agnostic_bits = []
        for we in range(elements_in_word):
            element_index = vline_index * elements_in_vline + we * params.j_in_l + vw_index
            if element_index < start_index:
                # prestart: undisturbed regardless of vta/vma
                active_bits += [0] * ordering.ew
                agnostic_bits += [0] * ordering.ew
            elif element_index >= start_index + n_elements:
                # tail
                active_bits += [0] * ordering.ew
                agnostic_bits += [1 if vta else 0] * ordering.ew
            else:
                bit_index = element_index // params.j_in_l
                element_mask_bit = (mask_word >> bit_index) & 1
                if element_mask_bit:
                    active_bits += [1] * ordering.ew
                    agnostic_bits += [0] * ordering.ew
                else:
                    active_bits += [0] * ordering.ew
                    agnostic_bits += [1 if vma else 0] * ordering.ew
        active_mask = utils.list_of_uints_to_uint(active_bits, width=1)
        agnostic_mask = utils.list_of_uints_to_uint(agnostic_bits, width=1)
        offsets_and_masks.append(
            (vline_index - first_vline, active_mask, agnostic_mask))

    return offsets_and_masks


def write_agnostic_element(
    jamlet: 'Jamlet',
    *,
    instr_ident: int,
    dst_preg: int,
    tag: int,
    n_bytes: int,
    dst_e: int,
    reason: str,
) -> None:
    """Write n_bytes of 0xFF at byte position `tag` in dst_preg. Used by
    pull-style loads (gather, permute) at the leading-byte tag of an
    agnostic element (vta tail or vma mask-off body).
    """
    witem_span_id = jamlet.monitor.get_witem_span_id(
        instr_ident, jamlet.k_min_x, jamlet.k_min_y)
    jamlet.write_vreg(
        dst_preg, tag, b'\xff' * n_bytes,
        span_id=witem_span_id,
        event_details={'source': 'agnostic', 'element': dst_e,
                       'tag': tag, 'reason': reason})


