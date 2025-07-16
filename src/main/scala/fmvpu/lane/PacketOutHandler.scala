package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Packet Output Handler IO
 */
class PacketOutHandlerIO(params: LaneParams) extends Bundle {
  // Output direction this handler serves
  val outputDirection = Input(NetworkDirections())
  
  // Handler arbitration signals
  val handlerRequest = Input(Vec(5, Bool()))
  
  // Connection inputs from packet input handlers
  val connections = Flipped(Vec(5, Decoupled(new PacketData(params))))
  
  // Output to downstream
  val output = Decoupled(new NetworkWord(params))
}

/**
 * Packet Output Handler Module
 */
class PacketOutHandler(params: LaneParams) extends Module {
  val io = IO(new PacketOutHandlerIO(params))
  
  // Global priority counter for all 5 directions (North=0, East=1, South=2, West=3, Here=4)
  // All output handlers share the same priority sequence
  val globalPriority = RegInit(4.U)  // Start with Here for all output handlers
  
  // Update global priority every cycle through all 5 directions
  globalPriority := (globalPriority + 1.U) % 5.U
  
  // Default outputs
  io.connections.foreach(_.ready := false.B)
  io.output.valid := false.B
  io.output.bits := DontCare
  
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

  io.output.valid := io.connections(connectedIn).valid
  io.connections(connectedIn).ready := io.output.ready
  io.output.bits.data := io.connections(connectedIn).bits.data
  io.output.bits.isHeader := io.connections(connectedIn).bits.isHeader

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
    when (io.connections(connectedIn).bits.append) {
      connstateIn := NetworkDirections.Here.asUInt
    }
    when (io.output.ready) {
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
      println("Usage: <command> <outputDir> PacketOutHandler <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new PacketOutHandler(params)
    }
  }
}
