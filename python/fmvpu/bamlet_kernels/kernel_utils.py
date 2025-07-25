from fmvpu.bamlet.bamlet_params import BamletParams
from fmvpu.amlet.instruction import VLIWInstruction
from fmvpu.amlet.control_instruction import ControlInstruction, ControlModes
from fmvpu.amlet.packet_instruction import PacketInstruction
from fmvpu.amlet.ldst_instruction import LoadStoreInstruction
from fmvpu.amlet.alu_instruction import ALUInstruction
from fmvpu.amlet.alu_lite_instruction import ALULiteInstruction

                  
def instructions_into_vliw(params: BamletParams, instrs):
    class_index = 0
    instr = None
    vliws = []
    vliw = VLIWInstruction()
    while instr or instrs:
        if instr is None:
            instr = instrs.pop(0)
        if isinstance(instr, ControlInstruction):
            if instr.mode not in (ControlModes.ENDIF, ControlModes.ENDLOOP, ControlModes.HALT):
                vliw.control = instr
                if not instrs:
                    break
                instr = instrs.pop(0)
        if isinstance(instr, PacketInstruction):
            vliw.packet = instr
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, LoadStoreInstruction):
            vliw.ldst = instr
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, ALUInstruction):
            vliw.alu = instr
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, ALULiteInstruction):
            vliw.alulite = instr
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, ControlInstruction):
            if instr.mode == ControlModes.HALT:
                vliw.halt = True
            vliw.control = instr
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, ControlInstruction):
            if instr.mode == ControlModes.ENDIF:
                vliw.halt = True
            vliw.control = instr
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, ControlInstruction):
            if instr.mode == ControlModes.ENDLOOP:
                vliw.halt = True
            vliw.control = instr
            if not instrs:
                break
            instr = instrs.pop(0)
        vliws.append(vliw)
        vliw = VLIWInstruction()
    vliws.append(vliw)
    return vliws
