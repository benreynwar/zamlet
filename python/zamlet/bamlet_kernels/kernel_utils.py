import logging

from zamlet.bamlet.bamlet_params import BamletParams
from zamlet.amlet.instruction import VLIWInstruction
from zamlet.amlet.control_instruction import ControlInstruction, ControlModes
from zamlet.amlet.packet_instruction import PacketInstruction
from zamlet.amlet.ldst_instruction import LoadStoreInstruction
from zamlet.amlet.alu_instruction import ALUInstruction
from zamlet.amlet.alu_lite_instruction import ALULiteInstruction
from zamlet.amlet.predicate_instruction import PredicateInstruction, PredicateModes, Src1Mode


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
                if not instrs:
                    break
                instr = instrs.pop(0)
        if isinstance(instr, PredicateInstruction):
            vliw.predicate = instr
            logger.info('Adding predicate')
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, PacketInstruction):
            vliw.packet = instr
            logger.info('Adding packet')
            if not instrs:
                break
            instr = instrs.pop(0)
        if isinstance(instr, ALULiteInstruction):
            vliw.alu_lite = instr
            logger.info('Adding alulite')
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
        while isinstance(instr, ControlInstruction) and (instr.mode == ControlModes.END_LOOP):
            loop_instruction = loop_instructions.pop()
            loop_instruction.length = index - loop_starts.pop()
            logger.info(f'Setting loop length to {loop_instruction.length}')
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
