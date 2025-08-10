package zamlet.amlet

import chisel3._
import chisel3.util._

/**
 * ALU Reservation Station - manages out-of-order execution for ALU operations
 */
class ALURS(params: AmletParams) extends ReservationStation[ALUInstr.Resolving, ALUInstr.Resolved](params, params.aluRSParams, new ALUInstr.Resolving(params), new ALUInstr.Resolved(params)) {

  def readyToIssue(allResolving: Vec[ALUInstr.Resolving], index: UInt): Bool = {
    allResolving(index).isResolved()
  }

  def emptySlot(): ALUInstr.Resolving = {
    val result = Wire(new ALUInstr.Resolving(params))
    result := DontCare
    result
  }

}

/** Generator object for creating AluRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of AluRS modules with configurable parameters.
  */
object ALURSGenerator extends zamlet.ModuleGenerator {
  /** Create an AluRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return AluRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ALURS <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ALURS(params)
    }
  }
}
