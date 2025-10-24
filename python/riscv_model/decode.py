"""RISC-V instruction decoder.

Decodes both 32-bit standard and 16-bit compressed RISC-V instructions.
"""

import logging
import struct

import decode_helpers
from instructions import Instruction
import instructions.base_integer as I
import instructions.compressed as C
import instructions.control_flow as CF
import instructions.system as S
import instructions.vector as V
import instructions.float as F
import instructions.memory as M
import instructions.multiply as MUL

decode_i_imm = decode_helpers.decode_i_imm
decode_b_imm = decode_helpers.decode_b_imm
decode_j_imm = decode_helpers.decode_j_imm
decode_u_imm = decode_helpers.decode_u_imm
decode_s_imm = decode_helpers.decode_s_imm
decode_cj_imm = decode_helpers.decode_cj_imm
decode_cb_imm = decode_helpers.decode_cb_imm
decode_caddi16sp_imm = decode_helpers.decode_caddi16sp_imm


logger = logging.getLogger(__name__)


def decode_compressed(instruction_bytes: bytes) -> Instruction:
    """Decode a 16-bit compressed RISC-V instruction."""
    inst = struct.unpack('<H', instruction_bytes[0:2])[0]

    opcode = inst & 0b11
    funct3 = (inst >> 13) & 0b111

    if opcode == 0b00:
        # Quadrant 0 - CL/CS format instructions
        if funct3 == 0b000:
            # C.ADDI4SPN - Add Immediate (scaled by 4) to SP
            rd_prime = (inst >> 2) & 0b111
            rd = 8 + rd_prime
            # Immediate encoding: nzuimm[5:4|9:6|2|3]
            # inst[12:11] -> uimm[5:4], inst[10:7] -> uimm[9:6],
            # inst[6] -> uimm[2], inst[5] -> uimm[3]
            uimm_5_4 = (inst >> 11) & 0b11
            uimm_9_6 = (inst >> 7) & 0b1111
            uimm_2 = (inst >> 6) & 0b1
            uimm_3 = (inst >> 5) & 0b1
            # Reconstruct the immediate (scaled by 4, so shift left by 2)
            nzuimm = (uimm_9_6 << 6) | (uimm_5_4 << 4) | (uimm_3 << 3) | (uimm_2 << 2)
            return C.CAddi4spn(rd=rd, imm=nzuimm)
        elif funct3 == 0b010:
            # C.LW - Load Word
            rd_prime = (inst >> 2) & 0b111
            rd = 8 + rd_prime
            rs1_prime = (inst >> 7) & 0b111
            rs1 = 8 + rs1_prime
            # Offset encoding: inst[5] -> offset[6], inst[12:10] -> offset[5:3],
            # inst[6] -> offset[2], bits 1:0 are 0 (scaled by 4)
            offset_bit_6 = (inst >> 5) & 0b1
            offset_bits_5_3 = (inst >> 10) & 0b111
            offset_bit_2 = (inst >> 6) & 0b1
            uimm_6_2 = (offset_bit_6 << 4) | (offset_bits_5_3 << 1) | offset_bit_2
            offset = uimm_6_2 << 2
            return C.CLw(rd=rd, rs1=rs1, offset=offset)

        elif funct3 == 0b011:
            # C.LD - Load Doubleword (RV64C)
            rd_prime = (inst >> 2) & 0b111
            rd = 8 + rd_prime
            rs1_prime = (inst >> 7) & 0b111
            rs1 = 8 + rs1_prime
            # Offset encoding: inst[5] -> offset[7], inst[12:10] -> offset[5:3],
            # inst[6] -> offset[6], bits 2:0 are 0 (scaled by 8)
            offset_bit_7_6 = (inst >> 5) & 0b11
            offset_bits_5_3 = (inst >> 10) & 0b111
            uimm_7_3 = (offset_bit_7_6 << 3) | offset_bits_5_3
            offset = uimm_7_3 << 3
            return C.CLd(rd=rd, rs1=rs1, offset=offset)

        elif funct3 == 0b110:
            # C.SW - Store Word
            rs2_prime = (inst >> 2) & 0b111
            rs2 = 8 + rs2_prime
            rs1_prime = (inst >> 7) & 0b111
            rs1 = 8 + rs1_prime
            # Same offset encoding as C.LW (scaled by 4)
            offset_bit_6 = (inst >> 5) & 0b1
            offset_bits_5_3 = (inst >> 10) & 0b111
            offset_bit_2 = (inst >> 6) & 0b1
            uimm_6_2 = (offset_bit_6 << 4) | (offset_bits_5_3 << 1) | offset_bit_2
            offset = uimm_6_2 << 2
            return C.CSw(rs1=rs1, rs2=rs2, offset=offset)

        elif funct3 == 0b111:
            # C.SD - Store Doubleword (RV64C)
            rs2_prime = (inst >> 2) & 0b111
            rs2 = 8 + rs2_prime
            rs1_prime = (inst >> 7) & 0b111
            rs1 = 8 + rs1_prime
            # Same offset encoding as C.LD (scaled by 8)
            offset_bit_7_6 = (inst >> 5) & 0b11
            offset_bits_5_3 = (inst >> 10) & 0b111
            uimm_7_3 = (offset_bit_7_6 << 3) | offset_bits_5_3
            offset = uimm_7_3 << 3
            return C.CSd(rs1=rs1, rs2=rs2, offset=offset)

    elif opcode == 0b01:
        if funct3 == 0b000:
            rd = (inst >> 7) & 0b11111
            imm_low = (inst >> 2) & 0b11111
            imm_high = (inst >> 12) & 0b1
            imm = imm_low | (imm_high << 5)

            if imm & 0b100000:
                imm = imm - 64

            if rd == 0:
                return C.CNop()
            else:
                return C.CAddi(rd=rd, imm=imm)

        elif funct3 == 0b001:
            # C.ADDIW - Add Immediate Word (RV64C)
            rd = (inst >> 7) & 0b11111
            imm_low = (inst >> 2) & 0b11111
            imm_high = (inst >> 12) & 0b1
            imm = imm_low | (imm_high << 5)

            if imm & 0b100000:
                imm = imm - 64

            return C.CAddiw(rd=rd, imm=imm)

        elif funct3 == 0b010:
            rd = (inst >> 7) & 0b11111
            imm_low = (inst >> 2) & 0b11111
            imm_high = (inst >> 12) & 0b1
            imm = imm_low | (imm_high << 5)

            if imm & 0b100000:
                imm = imm - 64

            return C.CLi(rd=rd, imm=imm)

        elif funct3 == 0b011:
            rd = (inst >> 7) & 0b11111

            if rd == 2:
                # C.ADDI16SP - Add immediate (scaled by 16) to stack pointer
                return C.CAddi16sp(imm=decode_caddi16sp_imm(inst))
            else:
                # C.LUI - Load upper immediate
                imm_low = (inst >> 2) & 0b11111
                imm_high = (inst >> 12) & 0b1
                nzimm = imm_low | (imm_high << 5)

                if nzimm & 0b100000:
                    nzimm = nzimm - 64

                return C.CLui(rd=rd, imm=nzimm)

        elif funct3 == 0b100:
            bits_12_10 = (inst >> 10) & 0b111
            rd_rs1_prime = (inst >> 7) & 0b111
            rd_rs1 = 8 + rd_rs1_prime
            rs2_prime = (inst >> 2) & 0b111
            rs2 = 8 + rs2_prime
            funct2 = (inst >> 5) & 0b11

            if bits_12_10 == 0b000:
                shamt_low = (inst >> 2) & 0b11111
                shamt_high = (inst >> 12) & 0b1
                shamt = shamt_low | (shamt_high << 5)
                return C.CSrli(rd_rs1=rd_rs1, shamt=shamt)
            elif bits_12_10 == 0b001:
                shamt_low = (inst >> 2) & 0b11111
                shamt_high = (inst >> 12) & 0b1
                shamt = shamt_low | (shamt_high << 5)
                return C.CSrai(rd_rs1=rd_rs1, shamt=shamt)
            elif bits_12_10 == 0b010:
                imm_low = (inst >> 2) & 0b11111
                imm_high = (inst >> 12) & 0b1
                imm = imm_low | (imm_high << 5)
                if imm & 0b100000:
                    imm = imm - 64
                return C.CAndi(rd_rs1=rd_rs1, imm=imm)
            elif bits_12_10 == 0b011:
                if funct2 == 0b00:
                    return C.CSub(rd_rs1=rd_rs1, rs2=rs2)
                elif funct2 == 0b01:
                    return C.CXor(rd_rs1=rd_rs1, rs2=rs2)
                elif funct2 == 0b10:
                    return C.COr(rd_rs1=rd_rs1, rs2=rs2)
                elif funct2 == 0b11:
                    return C.CAnd(rd_rs1=rd_rs1, rs2=rs2)
            elif bits_12_10 == 0b111:
                if funct2 == 0b00:
                    return C.CSubw(rd_rs1=rd_rs1, rs2=rs2)
                elif funct2 == 0b01:
                    return C.CAddw(rd_rs1=rd_rs1, rs2=rs2)

        elif funct3 == 0b101:
            return C.CJ(offset=decode_cj_imm(inst))

        elif funct3 == 0b110 or funct3 == 0b111:
            rs1_prime = (inst >> 7) & 0b111
            rs1 = 8 + rs1_prime
            offset = decode_cb_imm(inst)

            if funct3 == 0b110:
                return C.CBeqz(rs1=rs1, offset=offset)
            else:
                return C.CBnez(rs1=rs1, offset=offset)

    elif opcode == 0b10:
        if funct3 == 0b000:
            rd = (inst >> 7) & 0b11111
            shamt_low = (inst >> 2) & 0b11111
            shamt_high = (inst >> 12) & 0b1
            shamt = shamt_low | (shamt_high << 5)
            return C.CSlli(rd=rd, shamt=shamt)

        elif funct3 == 0b010:
            # C.LWSP - Load Word from Stack Pointer
            rd = (inst >> 7) & 0b11111
            # Offset encoding: inst[3:2|12] -> offset[5], inst[6:4] -> offset[4:2]
            # uimm[5|4:2|7:6] = inst[12|6:4|3:2] scaled by 4
            offset = ((inst >> 4) & 0b111) << 2 | ((inst >> 12) & 0b1) << 5 | ((inst >> 2) & 0b11) << 6
            return C.CLwsp(rd=rd, offset=offset)

        elif funct3 == 0b011:
            # C.LDSP - Load Doubleword from Stack Pointer (RV64C)
            rd = (inst >> 7) & 0b11111
            # Offset encoding: inst[4:2|12] -> offset[5], inst[6:5] -> offset[4:3]
            # uimm[5|4:3|8:6] = inst[12|6:5|4:2] scaled by 8
            offset = ((inst >> 5) & 0b11) << 3 | ((inst >> 12) & 0b1) << 5 | ((inst >> 2) & 0b111) << 6
            return C.CLdsp(rd=rd, offset=offset)

        elif funct3 == 0b100:
            bit12 = (inst >> 12) & 0b1
            rd_rs1 = (inst >> 7) & 0b11111
            rs2 = (inst >> 2) & 0b11111

            if bit12 == 0 and rs2 == 0 and rd_rs1 != 0:
                return C.CJr(rs1=rd_rs1)
            elif bit12 == 0 and rs2 != 0:
                return C.CMv(rd=rd_rs1, rs2=rs2)
            elif bit12 == 1 and rs2 == 0 and rd_rs1 == 0:
                return C.CEbreak()
            elif bit12 == 1 and rs2 == 0 and rd_rs1 != 0:
                return C.CJalr(rs1=rd_rs1)
            elif bit12 == 1 and rs2 != 0:
                return C.CAdd(rd=rd_rs1, rs2=rs2)

        elif funct3 == 0b110:
            # C.SWSP - Store Word to Stack Pointer
            rs2 = (inst >> 2) & 0b11111
            # Offset encoding: inst[8:7|12:9] -> uimm[5:2|7:6]
            # uimm[5:2|7:6] = inst[12:9|8:7] scaled by 4
            offset = ((inst >> 9) & 0b1111) << 2 | ((inst >> 7) & 0b11) << 6
            return C.CSwsp(rs2=rs2, offset=offset)

        elif funct3 == 0b111:
            rs2 = (inst >> 2) & 0b11111
            # C.SDSP offset encoding: inst[12:10] -> offset[5:3], inst[9:7] -> offset[8:6]
            offset = ((inst >> 10) & 0b111) << 3 | ((inst >> 7) & 0b111) << 6
            return C.CSdsp(rs2=rs2, offset=offset)

    logger.error(f'Unknown compressed instruction: 0x{inst:04x} '
                 f'(binary: {inst:016b}, opcode: {opcode:02b}, funct3: {funct3:03b})')
    raise ValueError(f'Unknown compressed instruction: 0x{inst:04x}')


def is_compressed(instruction_bytes: bytes) -> bool:
    """Check if instruction is compressed (16-bit) or standard (32-bit)."""
    return (instruction_bytes[0] & 0b11) != 0b11


def decode_standard(instruction_bytes: bytes) -> Instruction:
    """Decode a 32-bit standard RISC-V instruction."""
    inst = struct.unpack('<I', instruction_bytes[0:4])[0]

    opcode = inst & 0x7f
    rd = (inst >> 7) & 0x1f
    funct3 = (inst >> 12) & 0x7
    rs1 = (inst >> 15) & 0x1f
    rs2 = (inst >> 20) & 0x1f
    funct7 = (inst >> 25) & 0x7f
    imm_i = (inst >> 20) & 0xfff
    csr = (inst >> 20) & 0xfff

    if opcode == 0x13:
        if funct3 == 0x0:
            return I.Addi(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x1:
            shamt = (inst >> 20) & 0x3f
            return I.Slli(rd=rd, rs1=rs1, shamt=shamt)
        elif funct3 == 0x2:
            return I.Slti(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x3:
            return I.Sltiu(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x4:
            return I.Xori(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x6:
            return I.Ori(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x7:
            return I.Andi(rd=rd, rs1=rs1, imm=decode_i_imm(inst))

    elif opcode == 0x53:
        funct7_full = (inst >> 25) & 0x7f
        funct5 = (inst >> 27) & 0x1f
        fmt = (inst >> 25) & 0x3

        if funct7_full == 0x78 and funct3 == 0x0:
            return F.FmvWX(fd=rd, rs1=rs1)
        elif funct7_full == 0x08 and fmt == 0x0:
            return F.FsubS(fd=rd, rs1=rs1, rs2=rs2)
        elif funct7_full == 0x08 and fmt == 0x1:
            return F.FsubD(fd=rd, rs1=rs1, rs2=rs2)
        elif funct7_full == 0x50 and funct3 == 0x2:
            return F.FeqS(rd=rd, rs1=rs1, rs2=rs2)
        elif funct7_full == 0x50 and funct3 == 0x0:
            return F.FleS(rd=rd, rs1=rs1, rs2=rs2)
        elif funct7_full == 0x51 and funct3 == 0x0:
            return F.FleD(rd=rd, rs1=rs1, rs2=rs2)
        elif funct7_full == 0x10 and rs2 == rs1 and fmt == 0x0:
            return F.FabsS(fd=rd, rs1=rs1)
        elif funct7_full == 0x11 and rs2 == rs1 and fmt == 0x0:
            return F.FabsD(fd=rd, rs1=rs1)

    elif opcode == 0x17:
        return CF.Auipc(rd=rd, imm=decode_u_imm(inst))

    elif opcode == 0x37:
        return I.Lui(rd=rd, imm=decode_u_imm(inst))

    elif opcode == 0x6f:
        return CF.Jal(rd=rd, imm=decode_j_imm(inst))

    elif opcode == 0x1b:
        if funct3 == 0x0:
            return I.Addiw(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x1:
            shamt = (inst >> 20) & 0x1f
            return I.Slliw(rd=rd, rs1=rs1, shamt=shamt)
        elif funct3 == 0x5:
            shamt = (inst >> 20) & 0x1f
            if funct7 == 0x00:
                return I.Srliw(rd=rd, rs1=rs1, shamt=shamt)
            elif funct7 == 0x20:
                return I.Sraiw(rd=rd, rs1=rs1, shamt=shamt)

    elif opcode == 0x73:
        if funct3 == 0x1:
            return S.Csrrw(rd=rd, rs1=rs1, csr=csr)
        elif funct3 == 0x2:
            return S.Csrrs(rd=rd, rs1=rs1, csr=csr)

    elif opcode == 0x33:
        if funct3 == 0x0 and funct7 == 0x00:
            return I.Add(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x0 and funct7 == 0x01:
            return MUL.Mul(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x0 and funct7 == 0x20:
            return I.Sub(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x1 and funct7 == 0x01:
            return MUL.Mulh(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x2 and funct7 == 0x00:
            return I.Slt(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x2 and funct7 == 0x01:
            return MUL.Mulhsu(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x3 and funct7 == 0x00:
            return I.Sltu(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x3 and funct7 == 0x01:
            return MUL.Mulhu(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x4 and funct7 == 0x00:
            return I.Xor(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x4 and funct7 == 0x01:
            return MUL.Div(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x5 and funct7 == 0x01:
            return MUL.Divu(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x6 and funct7 == 0x00:
            return I.Or(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x6 and funct7 == 0x01:
            return MUL.Rem(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x7 and funct7 == 0x00:
            return I.And(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x7 and funct7 == 0x01:
            return MUL.Remu(rd=rd, rs1=rs1, rs2=rs2)

    elif opcode == 0x3b:
        if funct3 == 0x0 and funct7 == 0x00:
            return I.Addw(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x0 and funct7 == 0x20:
            return I.Subw(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x1 and funct7 == 0x00:
            return I.Sllw(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x5 and funct7 == 0x00:
            return I.Srlw(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x5 and funct7 == 0x20:
            return I.Sraw(rd=rd, rs1=rs1, rs2=rs2)

    elif opcode == 0x03:
        imm = decode_i_imm(inst)
        if funct3 == 0x0:
            return M.Lb(rd=rd, rs1=rs1, imm=imm)
        elif funct3 == 0x1:
            return M.Lh(rd=rd, rs1=rs1, imm=imm)
        elif funct3 == 0x2:
            return M.Lw(rd=rd, rs1=rs1, imm=imm)
        elif funct3 == 0x3:
            return M.Ld(rd=rd, rs1=rs1, imm=imm)
        elif funct3 == 0x4:
            return M.Lbu(rd=rd, rs1=rs1, imm=imm)
        elif funct3 == 0x5:
            return M.Lhu(rd=rd, rs1=rs1, imm=imm)
        elif funct3 == 0x6:
            return M.Lwu(rd=rd, rs1=rs1, imm=imm)

    elif opcode == 0x07:
        mop = (inst >> 26) & 0x3
        vm = (inst >> 25) & 0x1
        width = funct3
        if mop == 0x0 and width == 0x6:
            return V.Vle32V(vd=rd, rs1=rs1, vm=vm)

    elif opcode == 0x23:
        imm = decode_s_imm(inst)
        if funct3 == 0x0:
            return M.Sb(rs1=rs1, rs2=rs2, imm=imm)
        elif funct3 == 0x1:
            return M.Sh(rs1=rs1, rs2=rs2, imm=imm)
        elif funct3 == 0x2:
            return M.Sw(rs1=rs1, rs2=rs2, imm=imm)
        elif funct3 == 0x3:
            return M.Sd(rs1=rs1, rs2=rs2, imm=imm)

    elif opcode == 0x27:
        mop = (inst >> 26) & 0x3
        vm = (inst >> 25) & 0x1
        width = funct3
        vs3 = rd
        if mop == 0x0 and width == 0x6:
            return V.Vse32V(vs3=vs3, rs1=rs1, vm=vm)

    elif opcode == 0x63:
        imm = decode_b_imm(inst)
        if funct3 == 0x0:
            return CF.Beq(rs1=rs1, rs2=rs2, imm=imm)
        elif funct3 == 0x1:
            return CF.Bne(rs1=rs1, rs2=rs2, imm=imm)
        elif funct3 == 0x4:
            return CF.Blt(rs1=rs1, rs2=rs2, imm=imm)
        elif funct3 == 0x5:
            return CF.Bge(rs1=rs1, rs2=rs2, imm=imm)
        elif funct3 == 0x6:
            return CF.Bltu(rs1=rs1, rs2=rs2, imm=imm)
        elif funct3 == 0x7:
            return CF.Bgeu(rs1=rs1, rs2=rs2, imm=imm)

    elif opcode == 0x0f:
        if funct3 == 0x0:
            pred = (inst >> 24) & 0xf
            succ = (inst >> 20) & 0xf
            return S.Fence(pred=pred, succ=succ)

    elif opcode == 0x07:
        vm = (inst >> 25) & 0x1
        mop = (inst >> 26) & 0x3
        width = funct3
        if mop == 0 and width == 6:
            return V.Vle32V(vd=rd, rs1=rs1, vm=vm)
        elif width == 2:
            return F.Flw(fd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif width == 3:
            return F.Fld(fd=rd, rs1=rs1, imm=decode_i_imm(inst))

    elif opcode == 0x27:
        vm = (inst >> 25) & 0x1
        mop = (inst >> 26) & 0x3
        width = funct3
        vs3 = rd
        if mop == 0 and width == 6:
            return V.Vse32V(vs3=vs3, rs1=rs1, vm=vm)
        elif width == 2:
            return F.Fsw(rs2=rs2, rs1=rs1, imm=decode_s_imm(inst))
        elif width == 3:
            return F.Fsd(rs2=rs2, rs1=rs1, imm=decode_s_imm(inst))

    elif opcode == 0x57:
        bit31 = (inst >> 31) & 0x1
        funct6 = (inst >> 26) & 0x3f
        vm = (inst >> 25) & 0x1
        vs2 = rs2

        if bit31 == 0 and funct3 == 0x7:
            vtypei = (inst >> 20) & 0x7ff
            return V.Vsetvli(rd=rd, rs1=rs1, vtypei=vtypei)
        elif funct6 == 0x2c and funct3 == 0x5:
            return V.VfmaccVf(vd=rd, rs1=rs1, vs2=vs2, vm=vm)
        elif funct6 == 0x00 and funct3 == 0x4:
            return V.VaddVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm)

    logger.error(f'Unknown 32-bit instruction: 0x{inst:08x} '
                 f'(opcode: 0x{opcode:02x}, funct3: {funct3:03b}, funct7: {funct7:07b}, '
                 f'rd: {rd}, rs1: {rs1}, rs2: {rs2}, imm_i: {imm_i}, csr: 0x{csr:03x})')
    raise ValueError(f'Unknown 32-bit instruction: 0x{inst:08x}')


def decode(instruction_bytes: bytes) -> Instruction:
    """Decode a RISC-V instruction from bytes."""
    if is_compressed(instruction_bytes):
        return decode_compressed(instruction_bytes)
    else:
        return decode_standard(instruction_bytes)
