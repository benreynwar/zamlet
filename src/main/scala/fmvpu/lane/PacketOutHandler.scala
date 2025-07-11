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
  val handlerRequest = Input(UInt(4.W))
  val handlerConfirm = Input(UInt(4.W))
  val handlerResponse = Output(UInt(4.W))
  
  // Connection inputs from packet input handlers
  // Input order depends on output direction:
  // - Standard order: (north, east, south, west, here) = bits (0,1,2,3,4)
  // - If outputDirection=south: inputs are (west, here, north, east) = (3,4,0,1)
  // - If outputDirection=north: inputs are (east, south, west, here) = (1,2,3,4)
  // This prevents packets from bouncing back to their input direction
  val connections = Flipped(Vec(4, Decoupled(new PacketData(params))))
  
  // Output to downstream
  val output = Decoupled(new NetworkWord(params))
}

/**
 * Packet Output Handler states
 */
object PacketOutHandlerStates extends ChiselEnum {
  val Disconnected = Value(0.U)
  val Connected = Value(1.U)
}

/**
 * Packet Output Handler Module
 */
class PacketOutHandler(params: LaneParams) extends Module {
  val io = IO(new PacketOutHandlerIO(params))
  
  // State registers
  val state = RegInit(PacketOutHandlerStates.Disconnected)
  val connectedIn = RegInit(0.U(2.W))  // Which input handler we're connected to (0-3)
  
  // Global priority counter for all 5 directions (North=0, East=1, South=2, West=3, Here=4)
  // All output handlers share the same priority sequence
  val globalPriority = RegInit(4.U)  // Start with Here for all output handlers
  
  // Update global priority every cycle through all 5 directions
  globalPriority := (globalPriority + 1.U) % 5.U
  
  // Current priority input handler index (using next global priority to stay in sync)
  val currentPriorityInput = mapGlobalToLocalInput((globalPriority + 1.U) % 5.U, io.outputDirection)
  
  // Default outputs
  io.handlerResponse := 0.U
  io.connections.foreach(_.ready := false.B)
  io.output.valid := false.B
  io.output.bits := DontCare
  
  // Map global priority (0=North, 1=East, 2=South, 3=West, 4=Here) to local input index (0-3)
  // based on our output direction, excluding our own direction
  def mapGlobalToLocalInput(globalPriority: UInt, outputDirection: NetworkDirections.Type): UInt = {
    MuxLookup(outputDirection, 0.U)(Seq(
      NetworkDirections.North -> MuxLookup(globalPriority, 0.U)(Seq(
        1.U -> 0.U,  // East -> input 0
        2.U -> 1.U,  // South -> input 1  
        3.U -> 2.U,  // West -> input 2
        4.U -> 3.U   // Here -> input 3
      )),
      NetworkDirections.South -> MuxLookup(globalPriority, 0.U)(Seq(
        3.U -> 0.U,  // West -> input 0
        4.U -> 1.U,  // Here -> input 1
        0.U -> 2.U,  // North -> input 2
        1.U -> 3.U   // East -> input 3
      )),
      NetworkDirections.East -> MuxLookup(globalPriority, 0.U)(Seq(
        2.U -> 0.U,  // South -> input 0
        3.U -> 1.U,  // West -> input 1
        4.U -> 2.U,  // Here -> input 2
        0.U -> 3.U   // North -> input 3
      )),
      NetworkDirections.West -> MuxLookup(globalPriority, 0.U)(Seq(
        4.U -> 0.U,  // Here -> input 0
        0.U -> 1.U,  // North -> input 1
        1.U -> 2.U,  // East -> input 2
        2.U -> 3.U   // South -> input 3
      )),
      // Here case: inputs are North=0, East=1, South=2, West=3 (standard order)
      NetworkDirections.Here -> MuxLookup(globalPriority, 0.U)(Seq(
        0.U -> 0.U,  // North -> input 0
        1.U -> 1.U,  // East -> input 1
        2.U -> 2.U,  // South -> input 2
        3.U -> 3.U   // West -> input 3
      ))
    ))
  }
  
  // Helper function to select which input handler gets priority for new connections
  // Uses round-robin scheduling starting from current priority input
  // Returns the index (0-3) of the highest priority requester
  def getHighestPriorityRequester(requests: UInt, currentPriority: UInt): UInt = {
    // Check priority order starting from current priority
    MuxCase(0.U, Seq(
      requests(currentPriority) -> currentPriority,
      requests((currentPriority + 1.U) % 4.U) -> ((currentPriority + 1.U) % 4.U),
      requests((currentPriority + 2.U) % 4.U) -> ((currentPriority + 2.U) % 4.U),
      requests((currentPriority + 3.U) % 4.U) -> ((currentPriority + 3.U) % 4.U)
    ))
  }
  
  // Main state machine
  switch(state) {
    is(PacketOutHandlerStates.Disconnected) {
      // Check for handler requests using priority order
      when(io.handlerRequest =/= 0.U) {
        val selectedHandler = getHighestPriorityRequester(io.handlerRequest, currentPriorityInput)
        val selectedMask = UIntToOH(selectedHandler, 4)
        
        // Respond to selected handler
        io.handlerResponse := selectedMask
        
        // Check if they confirm the connection
        when((io.handlerConfirm & selectedMask) =/= 0.U) {
          connectedIn := selectedHandler
          state := PacketOutHandlerStates.Connected
        }
      }
    }
    
    is(PacketOutHandlerStates.Connected) {
      // Connect to selected input handler
      io.connections(connectedIn).ready := io.output.ready
      
      // Forward data from connected input - convert PacketData to NetworkWord
      io.output.valid := io.connections(connectedIn).valid
      io.output.bits.data := io.connections(connectedIn).bits.data
      io.output.bits.isHeader := io.connections(connectedIn).bits.isHeader
      
      // Handle state transitions based on packet data
      when(io.connections(connectedIn).valid && io.output.ready) {
        when(io.connections(connectedIn).bits.last) {
          // Last word sent, disconnect
          state := PacketOutHandlerStates.Disconnected
        }.elsewhen(io.connections(connectedIn).bits.append) {
          // Switch connection to 'here' input handler
          val hereInputIndex = mapGlobalToLocalInput(4.U, io.outputDirection) // 4.U = Here
          connectedIn := hereInputIndex
          // Stay connected to continue packet from 'here'
        }
      }
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
