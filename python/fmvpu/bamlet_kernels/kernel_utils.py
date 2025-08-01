import logging

from fmvpu.bamlet.bamlet_params import BamletParams
from fmvpu.amlet.instruction import VLIWInstruction
from fmvpu.amlet.control_instruction import ControlInstruction, ControlModes
from fmvpu.amlet.packet_instruction import PacketInstruction
from fmvpu.amlet.ldst_instruction import LoadStoreInstruction
from fmvpu.amlet.alu_instruction import ALUInstruction
from fmvpu.amlet.alu_lite_instruction import ALULiteInstruction


logger = logging.getLogger(__name__)
                  

def instructions_into_vliw(params: BamletParams, instrs):
    class_index = 0
    instr = None
    vliws = []
    vliw = VLIWInstruction()
    index = 0
    # Which instruction the live 'if' and 'loop' started in.
    # We use this to work out their length.
    if_starts = []
    loop_starts = []
    # The list of active 'if' and 'loop' instructions.
    if_instructions = []
    loop_instructions = []
    while instr or instrs:
        if instr is None:
            instr = instrs.pop(0)
        if isinstance(instr, ControlInstruction):
            if instr.mode not in (ControlModes.END_LOOP,):
                if instr.mode in (ControlModes.LOOP_LOCAL, ControlModes.LOOP_GLOBAL, ControlModes.LOOP_IMMEDIATE):
                    loop_instructions.append(instr)
                    loop_starts.append(index)
                vliw.control = instr
                logger.info('Adding control')
                if not instrs:
                    break
                instr = instrs.pop(0)
        if isinstance(instr, PacketInstruction):
            vliw.packet = instr
            logger.info('Adding packet')
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, LoadStoreInstruction):
            vliw.load_store = instr
            logger.info('Adding ldst')
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, ALUInstruction):
            vliw.alu = instr
            logger.info('Adding alu')
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, ALULiteInstruction):
            vliw.alu_lite = instr
            logger.info('Adding alulite')
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, ControlInstruction):
            if instr.mode == ControlModes.END_LOOP:
                logger.info('Adding endloop')
                loop_instructions.pop().length = index - loop_starts.pop()
                if not instrs:
                    break
                instr = instrs.pop(0)
        logger.info(f'Finishing {vliw}')
        vliws.append(vliw)
        vliw = VLIWInstruction()
        index += 1
    vliws.append(vliw)
    logger.info(f'Finishing {vliw}')
    return vliws
