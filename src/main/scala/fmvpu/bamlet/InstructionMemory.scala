package fmvpu.bamlet

import chisel3._
import chisel3.util._
import fmvpu.amlet.{ControlWrite, ControlWriteMode, VLIWInstr}

/**
 * Instruction memory interface for Bamlet
 */
class InstructionMemoryIO(params: BamletParams) extends Bundle {
  // Read interface (from Control) - same as Control.io.imReq
  val imReq = Flipped(Valid(UInt(params.amlet.instrAddrWidth.W)))
  
  // Response interface (to Control) - same as Control.io.imResp  
  val imResp = Valid(new InstrResp(params))
  
  // Write interface (from Amlets)
  val writeControl = Flipped(Valid(new ControlWrite(params.amlet)))
  
  // Error output
  val conflict = Output(Bool())
}

/**
 * Single-port instruction memory for Bamlet
 * Uses Vec storage to enable masked partial writes
 */
class InstructionMemory(params: BamletParams) extends Module {
  val io = IO(new InstructionMemoryIO(params))
  
  // Calculate actual VLIW instruction width and chunking
  val dummyVLIW = Wire(new VLIWInstr.Base(params.amlet))
  dummyVLIW := DontCare
  val instructionWidth = dummyVLIW.getWidth
  val writeWidth = params.amlet.width
  val wordsPerInstruction = (instructionWidth + writeWidth - 1) / writeWidth // Round up
  val wordSelectBits = log2Ceil(wordsPerInstruction)
  
  // Memory array - store instructions as Vec of writeWidth-bit words for masked writes
  val mem = SyncReadMem(params.instructionMemoryDepth, Vec(wordsPerInstruction, UInt(writeWidth.W)))
  
  // Arbitration - prioritize writes
  val writeReq = io.writeControl.valid && (io.writeControl.bits.mode === ControlWriteMode.InstructionMemory)
  val readReq = io.imReq.valid
  val conflict = writeReq && readReq
  
  // Read operation - single cycle, assemble full VLIW instruction
  val actualReadEnable = readReq && !writeReq
  val readInstrAddr = io.imReq.bits
  val readWordsVec = mem.read(readInstrAddr, actualReadEnable)
  val readData = readWordsVec.asUInt
  val readValid = RegNext(actualReadEnable, false.B)
  val readPC = RegNext(io.imReq.bits, 0.U)
  
  // Response to Control
  io.imResp.valid := readValid
  io.imResp.bits.instr := readData.asTypeOf(new VLIWInstr.Base(params.amlet))
  io.imResp.bits.pc := readPC
  
  // Write operation - masked write to specific word within instruction
  when(writeReq) {
    val writeInstrAddr = io.writeControl.bits.address >> wordSelectBits
    val writeWordSelect = io.writeControl.bits.address(wordSelectBits-1, 0)
    
    // Create write mask - only enable the selected word
    val writeMask = Wire(Vec(wordsPerInstruction, Bool()))
    for (i <- 0 until wordsPerInstruction) {
      writeMask(i) := (i.U === writeWordSelect)
    }
    
    // Create write data vector
    val writeDataVec = Wire(Vec(wordsPerInstruction, UInt(writeWidth.W)))
    for (i <- 0 until wordsPerInstruction) {
      writeDataVec(i) := io.writeControl.bits.data
    }
    
    // Perform masked write - only the selected word will be written
    mem.write(writeInstrAddr, writeDataVec, writeMask)
  }
  
  // Conflict detection
  io.conflict := conflict
}

object InstructionMemoryGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length != 1) {
      println("Usage: InstructionMemoryGenerator <config_file>")
      System.exit(1)
    }
    
    val configFile = args(0)
    val params = BamletParams.fromFile(configFile)
    
    new InstructionMemory(params)
  }
}
