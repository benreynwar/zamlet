"""
J2J Words Mapping

Common mapping logic for J2J (jamlet-to-jamlet) word transfers used by both
load_j2j_words and store_j2j_words transactions.

For Load: src = memory (cache), dst = register
For Store: src = register, dst = memory (cache)

The mapping functions determine which bytes from source map to which bytes
in destination, accounting for different element widths and offsets.
"""

from dataclasses import dataclass
from typing import List, TYPE_CHECKING
import logging

from zamlet import addresses, utils
from zamlet.params import ZamletParams

if TYPE_CHECKING:
    from zamlet.addresses import KMAddr, Ordering

logger = logging.getLogger(__name__)


@dataclass
class RegMemMapping:
    """
    Describes how a piece of register data maps to memory data (or vice versa).

    For Load: reg is dst, mem is src
    For Store: reg is src, mem is dst

    The _v fields are vline indices (which vector line).
    The _vw fields are word indices within a vline (this is related to which jamlet the word is in).
    The _wb fields are bit offsets within the word.
    """
    reg_v: int
    reg_vw: int
    reg_wb: int
    mem_v: int
    mem_vw: int
    mem_wb: int
    n_bits: int


def get_mapping_from_reg(
    params: ZamletParams,
    k_maddr: 'KMAddr',
    reg_ordering: 'Ordering',
    start_index: int,
    n_elements: int,
    reg_wb: int,
    reg_x: int,
    reg_y: int,
) -> List[RegMemMapping]:
    """
    Given the byte index in the register word, find which memory bytes it maps to.

    For Load: reg = dst, we're finding what memory bytes feed into this register byte
    For Store: reg = src, we're finding what memory bytes this register byte writes to

    Args:
        params: System parameters
        k_maddr: Memory address with ordering info
        reg_ordering: Register ordering (element width and word order)
        start_index: First element index being transferred
        n_elements: Number of elements being transferred
        reg_wb: Register word bit offset (must be multiple of 8). Which byte in the register
                word we're trying to find the mapping for.
        reg_x, reg_y: Jamlet coordinates for word in the register file we're trying to find
                      the mapping for.

    Returns:
        List of RegMemMapping for each vline that has data for this byte position

    Note: A mapping is not returned if this byte was already handled by the mapping for
    a previous byte (since mappings can have n_bits > 8).
    """
    ww = params.word_bytes * 8
    assert reg_wb % 8 == 0

    reg_vw = addresses.j_coords_to_vw_index(params, reg_ordering.word_order, reg_x, reg_y)
    reg_ew = reg_ordering.ew
    reg_ve = reg_wb // reg_ew * params.j_in_l + reg_vw
    reg_eb = reg_wb % reg_ew
    reg_elements_in_vline = params.vline_bytes * 8 // reg_ew
    start_vline = start_index // reg_elements_in_vline
    end_vline = (start_index + n_elements - 1) // reg_elements_in_vline
    mem_base_addr = k_maddr.to_logical_vline_addr().offset_bits(-reg_ew * start_index)
    mem_ew = k_maddr.ordering.ew

    logger.debug(
        f'get_mapping_from_reg: reg_x={reg_x} reg_y={reg_y} reg_wb={reg_wb} '
        f'reg_vw={reg_vw} reg_ve={reg_ve} reg_eb={reg_eb} '
        f'start_vline={start_vline} end_vline={end_vline} '
        f'mem_base_addr.index={mem_base_addr.index} mem_base_addr.bit_addr={mem_base_addr.bit_addr} '
        f'start_index={start_index} n_elements={n_elements}')

    mappings: List[RegMemMapping] = []
    for reg_v in range(start_vline, end_vline + 1):
        reg_addr = reg_v * params.vline_bytes * 8 + reg_ve * reg_ew + reg_eb
        mem_addr = mem_base_addr.offset_bits(reg_addr)
        mem_eb, mem_vw, mem_we, _ = utils.split_by_factors(
            mem_addr.bit_addr, [mem_ew, params.j_in_l, ww // mem_ew])
        mem_v = mem_addr.index

        if mem_eb != 0 and reg_eb != 0:
            # This byte has already been handled by a previous tag.
            continue

        mem_wb = mem_we * mem_ew + mem_eb
        n_bits = min(mem_ew - mem_eb, reg_ew - reg_eb)
        element_index = reg_ve + reg_v * reg_elements_in_vline

        logger.debug(
            f'  reg_v={reg_v} reg_addr={reg_addr} mem_addr.index={mem_addr.index} '
            f'mem_addr.bit_addr={mem_addr.bit_addr} element_index={element_index} '
            f'in_range={start_index <= element_index < start_index + n_elements}')

        if start_index <= element_index < start_index + n_elements:
            mappings.append(RegMemMapping(
                reg_v=reg_v, reg_vw=reg_vw, reg_wb=reg_wb,
                mem_v=mem_v, mem_vw=mem_vw, mem_wb=mem_wb, n_bits=n_bits))

    return mappings


def get_mapping_from_mem(
    params: ZamletParams,
    k_maddr: 'KMAddr',
    reg_ordering: 'Ordering',
    start_index: int,
    n_elements: int,
    mem_wb: int,
    mem_x: int,
    mem_y: int,
) -> List[RegMemMapping]:
    """
    Given the byte index in the memory word, find which register bytes it maps to.

    For Load: mem = src, we're finding what register bytes this memory byte feeds into
    For Store: mem = dst, we're finding what register bytes feed into this memory byte

    Args:
        params: System parameters
        k_maddr: Memory address with ordering info
        reg_ordering: Register ordering (element width and word order)
        start_index: First element index being transferred
        n_elements: Number of elements being transferred
        mem_wb: Memory word bit offset (must be multiple of 8). The byte in the memory
                word that we're trying to find the mapping for.
        mem_x, mem_y: Jamlet coordinates for the memory word that we're trying to find
                      the mapping for.

    Returns:
        List of RegMemMapping for each vline that has data for this byte position

    Note: A mapping is not returned if this byte was already handled by the mapping for
    a previous byte (since mappings can have n_bits > 8).
    """
    assert mem_wb < params.word_bytes * 8
    ww = params.word_bytes * 8
    assert mem_wb % 8 == 0

    mem_vw = addresses.j_coords_to_vw_index(params, k_maddr.ordering.word_order, mem_x, mem_y)
    mem_ew = k_maddr.ordering.ew
    mem_ve = mem_wb // mem_ew * params.j_in_l + mem_vw
    mem_eb = mem_wb % mem_ew
    mem_bit_addr_in_vline = mem_ve * mem_ew + mem_eb

    reg_ew = reg_ordering.ew
    reg_elements_in_vline = params.vline_bytes * 8 // reg_ew
    start_vline = start_index // reg_elements_in_vline
    end_vline = (start_index + n_elements - 1) // reg_elements_in_vline

    mem_base_addr = k_maddr.to_logical_vline_addr().offset_bits(-reg_ew * start_index)

    if mem_bit_addr_in_vline < mem_base_addr.bit_addr:
        # We're in the next vline by the time we get to this address in the vline.
        mem_v_offset = 1
    else:
        mem_v_offset = 0

    logger.debug(
        f'get_mapping_from_mem: mem_x={mem_x} mem_y={mem_y} mem_wb={mem_wb} '
        f'mem_vw={mem_vw} mem_ve={mem_ve} mem_eb={mem_eb} '
        f'mem_bit_addr_in_vline={mem_bit_addr_in_vline} '
        f'start_vline={start_vline} end_vline={end_vline} mem_v_offset={mem_v_offset} '
        f'mem_base_addr.index={mem_base_addr.index} mem_base_addr.bit_addr={mem_base_addr.bit_addr} '
        f'start_index={start_index} n_elements={n_elements}')

    mappings: List[RegMemMapping] = []
    for reg_v in range(start_vline, end_vline + 1):
        mem_v = mem_base_addr.index + reg_v + mem_v_offset
        mem_bit_addr = mem_v * params.vline_bytes * 8 + mem_bit_addr_in_vline
        reg_bit_addr = (mem_bit_addr - mem_base_addr.bit_addr -
                        mem_base_addr.index * params.vline_bytes * 8)
        reg_eb, reg_vw, reg_we, reg_v_check = utils.split_by_factors(
            reg_bit_addr, [reg_ew, params.j_in_l, ww // reg_ew])
        assert reg_v == reg_v_check
        reg_ve = reg_we * params.j_in_l + reg_vw
        reg_wb = reg_we * reg_ew + reg_eb

        if mem_eb != 0 and reg_eb != 0:
            # This byte has already been handled by a previous tag.
            continue

        n_bits = min(reg_ew - reg_eb, mem_ew - mem_eb)
        element_index = reg_ve + reg_v * reg_elements_in_vline

        logger.debug(
            f'  reg_v={reg_v} mem_v={mem_v} reg_bit_addr={reg_bit_addr} '
            f'reg_vw={reg_vw} reg_wb={reg_wb} element_index={element_index} '
            f'in_range={start_index <= element_index < start_index + n_elements}')

        if start_index <= element_index < start_index + n_elements:
            mappings.append(RegMemMapping(
                reg_v=reg_v, reg_vw=reg_vw, reg_wb=reg_wb,
                mem_v=mem_v, mem_vw=mem_vw, mem_wb=mem_wb, n_bits=n_bits))

    return mappings
