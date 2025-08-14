package zamlet.amlet

import chisel3._
import chisel3.util._
import zamlet.utils.ResetStage

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
  
  val resetBuffered = ResetStage(clock, reset)

  withReset(resetBuffered) {
    // Memory array
    val mem = SyncReadMem(params.dataMemoryDepth, UInt(params.width.W))
    
    // Memory operation
    val isLoad = io.instr.bits.mode === LoadStoreInstr.Modes.Load
    val isStore = io.instr.bits.mode === LoadStoreInstr.Modes.Store
    
    // Read operation (only when predicate is true)
    val readData = mem.read(io.instr.bits.addr, io.instr.valid && isLoad && io.instr.bits.predicate)
    
    // Write operation (only when predicate is true)
    when(io.instr.valid && isStore && io.instr.bits.predicate) {
      mem.write(io.instr.bits.addr, io.instr.bits.src)
    }
    
    // Output result for loads only - always output (predicate will be checked in RegisterFileAndRename)
    io.result.valid := RegNext(io.instr.valid && isLoad, false.B)

    val predicate = RegNext(io.instr.bits.predicate)
    val src = RegNext(io.instr.bits.src)

    when (predicate) {
      io.result.bits.value := readData
    } .otherwise {
      // If we the predicate is False we just write the old value.
      io.result.bits.value := src
    }
    io.result.bits.address := RegNext(io.instr.bits.dst)
    io.result.bits.predicate := predicate
    io.result.bits.force := false.B

  }
}

/**
 * Module generator for DataMemory
 */
object DataMemoryGenerator extends zamlet.ModuleGenerator {
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
