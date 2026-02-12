import logging
import struct
from enum import Enum
from random import Random
from typing import List

from zamlet import utils
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder
from zamlet.oamlet.oamlet import Oamlet
from zamlet.monitor import CompletionType, SpanType
from zamlet.params import ZamletParams
from zamlet.runner import Clock

logger = logging.getLogger(__name__)


async def update(clock: Clock, lamlet: Oamlet):
    """Update loop for the lamlet."""
    while True:
        await clock.next_update
        lamlet.update()


async def setup_lamlet(clock: Clock, params: ZamletParams) -> Oamlet:
    """Create and initialize a lamlet with update loop."""
    lamlet = Oamlet(clock, params)
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


def mask_bits_to_ew64_bytes(params: ZamletParams, bits: List[bool]):
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
    lamlet: 'Oamlet',
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
    # Load j_in_l elements (one 64-bit word per jamlet) - the mask fits in one register
    await lamlet.vload(
        vd=mask_reg,
        addr=mask_mem_addr,
        ordering=mask_ordering,
        n_elements=lamlet.params.j_in_l,
        mask_reg=None,
        start_index=0,
        parent_span_id=mask_span_id,
    )
    lamlet.monitor.finalize_children(mask_span_id)
    logger.info(f"Mask loaded into v{mask_reg}")


async def zero_register(
    lamlet: 'Oamlet',
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


class PageType(Enum):
    """Page types for mixed memory testing."""
    VPU_EW8 = 'vpu_ew8'
    VPU_EW16 = 'vpu_ew16'
    VPU_EW32 = 'vpu_ew32'
    VPU_EW64 = 'vpu_ew64'
    SCALAR_IDEMPOTENT = 'scalar_idempotent'
    SCALAR_NON_IDEMPOTENT = 'scalar_non_idempotent'
    UNALLOCATED = 'unallocated'


PAGE_TYPE_EW = {
    PageType.VPU_EW8: 8,
    PageType.VPU_EW16: 16,
    PageType.VPU_EW32: 32,
    PageType.VPU_EW64: 64,
}


def allocate_page(lamlet: Oamlet, base_addr: int, page_idx: int, page_type: PageType):
    """Allocate a single page with the specified type."""
    page_bytes = lamlet.params.page_bytes
    page_addr = base_addr + page_idx * page_bytes
    g_addr = GlobalAddress(bit_addr=page_addr * 8, params=lamlet.params)

    if page_type == PageType.UNALLOCATED:
        return
    elif page_type in PAGE_TYPE_EW:
        ew = PAGE_TYPE_EW[page_type]
        ordering = Ordering(WordOrder.STANDARD, ew)
        lamlet.allocate_memory(g_addr, page_bytes, memory_type=MemoryType.VPU, ordering=ordering)
    elif page_type == PageType.SCALAR_IDEMPOTENT:
        lamlet.allocate_memory(g_addr, page_bytes, memory_type=MemoryType.SCALAR_IDEMPOTENT,
                               ordering=None)
    elif page_type == PageType.SCALAR_NON_IDEMPOTENT:
        lamlet.allocate_memory(g_addr, page_bytes, memory_type=MemoryType.SCALAR_NON_IDEMPOTENT,
                               ordering=None)


def generate_page_types(n_pages: int, rnd: Random) -> list[PageType]:
    """Generate a random mix of page types."""
    all_types = list(PageType)
    return [rnd.choice(all_types) for _ in range(n_pages)]


def generate_indices(vl: int, data_ew: int, n_pages: int, page_bytes: int, rnd: Random,
                     allow_duplicates: bool = False) -> list[int]:
    """Generate random byte offsets for indexed access.

    Args:
        vl: Vector length (number of indices to generate)
        data_ew: Data element width in bits
        n_pages: Number of pages in address space
        page_bytes: Bytes per page
        rnd: Random instance
        allow_duplicates: If True, may generate duplicate indices (20% of duplicate elements)

    Returns:
        List of byte offsets. May contain duplicates if allow_duplicates=True.
    """
    element_bytes = data_ew // 8
    max_offset = n_pages * page_bytes - element_bytes
    n_slots = max_offset // element_bytes + 1

    if not allow_duplicates:
        assert vl <= n_slots, f"Cannot generate {vl} unique indices with only {n_slots} slots"
        used = set()
        indices = []
        for _ in range(vl):
            for attempt in range(1000):
                offset = rnd.randint(0, max_offset // element_bytes) * element_bytes
                if offset not in used:
                    used.add(offset)
                    indices.append(offset)
                    break
            else:
                raise RuntimeError(f"Failed to generate unique index after 1000 attempts")
        return indices
    else:
        # Generate indices allowing duplicates
        # First generate some unique "base" offsets (about 60% of vl)
        n_unique = max(1, int(vl * 0.6))
        n_unique = min(n_unique, n_slots)  # Can't have more unique than slots

        used = set()
        base_offsets = []
        for _ in range(n_unique):
            for attempt in range(1000):
                offset = rnd.randint(0, max_offset // element_bytes) * element_bytes
                if offset not in used:
                    used.add(offset)
                    base_offsets.append(offset)
                    break
            else:
                break  # OK if we can't generate all unique

        # Fill the rest by sampling from base_offsets (creating duplicates)
        indices = list(base_offsets)
        while len(indices) < vl:
            indices.append(rnd.choice(base_offsets))

        # Shuffle to mix duplicates throughout
        rnd.shuffle(indices)
        return indices


async def setup_index_register(
    lamlet: Oamlet,
    index_reg: int,
    indices: list[int],
    index_ew: int,
    base_addr: int,
):
    """Write indices to memory and load into a vector register."""
    index_bytes = index_ew // 8
    index_mem_addr = base_addr + 0x200000
    page_bytes = lamlet.params.page_bytes

    index_size = len(indices) * index_bytes + 64
    n_pages = (max(1024, index_size) + page_bytes - 1) // page_bytes
    index_ordering = Ordering(WordOrder.STANDARD, index_ew)

    for page_idx in range(n_pages):
        page_addr = index_mem_addr + page_idx * page_bytes
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=page_addr * 8, params=lamlet.params),
            page_bytes, memory_type=MemoryType.VPU, ordering=index_ordering)

    for i, idx in enumerate(indices):
        addr = index_mem_addr + i * index_bytes
        await lamlet.set_memory(addr, idx.to_bytes(index_bytes, byteorder='little'))

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="setup_index")
    await lamlet.vload(
        vd=index_reg,
        addr=index_mem_addr,
        ordering=index_ordering,
        n_elements=len(indices),
        mask_reg=None,
        start_index=0,
        parent_span_id=span_id,
    )
    lamlet.monitor.finalize_children(span_id)


def random_stride(rnd: Random, element_bytes: int, page_bytes: int) -> int:
    """Generate a random stride with roughly logarithmic distribution.

    Ranges from element_bytes+1 to several page_bytes, using multiple linear
    ranges to approximate logarithmic distribution. We avoid stride == element_bytes
    because that triggers the unit-stride path which has incomplete scalar memory support.
    """
    range_choice = rnd.randint(0, 3)
    if range_choice == 0:
        # Small: element_bytes+1 to 4x element_bytes
        return rnd.randint(element_bytes + 1, element_bytes * 4)
    elif range_choice == 1:
        # Medium: 4x element_bytes to 64 bytes
        return rnd.randint(element_bytes * 4, max(element_bytes * 4, 64))
    elif range_choice == 2:
        # Large: 64 bytes to page_bytes
        return rnd.randint(64, page_bytes)
    else:
        # Very large: page_bytes to 4x page_bytes
        return rnd.randint(page_bytes, page_bytes * 4)


def max_vl_for_indexed(params: 'ZamletParams', data_ew: int, index_ew: int) -> int:
    """Calculate max vl that fits in available registers for indexed ops.

    Indexed ops need: ceil(vl/d) + ceil(vl/i) + 1 <= n_vregs
    where d = data elements per reg, i = index elements per reg,
    and ceil(vl/d) = (vl + d - 1) // d.

    Since (vl + d - 1) // d <= vl/d + 1:
        vl/d + vl/i + 2 + 1 <= n_vregs
        vl * (d + i) / (d * i) <= n_vregs - 3
        vl <= (n_vregs - 3) * d * i / (d + i)
    """
    vline_bits = params.vline_bytes * 8
    d = vline_bits // data_ew
    i = vline_bits // index_ew
    available = params.n_vregs - 3
    return available * d * i // (d + i)


def random_start_index(rnd: Random, vl: int) -> int:
    """Generate a random start_index for vstart testing.

    Returns 0 most of the time (80%), otherwise a random value in [1, vl-1].
    """
    if vl <= 1:
        return 0
    if rnd.randint(0, 4) == 0:  # 20% chance of non-zero
        return rnd.randint(1, vl - 1)
    return 0


def random_vl(rnd: Random, max_vl: int) -> int:
    """Generate a random vl with roughly logarithmic distribution.

    Favors smaller vl values while still testing larger ones.
    Uses fractional ranges of max_vl to adapt to any max_vl value.
    """
    # Define ranges as fractions: [1, max_vl/8], [max_vl/8, max_vl/4], etc.
    # This gives roughly logarithmic distribution that adapts to max_vl
    boundaries = [1, max(2, max_vl // 8), max(3, max_vl // 4),
                  max(4, max_vl // 2), max_vl]

    range_choice = rnd.randint(0, 3)
    lo = boundaries[range_choice]
    hi = boundaries[range_choice + 1]
    return rnd.randint(lo, hi)


def choose_mask_pattern(rnd: Random) -> str:
    """Choose a mask pattern type with weighted random selection.

    Returns one of: 'random', 'all_true', 'all_false', 'alternating', 'first_half'
    """
    choice = rnd.randint(0, 99)
    if choice < 50:
        return 'random'
    elif choice < 75:
        return 'all_true'
    elif choice < 85:
        return 'all_false'
    elif choice < 95:
        return 'alternating'
    else:
        return 'first_half'


def generate_mask_pattern(vl: int, pattern_type: str, rnd: Random) -> list[bool]:
    """Generate a mask bit pattern of the specified type.

    Args:
        vl: Vector length (number of mask bits to generate)
        pattern_type: One of 'random', 'all_true', 'all_false', 'alternating', 'first_half'
        rnd: Random instance for 'random' pattern

    Returns:
        List of bool mask bits
    """
    if pattern_type == 'random':
        return [rnd.choice([True, False]) for _ in range(vl)]
    elif pattern_type == 'all_true':
        return [True] * vl
    elif pattern_type == 'all_false':
        return [False] * vl
    elif pattern_type == 'alternating':
        return [(i % 2 == 0) for i in range(vl)]
    elif pattern_type == 'first_half':
        return [(i < vl // 2) for i in range(vl)]
    else:
        raise ValueError(f"Unknown mask pattern type: {pattern_type}")



