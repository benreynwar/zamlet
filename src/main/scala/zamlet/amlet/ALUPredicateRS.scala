package zamlet.amlet

import chisel3._
import chisel3.util._

/**
 * ALU Predicate Reservation Station - manages out-of-order execution for ALU predicate operations
 */
class ALUPredicateRS(params: AmletParams) extends ReservationStation[PredicateInstr.Resolving, PredicateInstr.Resolved](params, params.aluPredicateRSParams, new PredicateInstr.Resolving(params), new PredicateInstr.Resolved(params)) {

  def readyToIssue(allResolving: Vec[PredicateInstr.Resolving], index: UInt): Bool = {
    allResolving(index).isResolved()
  }

  def emptySlot(): PredicateInstr.Resolving = {
    val result = Wire(new PredicateInstr.Resolving(params))
    result := DontCare
    result
  }

}

/** Generator object for creating ALUPredicateRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of ALUPredicateRS modules with configurable parameters.
  */
object ALUPredicateRSGenerator extends zamlet.ModuleGenerator {
  /** Create an ALUPredicateRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return ALUPredicateRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ALUPredicateRS <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ALUPredicateRS(params)
    }
  }
}
