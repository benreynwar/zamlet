"""RISC-V instruction decoder.

Decodes both 32-bit standard and 16-bit compressed RISC-V instructions.
"""

import logging
import struct

from zamlet import decode_helpers
from zamlet.instructions import Instruction
from zamlet.instructions import base_integer as I
from zamlet.instructions import compressed as C
from zamlet.instructions import control_flow as CF
from zamlet.instructions import system as S
from zamlet.instructions import vector as V
from zamlet.instructions import float as F
from zamlet.instructions import memory as M
from zamlet.instructions import multiply as MUL
from zamlet.instructions import custom as CUSTOM
from zamlet.kamlet import kinstructions
from zamlet.transactions.reg_slide import SlideDirection

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
        elif funct3 == 0b001:
            # C.FLD - Floating-Point Load Double (RV32DC/RV64DC)
            fd_prime = (inst >> 2) & 0b111
            fd = 8 + fd_prime
            rs1_prime = (inst >> 7) & 0b111
            rs1 = 8 + rs1_prime
            # Offset encoding: uimm[5:3] at inst[12:10], uimm[7:6] at inst[6:5]
            offset_bits_5_3 = (inst >> 10) & 0b111
            offset_bit_7_6 = (inst >> 5) & 0b11
            uimm_7_3 = (offset_bit_7_6 << 3) | offset_bits_5_3
            offset = uimm_7_3 << 3  # Scaled by 8
            return C.CFld(fd=fd, rs1=rs1, offset=offset)
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

        elif funct3 == 0b101:
            # C.FSD - Floating-Point Store Double (RV32DC/RV64DC)
            fs2_prime = (inst >> 2) & 0b111
            fs2 = 8 + fs2_prime
            rs1_prime = (inst >> 7) & 0b111
            rs1 = 8 + rs1_prime
            # Offset encoding: uimm[5:3] at inst[12:10], uimm[7:6] at inst[6:5]
            offset_bits_5_3 = (inst >> 10) & 0b111
            offset_bit_7_6 = (inst >> 5) & 0b11
            uimm_7_3 = (offset_bit_7_6 << 3) | offset_bits_5_3
            offset = uimm_7_3 << 3  # Scaled by 8
            return C.CFsd(rs1=rs1, fs2=fs2, offset=offset)

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

            if bits_12_10 == 0b000 or bits_12_10 == 0b100:
                # C.SRLI: bits[11:10]=00, bit[12] is part of shamt
                shamt_low = (inst >> 2) & 0b11111
                shamt_high = (inst >> 12) & 0b1
                shamt = shamt_low | (shamt_high << 5)
                return C.CSrli(rd_rs1=rd_rs1, shamt=shamt)
            elif bits_12_10 == 0b001 or bits_12_10 == 0b101:
                # C.SRAI: bits[11:10]=01, bit[12] is part of shamt
                shamt_low = (inst >> 2) & 0b11111
                shamt_high = (inst >> 12) & 0b1
                shamt = shamt_low | (shamt_high << 5)
                return C.CSrai(rd_rs1=rd_rs1, shamt=shamt)
            elif bits_12_10 == 0b010 or bits_12_10 == 0b110:
                # C.ANDI: bits[11:10]=10, bit[12] is part of immediate
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

        elif funct3 == 0b001:
            # C.FLDSP - Floating-Point Load Double from Stack Pointer (RV32DC/RV64DC)
            fd = (inst >> 7) & 0b11111
            # Offset encoding: offset[5|4:3|8:6] = inst[12|6:5|4:2], scaled by 8
            offset = ((inst >> 12) & 0b1) << 5 | ((inst >> 5) & 0b11) << 3 | ((inst >> 2) & 0b111) << 6
            return C.CFldsp(fd=fd, offset=offset)

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

        elif funct3 == 0b101:
            # C.FSDSP - Floating-Point Store Double to Stack Pointer (RV32DC/RV64DC)
            fs2 = (inst >> 2) & 0b11111
            # Offset encoding: uimm[5:3|8:6] at inst[12:7], scaled by 8
            offset = ((inst >> 7) & 0b111) << 6 | ((inst >> 10) & 0b111) << 3
            return C.CFsdsp(fs2=fs2, offset=offset)

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

    if opcode == 0x03:
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

    # Custom-0 opcode: VPU optimization hints (I-type encoding, funct3 selects instruction)
    #   funct3=0: SetIndexBound — bound indexed load/store range to skip fault sync
    #   funct3=1: BeginWriteset — open shared writeset scope to skip completion sync
    #   funct3=2: EndWriteset — close writeset scope
    #   funct3=3: Mark — broadcast a trace marker to every kamlet
    elif opcode == 0x0b:
        imm = decode_i_imm(inst)
        if funct3 == 0x0:
            return CUSTOM.SetIndexBound(rs1=rs1, imm=imm)
        elif funct3 == 0x1:
            return CUSTOM.BeginWriteset()
        elif funct3 == 0x2:
            return CUSTOM.EndWriteset()
        elif funct3 == 0x3:
            return CUSTOM.Mark(rs1=rs1, imm=imm)

    elif opcode == 0x07:
        width = funct3
        # Width field discriminates vector vs scalar FP loads.
        # Vector: 000(8b), 101(16b), 110(32b), 111(64b)
        # Scalar FP: 001(flh), 010(flw), 011(fld), 100(flq)
        vector_width_map = {0x0: 8, 0x5: 16, 0x6: 32, 0x7: 64}
        if width in vector_width_map:
            nf = (inst >> 29) & 0x7
            mop = (inst >> 26) & 0x3
            vm = (inst >> 25) & 0x1
            lumop = rs2
            ew = vector_width_map[width]
            if mop == 0x0 and lumop == 8:
                # Whole register load (vl1re8, vl2re8, vl4re8, vl8re8, etc.)
                nreg_map = {0: 1, 1: 2, 3: 4, 7: 8}
                assert nf in nreg_map, f"Invalid nf={nf} for whole register load"
                return V.VlrV(vd=rd, rs1=rs1, nreg=nreg_map[nf])
            elif mop == 0x0:
                # Unit-stride load
                if nf == 0:
                    return V.VleV(vd=rd, rs1=rs1, vm=vm, element_width=ew)
                else:
                    return V.VlsegV(
                        vd=rd, rs1=rs1, vm=vm, element_width=ew, nf=nf + 1,
                    )
            elif mop == 0x1:
                # Indexed-unordered load (vluxei*.v)
                return V.VIndexedLoad(
                    vd=rd, rs1=rs1, vs2=rs2, vm=vm, index_width=ew, ordered=False,
                )
            elif mop == 0x2:
                # Constant-stride load (vlse*.v)
                return V.VlseV(vd=rd, rs1=rs1, rs2=rs2, vm=vm, element_width=ew)
            elif mop == 0x3:
                # Indexed-ordered load (vloxei*.v)
                return V.VIndexedLoad(
                    vd=rd, rs1=rs1, vs2=rs2, vm=vm, index_width=ew, ordered=True,
                )
        elif width == 0x2:
            return F.Flw(fd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif width == 0x3:
            return F.Fld(fd=rd, rs1=rs1, imm=decode_i_imm(inst))

    elif opcode == 0x0f:
        if funct3 == 0x0:
            pred = (inst >> 24) & 0xf
            succ = (inst >> 20) & 0xf
            return S.Fence(pred=pred, succ=succ)

    elif opcode == 0x13:
        if funct3 == 0x0:
            return I.Addi(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x1:
            shamt = imm_i & 0x3f
            return I.Slli(rd=rd, rs1=rs1, shamt=shamt)
        elif funct3 == 0x2:
            return I.Slti(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x3:
            return I.Sltiu(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x4:
            return I.Xori(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x5:
            shamt = imm_i & 0x3f
            if funct7 & 0x20:  # bit 30 encodes shift type
                return I.Srai(rd=rd, rs1=rs1, shamt=shamt)
            else:
                return I.Srli(rd=rd, rs1=rs1, shamt=shamt)
        elif funct3 == 0x6:
            return I.Ori(rd=rd, rs1=rs1, imm=decode_i_imm(inst))
        elif funct3 == 0x7:
            return I.Andi(rd=rd, rs1=rs1, imm=decode_i_imm(inst))

    elif opcode == 0x17:
        return CF.Auipc(rd=rd, imm=decode_u_imm(inst))

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
        width = funct3
        vs3 = rd
        vector_width_map = {0x0: 8, 0x5: 16, 0x6: 32, 0x7: 64}
        if width in vector_width_map:
            nf = (inst >> 29) & 0x7
            mop = (inst >> 26) & 0x3
            vm = (inst >> 25) & 0x1
            sumop = rs2
            ew = vector_width_map[width]
            if mop == 0x0 and sumop == 8:
                # Whole register store (vs1r, vs2r, vs4r, vs8r)
                nreg_map = {0: 1, 1: 2, 3: 4, 7: 8}
                assert nf in nreg_map, f"Invalid nf={nf} for whole register store"
                return V.VsrV(vs3=vs3, rs1=rs1, nreg=nreg_map[nf])
            elif mop == 0x0:
                # Unit-stride store
                if nf == 0:
                    return V.VseV(vs3=vs3, rs1=rs1, vm=vm, element_width=ew)
                else:
                    return V.VssegV(
                        vs3=vs3, rs1=rs1, vm=vm, element_width=ew, nf=nf + 1,
                    )
            elif mop == 0x1:
                # Indexed-unordered store (vsuxei*.v)
                return V.VIndexedStore(
                    vs3=vs3, rs1=rs1, vs2=rs2, vm=vm, index_width=ew, ordered=False,
                )
            elif mop == 0x2:
                # Constant-stride store (vsse*.v)
                return V.VsseV(
                    vs3=vs3, rs1=rs1, rs2=rs2, vm=vm, element_width=ew,
                )
            elif mop == 0x3:
                # Indexed-ordered store (vsoxei*.v)
                return V.VIndexedStore(
                    vs3=vs3, rs1=rs1, vs2=rs2, vm=vm, index_width=ew, ordered=True,
                )
        elif width == 0x2:
            return F.Fsw(rs2=rs2, rs1=rs1, imm=decode_s_imm(inst))
        elif width == 0x3:
            return F.Fsd(rs2=rs2, rs1=rs1, imm=decode_s_imm(inst))

    elif opcode == 0x33:
        if funct3 == 0x0 and funct7 == 0x00:
            return I.Add(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x0 and funct7 == 0x01:
            return MUL.Mul(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x0 and funct7 == 0x20:
            return I.Sub(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x1 and funct7 == 0x00:
            return I.Sll(rd=rd, rs1=rs1, rs2=rs2)
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
        elif funct3 == 0x5 and funct7 == 0x00:
            return I.Srl(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x5 and funct7 == 0x01:
            return MUL.Divu(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x5 and funct7 == 0x20:
            return I.Sra(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x6 and funct7 == 0x00:
            return I.Or(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x6 and funct7 == 0x01:
            return MUL.Rem(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x7 and funct7 == 0x00:
            return I.And(rd=rd, rs1=rs1, rs2=rs2)
        elif funct3 == 0x7 and funct7 == 0x01:
            return MUL.Remu(rd=rd, rs1=rs1, rs2=rs2)

    elif opcode == 0x37:
        return I.Lui(rd=rd, imm=decode_u_imm(inst))

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
        elif funct7 == 0x01:
            if funct3 == 0x0:
                return MUL.Mulw(rd=rd, rs1=rs1, rs2=rs2)
            elif funct3 == 0x4:
                return MUL.Divw(rd=rd, rs1=rs1, rs2=rs2)
            elif funct3 == 0x5:
                return MUL.Divuw(rd=rd, rs1=rs1, rs2=rs2)
            elif funct3 == 0x6:
                return MUL.Remw(rd=rd, rs1=rs1, rs2=rs2)
            elif funct3 == 0x7:
                return MUL.Remuw(rd=rd, rs1=rs1, rs2=rs2)

    elif opcode in (0x43, 0x47, 0x4b, 0x4f):
        fmt = (inst >> 25) & 0x3
        rs3 = (inst >> 27) & 0x1f
        if fmt in (0x0, 0x1):
            is_double = (fmt == 0x1)
            fma_op = {
                0x43: F.FmaOp.FMADD,
                0x47: F.FmaOp.FMSUB,
                0x4b: F.FmaOp.FNMSUB,
                0x4f: F.FmaOp.FNMADD,
            }[opcode]
            return F.FMA(fd=rd, rs1=rs1, rs2=rs2, rs3=rs3, op=fma_op, is_double=is_double)

    elif opcode == 0x53:
        funct7_full = (inst >> 25) & 0x7f
        fmt = funct7_full & 0x1
        is_double = (fmt == 0x1)
        arith_binary = {
            0x00: F.FArithOp.FADD, 0x01: F.FArithOp.FADD,
            0x04: F.FArithOp.FSUB, 0x05: F.FArithOp.FSUB,
            0x08: F.FArithOp.FMUL, 0x09: F.FArithOp.FMUL,
            0x0c: F.FArithOp.FDIV, 0x0d: F.FArithOp.FDIV,
        }
        int_type = {0x0: F.FType.I32, 0x1: F.FType.U32,
                    0x2: F.FType.I64, 0x3: F.FType.U64}

        # Integer <-> FP register moves (bit-preserving, funct3=0)
        if funct7_full == 0x70 and rs2 == 0 and funct3 == 0x0:
            return F.FmvXW(rd=rd, rs1=rs1)
        elif funct7_full == 0x71 and rs2 == 0 and funct3 == 0x0:
            return F.FmvXD(rd=rd, rs1=rs1)
        elif funct7_full == 0x78 and rs2 == 0 and funct3 == 0x0:
            return F.FmvWX(fd=rd, rs1=rs1)
        elif funct7_full == 0x79 and rs2 == 0 and funct3 == 0x0:
            return F.FmvDX(fd=rd, rs1=rs1)

        # Classify (funct3=1)
        elif funct7_full == 0x70 and rs2 == 0 and funct3 == 0x1:
            return F.FClass(rd=rd, rs1=rs1, is_double=False)
        elif funct7_full == 0x71 and rs2 == 0 and funct3 == 0x1:
            return F.FClass(rd=rd, rs1=rs1, is_double=True)

        # Arithmetic (FArith)
        elif funct7_full in arith_binary:
            return F.FArith(fd=rd, rs1=rs1, rs2=rs2,
                            op=arith_binary[funct7_full], is_double=is_double)
        elif funct7_full in (0x2c, 0x2d) and rs2 == 0:
            return F.FArith(fd=rd, rs1=rs1, rs2=0,
                            op=F.FArithOp.FSQRT, is_double=is_double)
        elif funct7_full in (0x10, 0x11) and funct3 in (0x0, 0x1, 0x2):
            sgnj_op = {0x0: F.FArithOp.FSGNJ,
                       0x1: F.FArithOp.FSGNJN,
                       0x2: F.FArithOp.FSGNJX}[funct3]
            return F.FArith(fd=rd, rs1=rs1, rs2=rs2,
                            op=sgnj_op, is_double=is_double)
        elif funct7_full in (0x14, 0x15) and funct3 in (0x0, 0x1):
            minmax_op = {0x0: F.FArithOp.FMIN,
                         0x1: F.FArithOp.FMAX}[funct3]
            return F.FArith(fd=rd, rs1=rs1, rs2=rs2,
                            op=minmax_op, is_double=is_double)

        # Compare (FCmp — writes integer reg)
        elif funct7_full in (0x50, 0x51) and funct3 in (0x0, 0x1, 0x2):
            cmp_op = {0x2: F.FCmpOp.FEQ,
                      0x1: F.FCmpOp.FLT,
                      0x0: F.FCmpOp.FLE}[funct3]
            return F.FCmp(rd=rd, rs1=rs1, rs2=rs2,
                          op=cmp_op, is_double=is_double)

        # Precision conversions (F<->F)
        elif funct7_full == 0x20 and rs2 == 0x1:
            return F.FCvt(dst=rd, src=rs1,
                          dst_type=F.FType.F32, src_type=F.FType.F64, rm=funct3)
        elif funct7_full == 0x21 and rs2 == 0x0:
            return F.FCvt(dst=rd, src=rs1,
                          dst_type=F.FType.F64, src_type=F.FType.F32, rm=funct3)

        # Float -> Int (funct7 0x60=.S, 0x61=.D; rs2 selects signed/width)
        elif funct7_full == 0x60 and rs2 in int_type:
            return F.FCvt(dst=rd, src=rs1,
                          dst_type=int_type[rs2], src_type=F.FType.F32, rm=funct3)
        elif funct7_full == 0x61 and rs2 in int_type:
            return F.FCvt(dst=rd, src=rs1,
                          dst_type=int_type[rs2], src_type=F.FType.F64, rm=funct3)

        # Int -> Float (funct7 0x68=.S, 0x69=.D; rs2 selects signed/width)
        elif funct7_full == 0x68 and rs2 in int_type:
            return F.FCvt(dst=rd, src=rs1,
                          dst_type=F.FType.F32, src_type=int_type[rs2], rm=funct3)
        elif funct7_full == 0x69 and rs2 in int_type:
            return F.FCvt(dst=rd, src=rs1,
                          dst_type=F.FType.F64, src_type=int_type[rs2], rm=funct3)

    elif opcode == 0x57:
        bit31 = (inst >> 31) & 0x1
        funct6 = (inst >> 26) & 0x3f
        vm = (inst >> 25) & 0x1
        vs2 = rs2

        if bit31 == 0 and funct3 == 0x7:
            vtypei = (inst >> 20) & 0x7ff
            return V.Vsetvli(rd=rd, rs1=rs1, vtypei=vtypei)
        elif bit31 == 1 and ((inst >> 30) & 0x1) == 1 and funct3 == 0x7:
            # vsetivli: bit31=1, bit30=1, funct3=7
            uimm = (inst >> 15) & 0x1f
            vtypei = (inst >> 20) & 0x3ff
            return V.Vsetivli(rd=rd, uimm=uimm, vtypei=vtypei)
        # OPFVF (funct3 = 0x5) - floating-point vector-scalar
        elif funct6 == 0x00 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FADD)
        elif funct6 == 0x02 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSUB)
        elif funct6 == 0x27 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FRSUB)
        elif funct6 == 0x04 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMIN)
        elif funct6 == 0x06 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMAX)
        elif funct6 == 0x08 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSGNJ)
        elif funct6 == 0x09 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSGNJN)
        elif funct6 == 0x0a and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSGNJX)
        elif funct6 == 0x18 and funct3 == 0x5:
            return V.VCmpVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.EQ)
        elif funct6 == 0x19 and funct3 == 0x5:
            return V.VCmpVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.LE)
        elif funct6 == 0x1b and funct3 == 0x5:
            return V.VCmpVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.LT)
        elif funct6 == 0x1c and funct3 == 0x5:
            return V.VCmpVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.NE)
        elif funct6 == 0x1d and funct3 == 0x5:
            return V.VCmpVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.GT)
        elif funct6 == 0x1f and funct3 == 0x5:
            return V.VCmpVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.GE)
        elif funct6 == 0x24 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMUL)
        elif funct6 == 0x20 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FDIV)
        elif funct6 == 0x21 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FRDIV)
        elif funct6 == 0x28 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMADD)
        elif funct6 == 0x29 and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMADD)
        elif funct6 == 0x2a and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMSUB)
        elif funct6 == 0x2b and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMSUB)
        elif funct6 == 0x2c and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMACC)
        elif funct6 == 0x2d and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMACC)
        elif funct6 == 0x2e and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMSAC)
        elif funct6 == 0x2f and funct3 == 0x5:
            return V.VArithVxFloat(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMSAC)
        # OPMVV (funct3 = 0x2) - single-width integer reductions
        elif funct6 == 0x00 and funct3 == 0x2:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.SUM)
        elif funct6 == 0x01 and funct3 == 0x2:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.AND)
        elif funct6 == 0x02 and funct3 == 0x2:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.OR)
        elif funct6 == 0x03 and funct3 == 0x2:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.XOR)
        elif funct6 == 0x04 and funct3 == 0x2:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.MINU)
        elif funct6 == 0x05 and funct3 == 0x2:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.MIN)
        elif funct6 == 0x06 and funct3 == 0x2:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.MAXU)
        elif funct6 == 0x07 and funct3 == 0x2:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.MAX)
        # OPFVV (funct3 = 0x1) - single-width float reductions
        elif funct6 == 0x01 and funct3 == 0x1:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.FSUM)
        elif funct6 == 0x05 and funct3 == 0x1:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.FMIN)
        elif funct6 == 0x07 and funct3 == 0x1:
            vs1 = rs1
            return V.Vreduction(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.FMAX)
        # OPIVV (funct3 = 0x0) - widening integer reductions
        elif funct6 == 0x30 and funct3 == 0x0:
            vs1 = rs1
            return V.Vreduction(
                vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.WSUMU)
        elif funct6 == 0x31 and funct3 == 0x0:
            vs1 = rs1
            return V.Vreduction(
                vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.WSUM)
        # OPFVV (funct3 = 0x1) - widening float reduction
        elif funct6 == 0x31 and funct3 == 0x1:
            vs1 = rs1
            return V.Vreduction(
                vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VRedOp.FWSUM)
        # OPIVV (funct3 = 0x0) - integer vector-vector
        elif funct6 == 0x00 and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD)
        elif funct6 == 0x02 and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB)
        elif funct6 == 0x09 and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.AND)
        elif funct6 == 0x0a and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.OR)
        elif funct6 == 0x0b and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.XOR)
        elif funct6 == 0x25 and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SLL)
        elif funct6 == 0x28 and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SRL)
        elif funct6 == 0x29 and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SRA)
        # OPIVX (funct3 = 0x4) - integer vector-scalar
        elif funct6 == 0x00 and funct3 == 0x4:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD)
        elif funct6 == 0x02 and funct3 == 0x4:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB)
        elif funct6 == 0x03 and funct3 == 0x4:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.RSUB)
        elif funct6 == 0x03 and funct3 == 0x3:
            simm5 = rs1
            return V.VArithVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VArithOp.RSUB)
        elif funct6 == 0x09 and funct3 == 0x4:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.AND)
        elif funct6 == 0x0a and funct3 == 0x4:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.OR)
        elif funct6 == 0x0b and funct3 == 0x4:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.XOR)
        elif funct6 == 0x25 and funct3 == 0x4:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SLL)
        elif funct6 == 0x28 and funct3 == 0x4:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SRL)
        elif funct6 == 0x29 and funct3 == 0x4:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SRA)
        # OPIVI (funct3 = 0x3) - integer vector-immediate
        elif funct6 == 0x00 and funct3 == 0x3:
            simm5 = rs1
            return V.VArithVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VArithOp.ADD)
        elif funct6 == 0x09 and funct3 == 0x3:
            simm5 = rs1
            return V.VArithVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VArithOp.AND)
        elif funct6 == 0x0a and funct3 == 0x3:
            simm5 = rs1
            return V.VArithVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VArithOp.OR)
        elif funct6 == 0x0b and funct3 == 0x3:
            simm5 = rs1
            return V.VArithVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VArithOp.XOR)
        elif funct6 == 0x25 and funct3 == 0x3:
            simm5 = rs1
            return V.VArithVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VArithOp.SLL)
        elif funct6 == 0x28 and funct3 == 0x3:
            simm5 = rs1
            return V.VArithVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VArithOp.SRL)
        elif funct6 == 0x29 and funct3 == 0x3:
            simm5 = rs1
            return V.VArithVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VArithOp.SRA)
        # Narrowing right shift family (vnsrl, vnsra). funct6 0x2c = vnsrl,
        # 0x2d = vnsra. funct3 0x0 = .wv, 0x3 = .wi (uimm), 0x4 = .wx.
        elif funct6 == 0x2c and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm,
                op=kinstructions.VArithOp.SRL, shape=V.OvShape.NARROW,
                src1_signed=False, src2_signed=False, mnemonic='vnsrl.wv')
        elif funct6 == 0x2c and funct3 == 0x4:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm,
                op=kinstructions.VArithOp.SRL, shape=V.OvShape.NARROW,
                scalar_signed=False, src2_signed=False, mnemonic='vnsrl.wx')
        elif funct6 == 0x2c and funct3 == 0x3:
            uimm = rs1
            return V.VArithVxOv(
                vd=rd, rs1=uimm, vs2=vs2, vm=vm,
                op=kinstructions.VArithOp.SRL, shape=V.OvShape.NARROW,
                scalar_signed=False, src2_signed=False, mnemonic='vnsrl.wi',
                is_imm=True)
        elif funct6 == 0x2d and funct3 == 0x0:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm,
                op=kinstructions.VArithOp.SRA, shape=V.OvShape.NARROW,
                src1_signed=False, src2_signed=True, mnemonic='vnsra.wv')
        elif funct6 == 0x2d and funct3 == 0x4:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm,
                op=kinstructions.VArithOp.SRA, shape=V.OvShape.NARROW,
                scalar_signed=False, src2_signed=True, mnemonic='vnsra.wx')
        elif funct6 == 0x2d and funct3 == 0x3:
            uimm = rs1
            return V.VArithVxOv(
                vd=rd, rs1=uimm, vs2=vs2, vm=vm,
                op=kinstructions.VArithOp.SRA, shape=V.OvShape.NARROW,
                scalar_signed=False, src2_signed=True, mnemonic='vnsra.wi',
                is_imm=True)
        # Comparison .vi forms (funct3=0x3 = OPIVI)
        elif funct6 == 0x18 and funct3 == 0x3:
            simm5 = rs1
            return V.VCmpVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VCmpOp.EQ)
        elif funct6 == 0x19 and funct3 == 0x3:
            simm5 = rs1
            return V.VCmpVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VCmpOp.NE)
        elif funct6 == 0x1c and funct3 == 0x3:
            simm5 = rs1
            return V.VCmpVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VCmpOp.LEU)
        elif funct6 == 0x1d and funct3 == 0x3:
            simm5 = rs1
            return V.VCmpVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VCmpOp.LE)
        elif funct6 == 0x1e and funct3 == 0x3:
            simm5 = rs1
            return V.VCmpVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VCmpOp.GTU)
        elif funct6 == 0x1f and funct3 == 0x3:
            simm5 = rs1
            return V.VCmpVi(vd=rd, vs2=vs2, simm5=simm5, vm=vm, op=kinstructions.VCmpOp.GT)
        # Comparison .vv forms (funct3=0x0 = OPIVV)
        elif funct6 == 0x18 and funct3 == 0x0:
            vs1 = rs1
            return V.VCmpVv(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VCmpOp.EQ)
        elif funct6 == 0x19 and funct3 == 0x0:
            vs1 = rs1
            return V.VCmpVv(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VCmpOp.NE)
        elif funct6 == 0x1a and funct3 == 0x0:
            vs1 = rs1
            return V.VCmpVv(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VCmpOp.LTU)
        elif funct6 == 0x1b and funct3 == 0x0:
            vs1 = rs1
            return V.VCmpVv(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VCmpOp.LT)
        elif funct6 == 0x1c and funct3 == 0x0:
            vs1 = rs1
            return V.VCmpVv(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VCmpOp.LEU)
        elif funct6 == 0x1d and funct3 == 0x0:
            vs1 = rs1
            return V.VCmpVv(vd=rd, vs2=vs2, vs1=vs1, vm=vm, op=kinstructions.VCmpOp.LE)
        # Comparison .vx forms (funct3=0x4 = OPIVX)
        elif funct6 == 0x18 and funct3 == 0x4:
            return V.VCmpVx(vd=rd, vs2=vs2, rs1=rs1, vm=vm, op=kinstructions.VCmpOp.EQ)
        elif funct6 == 0x19 and funct3 == 0x4:
            return V.VCmpVx(vd=rd, vs2=vs2, rs1=rs1, vm=vm, op=kinstructions.VCmpOp.NE)
        elif funct6 == 0x1a and funct3 == 0x4:
            return V.VCmpVx(vd=rd, vs2=vs2, rs1=rs1, vm=vm, op=kinstructions.VCmpOp.LTU)
        elif funct6 == 0x1b and funct3 == 0x4:
            return V.VCmpVx(vd=rd, vs2=vs2, rs1=rs1, vm=vm, op=kinstructions.VCmpOp.LT)
        elif funct6 == 0x1c and funct3 == 0x4:
            return V.VCmpVx(vd=rd, vs2=vs2, rs1=rs1, vm=vm, op=kinstructions.VCmpOp.LEU)
        elif funct6 == 0x1d and funct3 == 0x4:
            return V.VCmpVx(vd=rd, vs2=vs2, rs1=rs1, vm=vm, op=kinstructions.VCmpOp.LE)
        elif funct6 == 0x1e and funct3 == 0x4:
            return V.VCmpVx(vd=rd, vs2=vs2, rs1=rs1, vm=vm, op=kinstructions.VCmpOp.GTU)
        elif funct6 == 0x1f and funct3 == 0x4:
            return V.VCmpVx(vd=rd, vs2=vs2, rs1=rs1, vm=vm, op=kinstructions.VCmpOp.GT)
        elif funct6 == 0x18 and funct3 == 0x2:
            return V.VmLogicMm(vd=rd, vs2=vs2, vs1=rs1,
                               op=kinstructions.VmLogicOp.ANDN)
        elif funct6 == 0x19 and funct3 == 0x2:
            return V.VmLogicMm(vd=rd, vs2=vs2, vs1=rs1,
                               op=kinstructions.VmLogicOp.AND)
        elif funct6 == 0x1a and funct3 == 0x2:
            return V.VmLogicMm(vd=rd, vs2=vs2, vs1=rs1,
                               op=kinstructions.VmLogicOp.OR)
        elif funct6 == 0x1b and funct3 == 0x2:
            return V.VmLogicMm(vd=rd, vs2=vs2, vs1=rs1,
                               op=kinstructions.VmLogicOp.XOR)
        elif funct6 == 0x1c and funct3 == 0x2:
            return V.VmLogicMm(vd=rd, vs2=vs2, vs1=rs1,
                               op=kinstructions.VmLogicOp.ORN)
        elif funct6 == 0x1d and funct3 == 0x2:
            return V.VmLogicMm(vd=rd, vs2=vs2, vs1=rs1,
                               op=kinstructions.VmLogicOp.NAND)
        elif funct6 == 0x1e and funct3 == 0x2:
            return V.VmLogicMm(vd=rd, vs2=vs2, vs1=rs1,
                               op=kinstructions.VmLogicOp.NOR)
        elif funct6 == 0x1f and funct3 == 0x2:
            return V.VmLogicMm(vd=rd, vs2=vs2, vs1=rs1,
                               op=kinstructions.VmLogicOp.XNOR)
        elif funct6 == 0x17 and funct3 == 0x0 and vm == 0:
            vs1 = rs1
            return V.VmergeVvm(vd=rd, vs1=vs1, vs2=vs2)
        elif funct6 == 0x17 and funct3 == 0x0 and vm == 1:
            return V.Vmv(vd=rd, vs2=rs1, nreg=1, mnemonic='vmv.v.v')
        elif funct6 == 0x17 and funct3 == 0x3 and vm == 0:
            simm5 = rs1
            return V.VmergeVim(vd=rd, vs2=vs2, simm5=simm5)
        elif funct6 == 0x17 and funct3 == 0x3 and vm == 1:
            simm5 = rs1
            return V.VmvVi(vd=rd, simm5=simm5)
        elif funct6 == 0x17 and funct3 == 0x4 and vm == 0:
            return V.VmergeVx(vd=rd, rs1=rs1, vs2=vs2)
        elif funct6 == 0x17 and funct3 == 0x4 and vm == 1:
            return V.VmvVx(vd=rd, rs1=rs1)
        elif funct6 == 0x10 and funct3 == 0x2 and rs1 == 0:
            return V.VmvXs(rd=rd, vs2=vs2)
        elif funct6 == 0x10 and funct3 == 0x2 and rs1 == 0b10000:
            return V.VcpopM(rd=rd, vs2=vs2, vm=vm)
        elif funct6 == 0x10 and funct3 == 0x2 and rs1 == 0b10001:
            return V.VfirstM(rd=rd, vs2=vs2, vm=vm)
        elif funct6 == 0x14 and funct3 == 0x2 and rs1 == 0b00001:
            return V.VmsFirstMask(
                vd=rd, vs2=vs2, vm=vm,
                mode=kinstructions.SetMaskBitsMode.LT,
                mnemonic='vmsbf.m')
        elif funct6 == 0x14 and funct3 == 0x2 and rs1 == 0b00010:
            return V.VmsFirstMask(
                vd=rd, vs2=vs2, vm=vm,
                mode=kinstructions.SetMaskBitsMode.EQ,
                mnemonic='vmsof.m')
        elif funct6 == 0x14 and funct3 == 0x2 and rs1 == 0b00011:
            return V.VmsFirstMask(
                vd=rd, vs2=vs2, vm=vm,
                mode=kinstructions.SetMaskBitsMode.LE,
                mnemonic='vmsif.m')
        elif funct6 == 0x10 and funct3 == 0x6 and rs2 == 0:
            return V.VmvSx(vd=rd, rs1=rs1)
        elif funct6 == 0x10 and funct3 == 0x1 and rs1 == 0:
            return V.VfmvFs(rd=rd, vs2=vs2)
        elif funct6 == 0x10 and funct3 == 0x5 and rs2 == 0:
            return V.VfmvSf(vd=rd, rs1=rs1)
        elif funct6 == 0x25 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MUL)
        elif funct6 == 0x25 and funct3 == 0x6:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MUL)
        elif funct6 == 0x2d and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MACC)
        elif funct6 == 0x2d and funct3 == 0x6:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MACC)
        elif funct6 == 0x2f and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.NMSAC)
        elif funct6 == 0x2f and funct3 == 0x6:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.NMSAC)
        elif funct6 == 0x29 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MADD)
        elif funct6 == 0x29 and funct3 == 0x6:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MADD)
        elif funct6 == 0x2b and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVv(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.NMSUB)
        elif funct6 == 0x2b and funct3 == 0x6:
            return V.VArithVx(vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.NMSUB)
        elif funct6 == 0x0c and funct3 == 0x0:
            vs1 = rs1
            return V.Vrgather(vd=rd, vs2=vs2, vs1=vs1, vm=vm)
        elif funct6 == 0x0c and funct3 == 0x4:
            return V.VrgatherVxVi(vd=rd, vs2=vs2, index_src=rs1,
                                  is_imm=False, vm=vm)
        elif funct6 == 0x0c and funct3 == 0x3:
            uimm = rs1
            return V.VrgatherVxVi(vd=rd, vs2=vs2, index_src=uimm,
                                  is_imm=True, vm=vm)
        elif funct6 == 0x0e and funct3 == 0x0:
            vs1 = rs1
            return V.Vrgather(vd=rd, vs2=vs2, vs1=vs1, vm=vm, index_ew_fixed=16)
        # Slides: funct6 0x0e = vslideup, 0x0f = vslidedown.
        # funct3 0x4 = .vx (rs1 offset), 0x3 = .vi (uimm5 offset).
        elif funct6 == 0x0e and funct3 == 0x4:
            return V.Vslide(vd=rd, vs2=vs2, offset_src=rs1, is_imm=False, vm=vm,
                            direction=SlideDirection.UP)
        elif funct6 == 0x0e and funct3 == 0x3:
            uimm = rs1
            return V.Vslide(vd=rd, vs2=vs2, offset_src=uimm, is_imm=True, vm=vm,
                            direction=SlideDirection.UP)
        elif funct6 == 0x0f and funct3 == 0x4:
            return V.Vslide(vd=rd, vs2=vs2, offset_src=rs1, is_imm=False, vm=vm,
                            direction=SlideDirection.DOWN)
        elif funct6 == 0x0f and funct3 == 0x3:
            uimm = rs1
            return V.Vslide(vd=rd, vs2=vs2, offset_src=uimm, is_imm=True, vm=vm,
                            direction=SlideDirection.DOWN)
        # vslide1up.vx / vslide1down.vx: funct3 = OPMVX (0x6).
        elif funct6 == 0x0e and funct3 == 0x6:
            return V.Vslide1(vd=rd, vs2=vs2, rs1=rs1, vm=vm,
                             direction=SlideDirection.UP)
        elif funct6 == 0x0f and funct3 == 0x6:
            return V.Vslide1(vd=rd, vs2=vs2, rs1=rs1, vm=vm,
                             direction=SlideDirection.DOWN)
        # vfslide1up.vf / vfslide1down.vf: funct3 = OPFVF (0x5).
        elif funct6 == 0x0e and funct3 == 0x5:
            return V.Vslide1(vd=rd, vs2=vs2, rs1=rs1, vm=vm,
                             direction=SlideDirection.UP, is_float=True)
        elif funct6 == 0x0f and funct3 == 0x5:
            return V.Vslide1(vd=rd, vs2=vs2, rs1=rs1, vm=vm,
                             direction=SlideDirection.DOWN, is_float=True)
        elif funct6 == 0x14 and funct3 == 0x2 and rs1 == 0x11:
            # vid.v - vmunary0 with vs1=10001
            return V.Vid(vd=rd, vm=vm)
        elif funct6 == 0x27 and funct3 == 0x3:
            # vmvNr.v - whole register move, N = simm5 + 1
            nreg = rs1 + 1
            return V.Vmv(vd=rd, vs2=vs2, nreg=nreg, mnemonic=f'vmv{nreg}r.v')
        # OPFVV (funct3 = 0x1) - floating-point vector-vector
        elif funct6 == 0x00 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FADD)
        elif funct6 == 0x02 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSUB)
        elif funct6 == 0x04 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMIN)
        elif funct6 == 0x06 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMAX)
        elif funct6 == 0x08 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSGNJ)
        elif funct6 == 0x09 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSGNJN)
        elif funct6 == 0x0a and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSGNJX)
        elif funct6 == 0x18 and funct3 == 0x1:
            vs1 = rs1
            return V.VCmpVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.EQ)
        elif funct6 == 0x19 and funct3 == 0x1:
            vs1 = rs1
            return V.VCmpVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.LE)
        elif funct6 == 0x1b and funct3 == 0x1:
            vs1 = rs1
            return V.VCmpVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.LT)
        elif funct6 == 0x1c and funct3 == 0x1:
            vs1 = rs1
            return V.VCmpVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VCmpOp.NE)
        elif funct6 == 0x20 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FDIV)
        elif funct6 == 0x24 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMUL)
        elif funct6 == 0x28 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMADD)
        elif funct6 == 0x29 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMADD)
        elif funct6 == 0x2a and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMSUB)
        elif funct6 == 0x2b and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMSUB)
        elif funct6 == 0x2c and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMACC)
        elif funct6 == 0x2d and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMACC)
        elif funct6 == 0x2e and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMSAC)
        elif funct6 == 0x2f and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvFloat(vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMSAC)
        elif funct6 == 0x12 and funct3 == 0x2:
            # OPMVV vzext/vsext: rs1 selects variant
            vzext_table = {
                2: (kinstructions.VUnaryOp.ZEXT, 8, 'vzext.vf8'),
                3: (kinstructions.VUnaryOp.SEXT, 8, 'vsext.vf8'),
                4: (kinstructions.VUnaryOp.ZEXT, 4, 'vzext.vf4'),
                5: (kinstructions.VUnaryOp.SEXT, 4, 'vsext.vf4'),
                6: (kinstructions.VUnaryOp.ZEXT, 2, 'vzext.vf2'),
                7: (kinstructions.VUnaryOp.SEXT, 2, 'vsext.vf2'),
            }
            if rs1 in vzext_table:
                op, factor, mnemonic = vzext_table[rs1]
                return V.VUnary(vd=rd, vs2=vs2, vm=vm, op=op,
                                factor=factor, widening=True, mnemonic=mnemonic)
        elif funct6 == 0x12 and funct3 == 0x1:
            # vfunary0: single-width float/int conversions, vs1 selects variant
            vfcvt_ops = {
                0x00: (kinstructions.VUnaryOp.FCVT_XU_F, 'vfcvt.xu.f.v'),
                0x01: (kinstructions.VUnaryOp.FCVT_X_F, 'vfcvt.x.f.v'),
                0x02: (kinstructions.VUnaryOp.FCVT_F_XU, 'vfcvt.f.xu.v'),
                0x03: (kinstructions.VUnaryOp.FCVT_F_X, 'vfcvt.f.x.v'),
                0x06: (kinstructions.VUnaryOp.FCVT_RTZ_XU_F, 'vfcvt.rtz.xu.f.v'),
                0x07: (kinstructions.VUnaryOp.FCVT_RTZ_X_F, 'vfcvt.rtz.x.f.v'),
            }
            if rs1 in vfcvt_ops:
                op, mnemonic = vfcvt_ops[rs1]
                return V.VUnary(vd=rd, vs2=vs2, vm=vm, op=op,
                                factor=1, widening=True, mnemonic=mnemonic)
        # Widening integer add/sub family (OPMVV funct3=0x2, OPMVX funct3=0x6).
        # Encoding: src2_signed reflects the .wv/.wx signedness of vs2; src1
        # is at SEW (BASE) or already-widened to 2*SEW (WIDE); dst always 2*SEW.
        elif funct6 == 0x30 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vwaddu.vv')
        elif funct6 == 0x30 and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vwaddu.vx')
        elif funct6 == 0x31 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD,
                shape=V.OvShape.BASE, src1_signed=True, src2_signed=True,
                mnemonic='vwadd.vv')
        elif funct6 == 0x31 and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD,
                shape=V.OvShape.BASE, scalar_signed=True, src2_signed=True,
                mnemonic='vwadd.vx')
        elif funct6 == 0x32 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vwsubu.vv')
        elif funct6 == 0x32 and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vwsubu.vx')
        elif funct6 == 0x33 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB,
                shape=V.OvShape.BASE, src1_signed=True, src2_signed=True,
                mnemonic='vwsub.vv')
        elif funct6 == 0x33 and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB,
                shape=V.OvShape.BASE, scalar_signed=True, src2_signed=True,
                mnemonic='vwsub.vx')
        elif funct6 == 0x34 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD,
                shape=V.OvShape.WIDE, src1_signed=False, src2_signed=False,
                mnemonic='vwaddu.wv')
        elif funct6 == 0x34 and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD,
                shape=V.OvShape.WIDE, scalar_signed=False, src2_signed=False,
                mnemonic='vwaddu.wx')
        elif funct6 == 0x35 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD,
                shape=V.OvShape.WIDE, src1_signed=True, src2_signed=True,
                mnemonic='vwadd.wv')
        elif funct6 == 0x35 and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.ADD,
                shape=V.OvShape.WIDE, scalar_signed=True, src2_signed=True,
                mnemonic='vwadd.wx')
        elif funct6 == 0x36 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB,
                shape=V.OvShape.WIDE, src1_signed=False, src2_signed=False,
                mnemonic='vwsubu.wv')
        elif funct6 == 0x36 and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB,
                shape=V.OvShape.WIDE, scalar_signed=False, src2_signed=False,
                mnemonic='vwsubu.wx')
        elif funct6 == 0x37 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB,
                shape=V.OvShape.WIDE, src1_signed=True, src2_signed=True,
                mnemonic='vwsub.wv')
        elif funct6 == 0x37 and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.SUB,
                shape=V.OvShape.WIDE, scalar_signed=True, src2_signed=True,
                mnemonic='vwsub.wx')
        # Widening integer multiply / multiply-accumulate (only BASE shape;
        # spec has no .wv/.wx forms for these).
        elif funct6 == 0x38 and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MUL,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vwmulu.vv')
        elif funct6 == 0x38 and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MUL,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vwmulu.vx')
        elif funct6 == 0x3a and funct3 == 0x2:
            # vwmulsu: vs2 signed, vs1 unsigned
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MUL,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=True,
                mnemonic='vwmulsu.vv')
        elif funct6 == 0x3a and funct3 == 0x6:
            # vwmulsu.vx: vs2 signed, rs1 unsigned
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MUL,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=True,
                mnemonic='vwmulsu.vx')
        elif funct6 == 0x3b and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MUL,
                shape=V.OvShape.BASE, src1_signed=True, src2_signed=True,
                mnemonic='vwmul.vv')
        elif funct6 == 0x3b and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MUL,
                shape=V.OvShape.BASE, scalar_signed=True, src2_signed=True,
                mnemonic='vwmul.vx')
        elif funct6 == 0x3c and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MACC,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vwmaccu.vv')
        elif funct6 == 0x3c and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MACC,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vwmaccu.vx')
        elif funct6 == 0x3d and funct3 == 0x2:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MACC,
                shape=V.OvShape.BASE, src1_signed=True, src2_signed=True,
                mnemonic='vwmacc.vv')
        elif funct6 == 0x3d and funct3 == 0x6:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MACC,
                shape=V.OvShape.BASE, scalar_signed=True, src2_signed=True,
                mnemonic='vwmacc.vx')
        elif funct6 == 0x3e and funct3 == 0x6:
            # vwmaccus.vx (no .vv form): rs1 unsigned, vs2 signed
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MACC,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=True,
                mnemonic='vwmaccus.vx')
        elif funct6 == 0x3f and funct3 == 0x2:
            # vwmaccsu.vv: vs1 signed, vs2 unsigned
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MACC,
                shape=V.OvShape.BASE, src1_signed=True, src2_signed=False,
                mnemonic='vwmaccsu.vv')
        elif funct6 == 0x3f and funct3 == 0x6:
            # vwmaccsu.vx: rs1 signed, vs2 unsigned
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.MACC,
                shape=V.OvShape.BASE, scalar_signed=True, src2_signed=False,
                mnemonic='vwmaccsu.vx')
        # Widening float arith (OPFVV funct3=0x1, OPFVF funct3=0x5).
        # Float signedness is irrelevant; pass False/False.
        elif funct6 == 0x30 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FADD,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vfwadd.vv')
        elif funct6 == 0x30 and funct3 == 0x5:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FADD,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vfwadd.vf')
        elif funct6 == 0x32 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSUB,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vfwsub.vv')
        elif funct6 == 0x32 and funct3 == 0x5:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSUB,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vfwsub.vf')
        elif funct6 == 0x34 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FADD,
                shape=V.OvShape.WIDE, src1_signed=False, src2_signed=False,
                mnemonic='vfwadd.wv')
        elif funct6 == 0x34 and funct3 == 0x5:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FADD,
                shape=V.OvShape.WIDE, scalar_signed=False, src2_signed=False,
                mnemonic='vfwadd.wf')
        elif funct6 == 0x36 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSUB,
                shape=V.OvShape.WIDE, src1_signed=False, src2_signed=False,
                mnemonic='vfwsub.wv')
        elif funct6 == 0x36 and funct3 == 0x5:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FSUB,
                shape=V.OvShape.WIDE, scalar_signed=False, src2_signed=False,
                mnemonic='vfwsub.wf')
        elif funct6 == 0x38 and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMUL,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vfwmul.vv')
        elif funct6 == 0x38 and funct3 == 0x5:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMUL,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vfwmul.vf')
        elif funct6 == 0x3c and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMACC,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vfwmacc.vv')
        elif funct6 == 0x3c and funct3 == 0x5:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMACC,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vfwmacc.vf')
        elif funct6 == 0x3d and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMACC,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vfwnmacc.vv')
        elif funct6 == 0x3d and funct3 == 0x5:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMACC,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vfwnmacc.vf')
        elif funct6 == 0x3e and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMSAC,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vfwmsac.vv')
        elif funct6 == 0x3e and funct3 == 0x5:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FMSAC,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vfwmsac.vf')
        elif funct6 == 0x3f and funct3 == 0x1:
            vs1 = rs1
            return V.VArithVvOv(
                vd=rd, vs1=vs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMSAC,
                shape=V.OvShape.BASE, src1_signed=False, src2_signed=False,
                mnemonic='vfwnmsac.vv')
        elif funct6 == 0x3f and funct3 == 0x5:
            return V.VArithVxOv(
                vd=rd, rs1=rs1, vs2=vs2, vm=vm, op=kinstructions.VArithOp.FNMSAC,
                shape=V.OvShape.BASE, scalar_signed=False, src2_signed=False,
                mnemonic='vfwnmsac.vf')

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

    elif opcode == 0x67:
        return CF.Jalr(rd=rd, rs1=rs1, imm=decode_i_imm(inst))

    elif opcode == 0x6f:
        return CF.Jal(rd=rd, imm=decode_j_imm(inst))

    elif opcode == 0x73:
        if funct3 == 0x0:
            # PRIV instructions (ECALL, EBREAK, xRET, WFI, etc.)
            funct12 = imm_i
            if funct12 == 0x302:
                return S.Mret()
            elif funct12 == 0x102:
                return S.Sret()
        elif funct3 == 0x1:
            return S.Csrrw(rd=rd, rs1=rs1, csr=csr)
        elif funct3 == 0x2:
            return S.Csrrs(rd=rd, rs1=rs1, csr=csr)
        elif funct3 == 0x5:
            zimm = rs1
            return S.Csrrwi(rd=rd, zimm=zimm, csr=csr)
        elif funct3 == 0x6:
            zimm = rs1
            return S.Csrrsi(rd=rd, zimm=zimm, csr=csr)
        elif funct3 == 0x7:
            zimm = rs1
            return S.Csrrci(rd=rd, zimm=zimm, csr=csr)

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
