package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams
import zamlet.utils.{SkidBuffer, DecoupledBuffer, DoubleBuffer}

/**
 * Packet Output Handler IO
 */
class PacketOutHandlerIO(params: LamletParams) extends Bundle {
  // Output direction this handler serves
  val outputDirection = Input(NetworkDirections())
  
  // Connection inputs from packet input handlers
  val connections = Flipped(Vec(5, Decoupled(new PacketData(params))))
  
  // Output to downstream
  val output = Decoupled(new NetworkWord(params))

  val thisX = Input(UInt(params.xPosWidth.W))
}

/**
 * Packet Output Handler Module
 *
 * arg: isNorthOrSouth
 *   Is this outputting in the vertical direction
 *   If so we tie the x_dest in the packet header to the current x_dest.
 *   This helps with broadcast instructions (otherwise there are multiple paths to the same dest)
 *   Since routing in horiz then vert it doesn't mess other stuff up.
 */
class PacketOutHandler(params: LamletParams, isNorthOrSouth: Boolean) extends Module {
  val io = IO(new PacketOutHandlerIO(params))
  
  val outputToBuffer = Wire(Decoupled(new NetworkWord(params)))
  io.output <> DoubleBuffer(outputToBuffer, params.networkNodeParams.boForwardBuffer, params.networkNodeParams.boBackwardBuffer)
  
  // Global priority counter for all 5 directions (North=0, East=1, South=2, West=3, Here=4)
  // All output handlers share the same priority sequence
  val globalPriority = RegInit(4.U)  // Start with Here for all output handlers
  
  // Update global priority every cycle through all 5 directions
  globalPriority := (globalPriority + 1.U) % 5.U

  // Buffer from each of the inputs.
  val connectionsBuffered = Wire(Vec(5, Decoupled(new PacketData(params))))
  for (i <- 0 until 5) {
    connectionsBuffered(i) <> DoubleBuffer(io.connections(i), params.networkNodeParams.abForwardBuffer, params.networkNodeParams.abBackwardBuffer)
  }

  
  // Default outputs - now connect to buffer instead of io.output
  connectionsBuffered.foreach(_.ready := false.B)
  outputToBuffer.valid := false.B
  outputToBuffer.bits := DontCare
  
  // Helper function to select which input handler gets priority for new connections
  // Uses round-robin scheduling starting from current priority input
  // Returns the index (0-4) of the highest priority requester
  def getHighestPriorityRequester(requests: Vec[Bool], currentPriority: UInt): UInt = {
    val result = Wire(UInt(3.W))
    result := 0.U // default value
    
    // Check priority order starting from current priority
    when(currentPriority === 0.U && requests(0)) { result := 0.U }
    .elsewhen(currentPriority === 0.U && requests(1)) { result := 1.U }
    .elsewhen(currentPriority === 0.U && requests(2)) { result := 2.U }
    .elsewhen(currentPriority === 0.U && requests(3)) { result := 3.U }
    .elsewhen(currentPriority === 0.U && requests(4)) { result := 4.U }
    .elsewhen(currentPriority === 1.U && requests(1)) { result := 1.U }
    .elsewhen(currentPriority === 1.U && requests(2)) { result := 2.U }
    .elsewhen(currentPriority === 1.U && requests(3)) { result := 3.U }
    .elsewhen(currentPriority === 1.U && requests(4)) { result := 4.U }
    .elsewhen(currentPriority === 1.U && requests(0)) { result := 0.U }
    .elsewhen(currentPriority === 2.U && requests(2)) { result := 2.U }
    .elsewhen(currentPriority === 2.U && requests(3)) { result := 3.U }
    .elsewhen(currentPriority === 2.U && requests(4)) { result := 4.U }
    .elsewhen(currentPriority === 2.U && requests(0)) { result := 0.U }
    .elsewhen(currentPriority === 2.U && requests(1)) { result := 1.U }
    .elsewhen(currentPriority === 3.U && requests(3)) { result := 3.U }
    .elsewhen(currentPriority === 3.U && requests(4)) { result := 4.U }
    .elsewhen(currentPriority === 3.U && requests(0)) { result := 0.U }
    .elsewhen(currentPriority === 3.U && requests(1)) { result := 1.U }
    .elsewhen(currentPriority === 3.U && requests(2)) { result := 2.U }
    .elsewhen(currentPriority === 4.U && requests(4)) { result := 4.U }
    .elsewhen(currentPriority === 4.U && requests(0)) { result := 0.U }
    .elsewhen(currentPriority === 4.U && requests(1)) { result := 1.U }
    .elsewhen(currentPriority === 4.U && requests(2)) { result := 2.U }
    .elsewhen(currentPriority === 4.U && requests(3)) { result := 3.U }
    
    result
  }
  // Which input we would select if we were making a new connection
  val validRequests = VecInit(connectionsBuffered.map(_.valid))
  val selectedInput = getHighestPriorityRequester(validRequests, globalPriority)

  // State of a connection
  val connstateIn = RegInit(0.U(3.W))
  val connstateActive = RegInit(false.B)

  // connectedIn is who we're connected to
  // This could be selectedInput (for a new connection) or connstateIn for an existing connection
  val connectedIn = Wire(UInt(3.W))

  val newHeader = Wire(new PacketHeader(params))
  newHeader := connectionsBuffered(connectedIn).bits.data.asTypeOf(new PacketHeader(params))
  
  outputToBuffer.valid := connectionsBuffered(connectedIn).valid
  connectionsBuffered(connectedIn).ready := outputToBuffer.ready
  when (connectionsBuffered(connectedIn).bits.isHeader) {
    outputToBuffer.bits.data := newHeader.asUInt
  } .otherwise {
    outputToBuffer.bits.data := connectionsBuffered(connectedIn).bits.data
  }
  outputToBuffer.bits.isHeader := connectionsBuffered(connectedIn).bits.isHeader
  if (isNorthOrSouth) {
    newHeader.targetX := io.thisX
  }

  when (connstateActive) {
    connectedIn := connstateIn
  }.otherwise {
    connectedIn := selectedInput
  }
  when (connectionsBuffered(connectedIn).valid) {
    when (connectionsBuffered(connectedIn).bits.isHeader) {
      when (!connstateActive) {
        connstateIn := selectedInput
      }
    }
    when (outputToBuffer.ready) {
      connstateActive := !connectionsBuffered(connectedIn).bits.last
    }
  }
}

/**
 * Module generator for PacketOutHandler
 */
object PacketOutHandlerGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> PacketOutHandler <jamletParamsFileName>")
      null
    } else {
      val params = LamletParams.fromFile(args(0))
      new PacketOutHandler(params, false)
    }
  }
}
