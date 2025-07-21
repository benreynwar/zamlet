package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * LoadStore Reservation Station - manages out-of-order execution for Load/Store operations
 * with complex dependency checking to maintain memory ordering semantics
 */
class LoadStoreRS(params: AmletParams) extends ReservationStation[LoadStoreInstr.Resolving, LoadStoreInstr.Resolved](params, new LoadStoreInstr.Resolving(params), new LoadStoreInstr.Resolved(params)) {

  def nSlots(): Int = {
    params.nLoadStoreRSSlots
  }

  def readyToIssue(allResolving: Vec[LoadStoreInstr.Resolving], index: UInt): Bool = {
    val instr = allResolving(index)
    
    // Instruction must be resolved and valid to be considered for issuing
    val basicReady = instr.valid && instr.isResolved()
    
    // Check dependencies with all instructions ahead of this one (lower indices)
    val noDependencies = (0 until nSlots()).map { i =>
      val ahead = allResolving(i.U)
      val isAhead = i.U < index && ahead.valid
      
      val dependency = Wire(Bool())
      dependency := false.B
      
      when(isAhead && instr.mode === LoadStoreInstr.Modes.Load) {
        // Load is blocked by stores ahead with unresolved addresses or matching resolved addresses
        dependency := ahead.mode === LoadStoreInstr.Modes.Store && (
          !ahead.addr.resolved ||  // Store has unresolved address
          (ahead.addr.resolved && instr.addr.resolved && ahead.addr.getData === instr.addr.getData)  // Addresses match
        )
      }.elsewhen(isAhead && instr.mode === LoadStoreInstr.Modes.Store) {
        // Store is blocked by any load or store ahead with unresolved addresses or matching resolved addresses
        dependency := (ahead.mode === LoadStoreInstr.Modes.Load || ahead.mode === LoadStoreInstr.Modes.Store) && (
          !ahead.addr.resolved ||  // Ahead instruction has unresolved address
          (ahead.addr.resolved && instr.addr.resolved && ahead.addr.getData === instr.addr.getData)  // Addresses match
        )
      }
      
      !dependency
    }.reduce(_ && _)
    
    basicReady && noDependencies
  }

  def emptySlot(): LoadStoreInstr.Resolving = {
    val result = Wire(new LoadStoreInstr.Resolving(params))
    result := DontCare
    result
  }

}

/** Generator object for creating LoadStoreRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of LoadStoreRS modules with configurable parameters.
  */
object LoadStoreRSGenerator extends fmvpu.ModuleGenerator {
  /** Create a LoadStoreRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return LoadStoreRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> LoadStoreRS <laneParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new LoadStoreRS(params)
    }
  }
}