package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * ALULite Reservation Station - manages out-of-order execution for ALULite operations
 */
class ALULiteRS(params: AmletParams) extends ReservationStation[ALULiteInstr.Resolving, ALULiteInstr.Resolved](params, new ALULiteInstr.Resolving(params), new ALULiteInstr.Resolved(params)) {

  def nSlots(): Int = {
    params.nAluLiteRSSlots
  }

}

/** Generator object for creating ALULiteRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of ALULiteRS modules with configurable parameters.
  */
object ALULiteRSGenerator extends fmvpu.ModuleGenerator {
  /** Create an ALULiteRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return ALULiteRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ALULiteRS <laneParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ALULiteRS(params)
    }
  }
}