import logging
from typing import List, TYPE_CHECKING

from zamlet import utils
from zamlet.addresses import GlobalAddress, Ordering, WordOrder
from zamlet.monitor import CompletionType, SpanType
from zamlet.params import LamletParams

if TYPE_CHECKING:
    from zamlet.lamlet.lamlet import Lamlet

logger = logging.getLogger(__name__)


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


async def setup_mask_register(
    lamlet: 'Lamlet',
    mask_reg: int,
    mask_bits: List[bool],
    page_bytes: int,
    mask_mem_addr: int,
) -> None:
    """Write mask bits to memory and load into a vector register."""
    mask_ordering = Ordering(WordOrder.STANDARD, 64)
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=mask_mem_addr * 8, params=lamlet.params),
        page_bytes, is_vpu=True, ordering=mask_ordering
    )

    mask_bytes = mask_bits_to_ew64_bytes(lamlet.params, mask_bits)
    await lamlet.set_memory(mask_mem_addr, bytes(mask_bytes))
    logger.info(f"Mask bytes written to 0x{mask_mem_addr:x}: {mask_bytes.hex()}")

    mask_span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="load_mask")
    await lamlet.vload(
        vd=mask_reg,
        addr=mask_mem_addr,
        ordering=mask_ordering,
        n_elements=len(mask_bits),
        mask_reg=None,
        start_index=0,
        parent_span_id=mask_span_id,
    )
    lamlet.monitor.finalize_children(mask_span_id)
    logger.info(f"Mask loaded into v{mask_reg}")


async def zero_register(
    lamlet: 'Lamlet',
    reg: int,
    n_elements: int,
    ew: int,
    page_bytes: int,
    zero_mem_addr: int,
) -> None:
    """Initialize a vector register to zeros."""
    element_bytes = ew // 8
    n_pages = (n_elements * element_bytes + page_bytes - 1) // page_bytes
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=zero_mem_addr * 8, params=lamlet.params),
        page_bytes * max(1, n_pages), is_vpu=True, ordering=Ordering(WordOrder.STANDARD, ew)
    )
    await lamlet.set_memory(zero_mem_addr, bytes(n_elements * element_bytes))
    zero_span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="zero_reg")
    await lamlet.vload(
        vd=reg,
        addr=zero_mem_addr,
        ordering=Ordering(WordOrder.STANDARD, ew),
        n_elements=n_elements,
        mask_reg=None,
        start_index=0,
        parent_span_id=zero_span_id,
    )
    lamlet.monitor.finalize_children(zero_span_id)
    logger.info(f"Register v{reg} zeroed ({n_elements} elements)")



