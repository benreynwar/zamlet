package zamlet.amlet

import chisel3._
import chisel3.util._

/**
 * SendPacket Reservation Station - manages in-order execution for Send Packet operations
 */
class SendPacketRS(params: AmletParams) extends ReservationStation[PacketInstr.SendResolving, PacketInstr.SendResolved](params, params.getSendPacketRSParams(), new PacketInstr.SendResolving(params), new PacketInstr.SendResolved(params)) {

  def readyToIssue(allResolving: Vec[PacketInstr.SendResolving], index: UInt): Bool = {
    // Only issue from position 0 (no reordering) and must be resolved
    index === 0.U && allResolving(index).isResolved()
  }

  def emptySlot(): PacketInstr.SendResolving = {
    val result = Wire(new PacketInstr.SendResolving(params))
    result := DontCare
    result
  }

}

/** Generator object for creating SendPacketRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of SendPacketRS modules with configurable parameters.
  */
object SendPacketRSGenerator extends zamlet.ModuleGenerator {
  /** Create a SendPacketRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return SendPacketRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> SendPacketRS <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new SendPacketRS(params)
    }
  }
}