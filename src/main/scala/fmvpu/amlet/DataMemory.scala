package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * Data Memory Execution Unit - handles load/store operations for amlet
 * 
 * @param params Amlet configuration parameters
 */
class DataMemory(params: AmletParams) extends Module {
  val io = IO(new Bundle {
    // Instruction input
    val instr = Input(Valid(new LoadStoreInstr.Resolved(params)))
    
    // Result output
    val result = Output(Valid(new WriteResult(params)))
  })
  
  // Memory array
  val mem = SyncReadMem(params.dataMemoryDepth, UInt(params.width.W))
  
  // Memory operation
  val isLoad = io.instr.bits.mode === LoadStoreInstr.Modes.Load
  val isStore = io.instr.bits.mode === LoadStoreInstr.Modes.Store
  
  // Read operation (only when not masked)
  val readData = mem.read(io.instr.bits.addr, io.instr.valid && isLoad)
  
  // Write operation (only when not masked)
  when(io.instr.valid && isStore) {
    mem.write(io.instr.bits.addr, io.instr.bits.src)
  }
  
  // Output result for loads only (only when not masked)
  io.result.valid := RegNext(io.instr.valid && isLoad, false.B)
  io.result.bits.value := readData
  io.result.bits.address := RegNext(io.instr.bits.dst)
  io.result.bits.force := false.B
}

/**
 * Module generator for DataMemory
 */
object DataMemoryGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> DataMemory <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new DataMemory(params)
    }
  }
}