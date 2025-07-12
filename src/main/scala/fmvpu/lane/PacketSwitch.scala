package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Packet Switch IO
 */
class PacketSwitchIO(params: LaneParams) extends Bundle {
  // Current position
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))
  
  // Network interfaces for 4 directions (North, South, East, West)
  val ni = Flipped(Decoupled(new NetworkWord(params)))
  val si = Flipped(Decoupled(new NetworkWord(params)))
  val ei = Flipped(Decoupled(new NetworkWord(params)))
  val wi = Flipped(Decoupled(new NetworkWord(params)))
  
  val no = Decoupled(new NetworkWord(params))
  val so = Decoupled(new NetworkWord(params))
  val eo = Decoupled(new NetworkWord(params))
  val wo = Decoupled(new NetworkWord(params))
  
  // 'Here' interface to/from local lane
  val hi = Flipped(Decoupled(new NetworkWord(params)))
  val ho = Decoupled(new NetworkWord(params))
  
  // Forward interface
  val forward = Flipped(Decoupled(new PacketForward(params)))
}

/**
 * Packet Switch Module
 * 
 * Instantiates 5 PacketInHandlers (North, East, South, West, Here) and 
 * 5 PacketOutHandlers (North, East, South, West, Here) and connects them together.
 */
class PacketSwitch(params: LaneParams) extends Module {
  val io = IO(new PacketSwitchIO(params))
  
  // Create 5 PacketInHandlers (North=0, East=1, South=2, West=3, Here=4)
  val inHandlers = Seq.fill(5)(Module(new PacketInHandler(params)))
  
  // Create 5 PacketOutHandlers (North=0, East=1, South=2, West=3, Here=4)  
  val outHandlers = Seq.fill(5)(Module(new PacketOutHandler(params)))
  
  // Position inputs for all handlers
  inHandlers.foreach { handler =>
    handler.io.thisX := io.thisX
    handler.io.thisY := io.thisY
  }
  
  // Configure input directions for PacketInHandlers (North=0, East=1, South=2, West=3, Here=4)
  inHandlers(0).io.inputDirection := NetworkDirections.North
  inHandlers(1).io.inputDirection := NetworkDirections.East
  inHandlers(2).io.inputDirection := NetworkDirections.South
  inHandlers(3).io.inputDirection := NetworkDirections.West
  inHandlers(4).io.inputDirection := NetworkDirections.Here
  
  // Configure output directions for PacketOutHandlers (North=0, East=1, South=2, West=3, Here=4)
  outHandlers(0).io.outputDirection := NetworkDirections.North
  outHandlers(1).io.outputDirection := NetworkDirections.East
  outHandlers(2).io.outputDirection := NetworkDirections.South
  outHandlers(3).io.outputDirection := NetworkDirections.West
  outHandlers(4).io.outputDirection := NetworkDirections.Here
  
  // Connect network inputs to PacketInHandlers (North=0, East=1, South=2, West=3, Here=4)
  inHandlers(0).io.fromNetwork <> io.ni
  inHandlers(1).io.fromNetwork <> io.ei
  inHandlers(2).io.fromNetwork <> io.si
  inHandlers(3).io.fromNetwork <> io.wi
  inHandlers(4).io.fromNetwork <> io.hi
  
  // Connect PacketOutHandlers to network outputs (North=0, East=1, South=2, West=3, Here=4)
  io.no <> outHandlers(0).io.output
  io.eo <> outHandlers(1).io.output
  io.so <> outHandlers(2).io.output
  io.wo <> outHandlers(3).io.output
  io.ho <> outHandlers(4).io.output
  
  // Connect forward interface to all PacketInHandlers
  inHandlers.foreach { handler =>
    handler.io.forward.valid := io.forward.valid
    handler.io.forward.bits := io.forward.bits
  }
  // Forward ready is OR of all input handler ready signals
  io.forward.ready := inHandlers.map(_.io.forward.ready).reduce(_ || _)
  
  // Connect data paths from PacketInHandlers to PacketOutHandlers using the mapping function
  val directions = Seq(NetworkDirections.North, NetworkDirections.East, NetworkDirections.South, NetworkDirections.West, NetworkDirections.Here)
  
  // Create unpacked Wire arrays for arbitration signals
  val outHandlerRequests = Seq.fill(5)(Wire(Vec(5, Bool())))
  
  // Initialize all to false
  outHandlerRequests.foreach(_.foreach(_ := false.B))
  
  for (dstIdx <- 0 until 5) {
    for (srcIdx <- 0 until 5) {
      if (dstIdx != srcIdx) {
        // Map to correct output index on source handler
        outHandlers(dstIdx).io.connections(srcIdx) <> inHandlers(srcIdx).io.outputs(dstIdx)
        
        // Connect arbitration signals using unpacked arrays
        outHandlerRequests(dstIdx)(srcIdx) := inHandlers(srcIdx).io.handlerRequest(dstIdx)
      } else {
        outHandlers(dstIdx).io.connections(srcIdx).valid := false.B
        outHandlers(dstIdx).io.connections(srcIdx).bits := DontCare
        inHandlers(srcIdx).io.outputs(dstIdx).ready := false.B
        outHandlerRequests(dstIdx)(srcIdx) := false.B
      }
    }
  }
  
  // Pack the Wire arrays into UInt signals
  for (outIdx <- 0 until 5) {
    outHandlers(outIdx).io.handlerRequest := Cat(outHandlerRequests(outIdx).reverse)
  }
}

/**
 * Module generator for PacketSwitch
 */
object PacketSwitchGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> PacketSwitch <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new PacketSwitch(params)
    }
  }
}
