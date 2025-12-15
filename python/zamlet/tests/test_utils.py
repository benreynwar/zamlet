import logging
import struct
from typing import List

from zamlet import utils
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder
from zamlet.lamlet.lamlet import Lamlet
from zamlet.monitor import CompletionType, SpanType
from zamlet.params import LamletParams
from zamlet.runner import Clock

logger = logging.getLogger(__name__)


async def update(clock: Clock, lamlet: Lamlet):
    """Update loop for the lamlet."""
    while True:
        await clock.next_update
        lamlet.update()


async def setup_lamlet(clock: Clock, params: LamletParams) -> Lamlet:
    """Create and initialize a lamlet with update loop."""
    lamlet = Lamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())
    await clock.next_cycle
    return lamlet


def pack_elements(values: list[int], element_width: int) -> bytes:
    """Pack a list of integer values into bytes based on element width."""
    if element_width == 8:
        return bytes(v & 0xFF for v in values)
    elif element_width == 16:
        return struct.pack(f'<{len(values)}H', *[v & 0xFFFF for v in values])
    elif element_width == 32:
        return struct.pack(f'<{len(values)}I', *[v & 0xFFFFFFFF for v in values])
    elif element_width == 64:
        return struct.pack(f'<{len(values)}Q', *[v & 0xFFFFFFFFFFFFFFFF for v in values])
    else:
        raise ValueError(f"Unsupported element width: {element_width}")


def unpack_elements(data: bytes, element_width: int) -> list[int]:
    """Unpack bytes into a list of integer values based on element width."""
    n_elements = len(data) * 8 // element_width
    if element_width == 8:
        return list(data)
    elif element_width == 16:
        return list(struct.unpack(f'<{n_elements}H', data))
    elif element_width == 32:
        return list(struct.unpack(f'<{n_elements}I', data))
    elif element_width == 64:
        return list(struct.unpack(f'<{n_elements}Q', data))
    else:
        raise ValueError(f"Unsupported element width: {element_width}")


def dump_span_trees(monitor, filename='span_trees.txt'):
    """Dump all root span trees to a file for debugging."""
    with open(filename, 'w') as f:
        for span in monitor.spans.values():
            if span.parent is None:
                f.write(monitor.format_span_tree(span.span_id, max_depth=20))
                f.write('\n')
    logger.info(f"Span trees written to {filename}")


def get_vpu_base_addr(element_width: int) -> int:
    """Get the VPU memory base address for a given element width."""
    if element_width == 8:
        return 0x20000000
    elif element_width == 16:
        return 0x20800000
    elif element_width == 32:
        return 0x90080000
    elif element_width == 64:
        return 0x90100000
    else:
        raise ValueError(f"Unsupported element width: {element_width}")


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
        page_bytes, memory_type=MemoryType.VPU, ordering=mask_ordering
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
        page_bytes * max(1, n_pages), memory_type=MemoryType.VPU,
        ordering=Ordering(WordOrder.STANDARD, ew)
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



