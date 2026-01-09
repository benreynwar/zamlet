"""RISC-V instruction encoding utilities.

Provides functions to encode RISC-V vector instructions for use in tests.
"""


def encode_vle(vd: int, rs1: int, width: int = 32, vm: int = 1, nf: int = 0) -> int:
    """Encode a unit-stride vector load instruction (vle).

    vle<width>.v vd, (rs1)

    Args:
        vd: Destination vector register (0-31)
        rs1: Base address register (0-31)
        width: Element width in bits (8, 16, 32, 64)
        vm: Mask mode (1=unmasked, 0=masked with v0)
        nf: Number of fields minus 1 for segment loads (0 for regular vle)

    Returns:
        32-bit encoded instruction
    """
    opcode = 0b0000111
    width_field = {8: 0b000, 16: 0b101, 32: 0b110, 64: 0b111}[width]
    mop = 0b00  # unit-stride
    mew = 0
    lumop = 0

    inst = ((nf & 0x7) << 29) | (mew << 28) | (mop << 26) | ((vm & 1) << 25) | \
           (lumop << 20) | ((rs1 & 0x1f) << 15) | (width_field << 12) | \
           ((vd & 0x1f) << 7) | opcode
    return inst


def encode_vse(vs3: int, rs1: int, width: int = 32, vm: int = 1, nf: int = 0) -> int:
    """Encode a unit-stride vector store instruction (vse).

    vse<width>.v vs3, (rs1)

    Args:
        vs3: Source vector register (0-31)
        rs1: Base address register (0-31)
        width: Element width in bits (8, 16, 32, 64)
        vm: Mask mode (1=unmasked, 0=masked with v0)
        nf: Number of fields minus 1 for segment stores (0 for regular vse)

    Returns:
        32-bit encoded instruction
    """
    opcode = 0b0100111
    width_field = {8: 0b000, 16: 0b101, 32: 0b110, 64: 0b111}[width]
    mop = 0b00  # unit-stride
    mew = 0
    sumop = 0

    inst = ((nf & 0x7) << 29) | (mew << 28) | (mop << 26) | ((vm & 1) << 25) | \
           (sumop << 20) | ((rs1 & 0x1f) << 15) | (width_field << 12) | \
           ((vs3 & 0x1f) << 7) | opcode
    return inst


def encode_vlse(vd: int, rs1: int, rs2: int, width: int = 32, vm: int = 1) -> int:
    """Encode a strided vector load instruction (vlse).

    vlse<width>.v vd, (rs1), rs2

    Args:
        vd: Destination vector register (0-31)
        rs1: Base address register (0-31)
        rs2: Stride register (0-31)
        width: Element width in bits (8, 16, 32, 64)
        vm: Mask mode (1=unmasked, 0=masked with v0)

    Returns:
        32-bit encoded instruction
    """
    opcode = 0b0000111
    width_field = {8: 0b000, 16: 0b101, 32: 0b110, 64: 0b111}[width]
    mop = 0b10  # strided
    nf = 0
    mew = 0

    inst = ((nf & 0x7) << 29) | (mew << 28) | (mop << 26) | ((vm & 1) << 25) | \
           ((rs2 & 0x1f) << 20) | ((rs1 & 0x1f) << 15) | (width_field << 12) | \
           ((vd & 0x1f) << 7) | opcode
    return inst


def encode_vsse(vs3: int, rs1: int, rs2: int, width: int = 32, vm: int = 1) -> int:
    """Encode a strided vector store instruction (vsse).

    vsse<width>.v vs3, (rs1), rs2

    Args:
        vs3: Source vector register (0-31)
        rs1: Base address register (0-31)
        rs2: Stride register (0-31)
        width: Element width in bits (8, 16, 32, 64)
        vm: Mask mode (1=unmasked, 0=masked with v0)

    Returns:
        32-bit encoded instruction
    """
    opcode = 0b0100111
    width_field = {8: 0b000, 16: 0b101, 32: 0b110, 64: 0b111}[width]
    mop = 0b10  # strided
    nf = 0
    mew = 0

    inst = ((nf & 0x7) << 29) | (mew << 28) | (mop << 26) | ((vm & 1) << 25) | \
           ((rs2 & 0x1f) << 20) | ((rs1 & 0x1f) << 15) | (width_field << 12) | \
           ((vs3 & 0x1f) << 7) | opcode
    return inst
