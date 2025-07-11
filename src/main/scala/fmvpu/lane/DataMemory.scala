package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Data Memory Execution Unit - handles load/store operations
 * 
 * @param params Lane configuration parameters
 */
class LaneDataMemory(params: LaneParams) extends Module {
  val io = IO(new Bundle {
    // Instruction input
    val instr = Input(Valid(new LdStInstrResolved(params)))
    
    // Result output
    val result = Output(new WriteResult(params))
  })
  
  // Memory array
  val mem = SyncReadMem(params.dataMemoryDepth, UInt(params.width.W))
  
  // Calculate address
  val addr = io.instr.bits.baseAddress + io.instr.bits.offset
  
  // Memory operation
  val isLoad = io.instr.bits.mode === LdStModes.Load
  val isStore = io.instr.bits.mode === LdStModes.Store
  
  // Read operation
  val readData = mem.read(addr, io.instr.valid && isLoad)
  
  // Write operation  
  when(io.instr.valid && isStore) {
    mem.write(addr, io.instr.bits.value)
  }
  
  // Output result for loads only
  io.result.valid := RegNext(io.instr.valid && isLoad, false.B)
  io.result.value := RegNext(readData)
  io.result.address := RegNext(io.instr.bits.dstAddr)
  io.result.force := false.B
}

/**
 * Module generator for LaneDataMemory
 */
object LaneDataMemoryGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> LaneDataMemory <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new LaneDataMemory(params)
    }
  }
}