package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Packet data bundle with control signals
 */
class PacketData(params: LaneParams) extends Bundle {
  val data = UInt(params.width.W)
  val isHeader = Bool()
  val last = Bool()
  val append = Bool()
}

/**
 * Packet processing state bundle
 */
class PacketState(params: LaneParams) extends Bundle {
  val remainingWords = UInt(8.W)
  val isForwarding = Bool()
  val targetDirections = UInt(5.W)
  val isAppending = Bool()
}

/**
 * Packet In Handler error bundle
 */
class PacketInHandlerErrors extends Bundle {
  val routingError = Bool()     // Trying to send back in input direction
  val broadcastError = Bool()   // Broadcast routing error
}

/**
 * Packet In Handler IO
 */
class PacketInHandlerIO(params: LaneParams) extends Bundle {
  // Current position
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))
  
  // Direction we're receiving from
  val inputDirection = Input(NetworkDirections())
  
  // Input from one direction (N/S/E/W)
  val fromNetwork = Flipped(Decoupled(new NetworkWord(params)))
  
  // Forward data input (from PacketInterface for forwarding packets)
  val forward = Flipped(Decoupled(new PacketForward(params)))
  
  
  // Handler arbitration signals
  val handlerResponse = Input(UInt(5.W))
  val handlerRequest = Output(UInt(5.W))
  val handlerConfirm = Output(UInt(5.W))
  
  // Outputs to packet handlers (4 connections)
  val outputs = Vec(4, Decoupled(new PacketData(params)))
  
  // Error outputs
  val errors = Output(new PacketInHandlerErrors)
}

/**
 * Packet In Handler states
 */
object PacketInStates extends ChiselEnum {
  val Idle = Value(0.U)
  val WaitingForForward = Value(1.U)
  val WaitingForHandlers = Value(2.U)
  val Transmitting = Value(3.U)
}

/**
 * Packet In Handler Module
 */
class PacketInHandler(params: LaneParams) extends Module {
  val io = IO(new PacketInHandlerIO(params))
  
  // State registers
  val state = RegInit(PacketInStates.Idle)
  
  // Packet processing state
  val packetState = RegInit({
    val init = Wire(new PacketState(params))
    init.remainingWords := 0.U
    init.isForwarding := false.B
    init.targetDirections := 0.U
    init.isAppending := false.B
    init
  })
  
  // Default outputs
  io.fromNetwork.ready := false.B
  io.forward.ready := false.B
  io.handlerRequest := 0.U
  io.handlerConfirm := 0.U
  io.outputs.foreach { out =>
    out.valid := false.B
    out.bits := DontCare
  }
  io.errors.routingError := false.B
  io.errors.broadcastError := false.B
  
  // Helper function for broadcast routing
  def calculateBroadcastRouting(broadcastDir: BroadcastDirections.Type, targetX: UInt, targetY: UInt): (UInt, Bool) = {
    val directions = Wire(UInt(5.W))
    val error = Wire(Bool())
    
    // Always go to 'here'
    val here = "b00001".U
    
    // Calculate which directions we can still go based on broadcast type and bounds
    val canGoNorth = MuxLookup(broadcastDir, false.B)(Seq(
      BroadcastDirections.NE -> (io.thisY > targetY),
      BroadcastDirections.NW -> (io.thisY > targetY),
      BroadcastDirections.SE -> false.B,
      BroadcastDirections.SW -> false.B
    ))
    
    val canGoSouth = MuxLookup(broadcastDir, false.B)(Seq(
      BroadcastDirections.NE -> false.B,
      BroadcastDirections.NW -> false.B,
      BroadcastDirections.SE -> (io.thisY < targetY),
      BroadcastDirections.SW -> (io.thisY < targetY)
    ))
    
    val canGoEast = MuxLookup(broadcastDir, false.B)(Seq(
      BroadcastDirections.NE -> (io.thisX < targetX),
      BroadcastDirections.NW -> false.B,
      BroadcastDirections.SE -> (io.thisX < targetX),
      BroadcastDirections.SW -> false.B
    ))
    
    val canGoWest = MuxLookup(broadcastDir, false.B)(Seq(
      BroadcastDirections.NE -> false.B,
      BroadcastDirections.NW -> (io.thisX > targetX),
      BroadcastDirections.SE -> false.B,
      BroadcastDirections.SW -> (io.thisX > targetX)
    ))
    
    // Bit mapping: 0=Here, 1=North, 2=South, 3=East, 4=West
    directions := here | (canGoWest << 4) | (canGoEast << 3) | (canGoSouth << 2) | (canGoNorth << 1)
    
    // Error if we've gone past the target bounds for this broadcast type
    error := MuxLookup(broadcastDir, false.B)(Seq(
      BroadcastDirections.NE -> ((io.thisX > targetX) || (io.thisY < targetY)),
      BroadcastDirections.NW -> ((io.thisX < targetX) || (io.thisY < targetY)),
      BroadcastDirections.SE -> ((io.thisX > targetX) || (io.thisY > targetY)),
      BroadcastDirections.SW -> ((io.thisX < targetX) || (io.thisY > targetY))
    ))
    
    (directions, error)
  }
  
  // Helper function for regular routing
  def calculateRegularRouting(targetX: UInt, targetY: UInt): UInt = {
    val directions = Wire(UInt(5.W))
    
    val needsEast = targetX > io.thisX
    val needsWest = targetX < io.thisX
    val needsNorth = targetY > io.thisY
    val needsSouth = targetY < io.thisY
    
    val isAtTarget = (targetX === io.thisX) && (targetY === io.thisY)
    
    when(isAtTarget) {
      // Packet is for this node
      directions := "b00001".U // Here only
    }.otherwise {
      // Route towards target - use dimension-order routing (X first, then Y)
      when(needsEast || needsWest) {
        // Move in X direction first
        directions := Mux(needsEast, "b01000".U, "b10000".U) // East or West
      }.otherwise {
        // X is correct, move in Y direction
        directions := Mux(needsNorth, "b00010".U, "b00100".U) // North or South
      }
    }
    
    directions
  }
  
  // Helper function to calculate target directions
  def calculateTargetDirections(header: PacketHeader, forwardDir: NetworkDirections.Type, isForwarding: Bool): (UInt, Bool, Bool) = {
    val directions = Wire(UInt(5.W))
    val broadcastError = Wire(Bool())
    val routingError = Wire(Bool())
    
    // Extract target coordinates
    val targetX = header.destination(params.xPosWidth - 1, 0)
    val targetY = header.destination(params.targetWidth - 1, params.xPosWidth)
    
    when(header.isBroadcast) {
      // Use broadcast routing
      val (broadcastDirs, bcastError) = calculateBroadcastRouting(header.broadcastDirection, targetX, targetY)
      directions := broadcastDirs
      broadcastError := bcastError
    }.elsewhen(isForwarding) {
      // Packet needs forwarding - use forward direction plus regular routing
      val regularDirs = calculateRegularRouting(targetX, targetY)
      val fwdDir = UIntToOH(forwardDir.asUInt, 5)
      directions := regularDirs | fwdDir
      broadcastError := false.B
    }.otherwise {
      // Regular routing only
      directions := calculateRegularRouting(targetX, targetY)
      broadcastError := false.B
    }
    
    // Filter out input direction and check for routing error
    val inputDirMask = UIntToOH(io.inputDirection.asUInt, 5)
    val filteredDirections = directions & ~inputDirMask
    routingError := (directions & inputDirMask) =/= 0.U
    
    (filteredDirections, broadcastError, routingError)
  }
  
  // Main state machine
  switch(state) {
    is(PacketInStates.Idle) {
      io.fromNetwork.ready := true.B
      
      // Process incoming packet header
      when(io.fromNetwork.valid && io.fromNetwork.bits.isHeader) {
        val header = io.fromNetwork.bits.data.asTypeOf(new PacketHeader(params))
        packetState.remainingWords := header.length
        
        // Calculate base directions for this packet
        val (targetDirs, bcastError, routeError) = calculateTargetDirections(header, NetworkDirections.North, false.B)
        packetState.targetDirections := targetDirs
        io.errors.broadcastError := bcastError
        io.errors.routingError := routeError
        
        when(header.forward && io.forward.valid) {
          // Packet needs forwarding and forward data is available
          io.forward.ready := true.B
          packetState.isForwarding := true.B
          // Add forward direction to existing directions
          packetState.targetDirections := packetState.targetDirections | UIntToOH(io.forward.bits.networkDirection.asUInt, 5)
          state := PacketInStates.WaitingForHandlers
        }.elsewhen(header.forward) {
          // Packet needs forwarding but no forward data yet
          state := PacketInStates.WaitingForForward
          io.forward.ready := true.B
        }.otherwise {
          // Regular packet - proceed to handler acquisition
          state := PacketInStates.WaitingForHandlers
        }
      }
    }
    
    is(PacketInStates.WaitingForForward) {
      // Wait for forward data to arrive
      io.forward.ready := true.B
      when(io.forward.valid) {
        packetState.isForwarding := true.B
        // Add forward direction to existing directions
        packetState.targetDirections := packetState.targetDirections | UIntToOH(io.forward.bits.networkDirection.asUInt, 5)
        state := PacketInStates.WaitingForHandlers
      }
    }
    
    is(PacketInStates.WaitingForHandlers) {
      // Request handler resources
      io.handlerRequest := packetState.targetDirections
      
      // Check if all required handlers responded positively
      val allHandlersResponded = (packetState.targetDirections & io.handlerResponse) === packetState.targetDirections
      
      when(allHandlersResponded) {
        io.handlerConfirm := packetState.targetDirections
        state := PacketInStates.Transmitting
      }
    }
    
    is(PacketInStates.Transmitting) {
      // Create per-output ready signals that exclude each output's own ready
      val perOutputReady = io.outputs.zipWithIndex.map { case (_, thisIdx) =>
        io.outputs.zipWithIndex.map { case (out, idx) =>
          if (idx == thisIdx) true.B // Exclude this output's own ready
          else !packetState.targetDirections(idx) || out.ready
        }.reduce(_ && _)
      }
      
      // Set valid and data on outputs based on their individual ready conditions
      io.outputs.zipWithIndex.foreach { case (out, idx) =>
        when(perOutputReady(idx) && packetState.targetDirections(idx)) {
          out.valid := io.fromNetwork.valid
          out.bits.data := io.fromNetwork.bits.data
          out.bits.isHeader := io.fromNetwork.bits.isHeader
          out.bits.last := packetState.remainingWords === 1.U && !packetState.isAppending
          out.bits.append := packetState.isAppending && packetState.remainingWords === 1.U
        }
      }
      
      // Overall ready when all target outputs have their conditions met
      val allTargetOutputsReady = io.outputs.zipWithIndex.map { case (out, idx) =>
        !packetState.targetDirections(idx) || out.ready
      }.reduce(_ && _)
      
      when(allTargetOutputsReady) {
        io.fromNetwork.ready := true.B
        
        when(io.fromNetwork.valid) {
          packetState.remainingWords := packetState.remainingWords - 1.U
          when(packetState.remainingWords === 1.U) {
            state := PacketInStates.Idle
            packetState.isForwarding := false.B
            packetState.isAppending := false.B
            packetState.targetDirections := 0.U
          }
        }
      }
    }
  }
}

/**
 * Module generator for PacketInHandler
 */
object PacketInHandlerGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> PacketInHandler <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new PacketInHandler(params)
    }
  }
}
