"""Helper functions for decoding RISC-V instruction immediates."""


def decode_i_imm(inst: int) -> int:
    """Decode I-type immediate from instruction."""
    imm = (inst >> 20) & 0xfff
    if imm & 0x800:
        imm = imm - 0x1000
    return imm


def decode_b_imm(inst: int) -> int:
    """Decode B-type immediate from instruction."""
    imm_11 = (inst >> 7) & 0x1
    imm_4_1 = (inst >> 8) & 0xf
    imm_10_5 = (inst >> 25) & 0x3f
    imm_12 = (inst >> 31) & 0x1
    imm = (imm_12 << 12) | (imm_11 << 11) | (imm_10_5 << 5) | (imm_4_1 << 1)
    if imm & 0x1000:
        imm = imm - 0x2000
    return imm


def decode_j_imm(inst: int) -> int:
    """Decode J-type immediate from instruction."""
    imm_20 = (inst >> 31) & 0x1
    imm_10_1 = (inst >> 21) & 0x3ff
    imm_11 = (inst >> 20) & 0x1
    imm_19_12 = (inst >> 12) & 0xff
    imm = (imm_20 << 20) | (imm_19_12 << 12) | (imm_11 << 11) | (imm_10_1 << 1)
    if imm & 0x100000:
        imm = imm - 0x200000
    return imm


def decode_u_imm(inst: int) -> int:
    """Decode U-type immediate (20-bit, sign-extended) from instruction."""
    imm = (inst >> 12) & 0xfffff
    if imm & 0x80000:
        imm = imm - 0x100000
    return imm


def decode_cj_imm(inst: int) -> int:
    """Decode CJ-format immediate from compressed instruction."""
    offset_11 = (inst >> 12) & 0b1
    offset_4 = (inst >> 11) & 0b1
    offset_9_8 = (inst >> 9) & 0b11
    offset_10 = (inst >> 8) & 0b1
    offset_6 = (inst >> 7) & 0b1
    offset_7 = (inst >> 6) & 0b1
    offset_3_1 = (inst >> 3) & 0b111
    offset_5 = (inst >> 2) & 0b1
    offset = (offset_11 << 11) | (offset_10 << 10) | (offset_9_8 << 8) | \
             (offset_7 << 7) | (offset_6 << 6) | (offset_5 << 5) | \
             (offset_4 << 4) | (offset_3_1 << 1)
    if offset & 0x800:
        offset = offset - 0x1000
    return offset


def decode_cb_imm(inst: int) -> int:
    """Decode CB-format immediate from compressed instruction (for branches)."""
    offset_8 = (inst >> 12) & 0b1
    offset_4_3 = (inst >> 10) & 0b11
    offset_7_6 = (inst >> 5) & 0b11
    offset_2_1 = (inst >> 3) & 0b11
    offset_5 = (inst >> 2) & 0b1
    offset = (offset_8 << 8) | (offset_7_6 << 6) | (offset_5 << 5) | \
             (offset_4_3 << 3) | (offset_2_1 << 1)
    if offset & 0x100:
        offset = offset - 0x200
    return offset


def decode_s_imm(inst: int) -> int:
    """Decode S-type immediate from instruction."""
    imm_4_0 = (inst >> 7) & 0x1f
    imm_11_5 = (inst >> 25) & 0x7f
    imm = (imm_11_5 << 5) | imm_4_0
    if imm & 0x800:
        imm = imm - 0x1000
    return imm


def decode_caddi16sp_imm(inst: int) -> int:
    """Decode C.ADDI16SP immediate from compressed instruction.

    nzimm[9] = inst[12]
    nzimm[4|6|8:7|5] = inst[6:2]
    Immediate is scaled by 16, range [-512, 496].
    """
    imm_9 = (inst >> 12) & 1
    imm_4 = (inst >> 6) & 1
    imm_6 = (inst >> 5) & 1
    imm_8_7 = (inst >> 3) & 0b11
    imm_5 = (inst >> 2) & 1

    nzimm = (imm_9 << 9) | (imm_8_7 << 7) | (imm_6 << 6) | (imm_5 << 5) | (imm_4 << 4)

    # Sign extend from bit 9
    if nzimm & (1 << 9):
        nzimm = nzimm - (1 << 10)

    return nzimm
