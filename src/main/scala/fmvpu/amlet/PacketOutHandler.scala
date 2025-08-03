package fmvpu.amlet

import chisel3._
import chisel3.util._
import fmvpu.utils.SkidBuffer

/**
 * Packet Output Handler IO
 */
class PacketOutHandlerIO(params: AmletParams) extends Bundle {
  // Output direction this handler serves
  val outputDirection = Input(NetworkDirections())
  
  // Handler arbitration signals
  val handlerRequest = Input(Vec(5, Bool()))

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
class PacketOutHandler(params: AmletParams, isNorthOrSouth: Boolean) extends Module {
  val io = IO(new PacketOutHandlerIO(params))
  
  // Add SkidBuffer on output to network
  val outputBuffer = Module(new SkidBuffer(new NetworkWord(params), params.packetOutBackwardBuffer))
  io.output <> outputBuffer.io.o
  
  // Global priority counter for all 5 directions (North=0, East=1, South=2, West=3, Here=4)
  // All output handlers share the same priority sequence
  val globalPriority = RegInit(4.U)  // Start with Here for all output handlers
  
  // Update global priority every cycle through all 5 directions
  globalPriority := (globalPriority + 1.U) % 5.U
  
  // Default outputs - now connect to buffer instead of io.output
  io.connections.foreach(_.ready := false.B)
  outputBuffer.io.i.valid := false.B
  outputBuffer.io.i.bits := DontCare
  
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
  val selectedInput = getHighestPriorityRequester(io.handlerRequest, globalPriority)

  // State of a connection
  val connstateIn = RegInit(0.U(3.W))
  val connstateActive = RegInit(false.B)

  // connectedIn is who we're connected to
  // This could be selectedInput (for a new connection) or connstateIn for an existing connection
  val connectedIn = Wire(UInt(3.W))

  val newHeader = Wire(new PacketHeader(params))
  newHeader := io.connections(connectedIn).bits.data.asTypeOf(new PacketHeader(params))
  
  outputBuffer.io.i.valid := io.connections(connectedIn).valid
  io.connections(connectedIn).ready := outputBuffer.io.i.ready
  when (io.connections(connectedIn).bits.isHeader) {
    outputBuffer.io.i.bits.data := newHeader.asUInt
  } .otherwise {
    outputBuffer.io.i.bits.data := io.connections(connectedIn).bits.data
  }
  outputBuffer.io.i.bits.isHeader := io.connections(connectedIn).bits.isHeader
  if (isNorthOrSouth) {
    newHeader.xDest := io.thisX
  }

  when (connstateActive) {
    connectedIn := connstateIn
  }.otherwise {
    connectedIn := selectedInput
  }
  when (io.connections(connectedIn).valid) {
    when (io.connections(connectedIn).bits.isHeader) {
      when (!connstateActive) {
        connstateIn := selectedInput
      }
    }
    when (outputBuffer.io.i.ready && io.connections(connectedIn).bits.append) {
      connstateIn := NetworkDirections.Here.asUInt
    }
    when (outputBuffer.io.i.ready) {
      connstateActive := !io.connections(connectedIn).bits.last
    }
  }
}

/**
 * Module generator for PacketOutHandler
 */
object PacketOutHandlerGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> PacketOutHandler <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new PacketOutHandler(params, false)
    }
  }
}