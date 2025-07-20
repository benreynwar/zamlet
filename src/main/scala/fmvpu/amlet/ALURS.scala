package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * ALU Reservation Station - manages out-of-order execution for ALU operations
 */
class ALURS(params: AmletParams) extends ReservationStation[ALUInstr.Resolving, ALUInstr.Resolved](params, new ALUInstr.Resolving(params), new ALUInstr.Resolved(params)) {

  def nSlots(): Int = {
    params.nAluRSSlots
  }

}

/** Generator object for creating AluRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of AluRS modules with configurable parameters.
  */
object ALURSGenerator extends fmvpu.ModuleGenerator {
  /** Create an AluRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return AluRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ALURS <laneParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ALURS(params)
    }
  }
}
