package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Instruction memory interface
 */
class InstructionMemoryIO(params: LaneParams) extends Bundle {
  // Read interface (from RFF)
  val readAddr = Input(UInt(params.instrAddrWidth.W))
  val readEnable = Input(Bool())
  val readData = Output(UInt(params.instructionWidth.W))
  val readValid = Output(Bool())
  
  // Write interface (from PacketInterface)
  val writeIM = Flipped(Valid(new IMWrite(params)))
  
  // Error output
  val conflict = Output(Bool())
}

/**
 * Single-port instruction memory
 */
class InstructionMemory(params: LaneParams) extends Module {
  val io = IO(new InstructionMemoryIO(params))
  
  // Memory array
  val mem = SyncReadMem(params.instructionMemoryDepth, UInt(params.instructionWidth.W))
  
  // Arbitration - prioritize writes
  val writeReq = io.writeIM.valid
  val readReq = io.readEnable
  val conflict = writeReq && readReq
  
  // Memory operations
  val actualReadEnable = readReq && !writeReq
  val addr = Mux(writeReq, io.writeIM.bits.address, io.readAddr)
  
  // Read operation (blocked during writes)
  io.readData := mem.read(addr, actualReadEnable)
  io.readValid := RegNext(actualReadEnable, false.B)
  
  // Write operation (has priority)
  when(writeReq) {
    mem.write(io.writeIM.bits.address, io.writeIM.bits.data(params.instructionWidth-1, 0))
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
    val params = LaneParams.fromFile(configFile)
    
    new InstructionMemory(params)
  }
}