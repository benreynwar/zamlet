package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * ReceivePacket Reservation Station - manages in-order execution for Receive Packet operations
 */
class ReceivePacketRS(params: AmletParams) extends ReservationStation[PacketInstr.ReceiveResolving, PacketInstr.ReceiveResolved](params, new PacketInstr.ReceiveResolving(params), new PacketInstr.ReceiveResolved(params)) {

  def nSlots(): Int = {
    params.nReceivePacketRSSlots
  }

  def readyToIssue(allResolving: Vec[PacketInstr.ReceiveResolving], index: UInt): Bool = {
    // Only issue from position 0 (no reordering) and must be resolved
    index === 0.U && allResolving(index).isResolved()
  }

  def emptySlot(): PacketInstr.ReceiveResolving = {
    val result = Wire(new PacketInstr.ReceiveResolving(params))
    result := DontCare
    result
  }

}

/** Generator object for creating ReceivePacketRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of ReceivePacketRS modules with configurable parameters.
  */
object ReceivePacketRSGenerator extends fmvpu.ModuleGenerator {
  /** Create a ReceivePacketRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return ReceivePacketRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ReceivePacketRS <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ReceivePacketRS(params)
    }
  }
}