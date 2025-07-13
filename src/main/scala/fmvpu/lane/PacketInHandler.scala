package fmvpu.lane

import chisel3._
import chisel3.util._
import fmvpu.utils._

/**
 * Direction bit constants for 5-bit direction fields
 */
object DirectionBits {
  val NORTH_BIT = 0
  val EAST_BIT = 1 
  val SOUTH_BIT = 2
  val WEST_BIT = 3
  val HERE_BIT = 4
  
  val NORTH_MASK = 1 << NORTH_BIT
  val EAST_MASK = 1 << EAST_BIT
  val SOUTH_MASK = 1 << SOUTH_BIT
  val WEST_MASK = 1 << WEST_BIT
  val HERE_MASK = 1 << HERE_BIT
  
  /**
   * Convert NetworkDirection to corresponding direction mask
   */
  def directionToMask(direction: NetworkDirections.Type): UInt = {
    MuxLookup(direction.asUInt, 0.U)(Seq(
      NetworkDirections.North.asUInt -> NORTH_MASK.U,
      NetworkDirections.East.asUInt -> EAST_MASK.U,
      NetworkDirections.South.asUInt -> SOUTH_MASK.U,
      NetworkDirections.West.asUInt -> WEST_MASK.U,
      NetworkDirections.Here.asUInt -> HERE_MASK.U
    ))
  }
}

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
  val handlerRequest = Output(Vec(5, Bool()))
  
  // Outputs to packet handlers (5 connections)
  val outputs = Vec(5, Decoupled(new PacketData(params)))
  
  // Error outputs
  val errors = Output(new PacketInHandlerErrors)
}


/**
 * Packet In Handler Module
 */
class PacketInHandler(params: LaneParams) extends Module {
  val io = IO(new PacketInHandlerIO(params))
  
  // Register declarations
  val bufferedDirections = RegInit(0.U(5.W))
  val remainingWords = RegInit(0.U(params.packetLengthWidth.W))
  val isAppend = RegInit(false.B)

  // Default outputs
  io.fromNetwork.ready := false.B
  io.forward.ready := false.B
  io.handlerRequest := VecInit(Seq.fill(5)(false.B))
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
    
    // Bit mapping: North=0, East=1, South=2, West=3, Here=4
    directions := (canGoNorth << DirectionBits.NORTH_BIT) | 
                  (canGoEast << DirectionBits.EAST_BIT) | 
                  (canGoSouth << DirectionBits.SOUTH_BIT) | 
                  (canGoWest << DirectionBits.WEST_BIT) | 
                  DirectionBits.HERE_MASK.U
    
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
    val needsNorth = targetY < io.thisY
    val needsSouth = targetY > io.thisY
    
    val isAtTarget = (targetX === io.thisX) && (targetY === io.thisY)
    
    when(isAtTarget) {
      // Packet is for this node
      directions := DirectionBits.HERE_MASK.U // Here only
    }.otherwise {
      // Route towards target - use dimension-order routing (X first, then Y)
      when(needsEast || needsWest) {
        // Move in X direction first
        directions := Mux(needsEast, DirectionBits.EAST_MASK.U, DirectionBits.WEST_MASK.U)
      }.otherwise {
        // X is correct, move in Y direction
        directions := Mux(needsNorth, DirectionBits.NORTH_MASK.U, DirectionBits.SOUTH_MASK.U)
      }
    }
    
    directions
  }

  // When data arrives it goes into a buffer to break the forwards and
  // backwards paths.
  // ---------------------------------------------------------------
  val buffered = Wire(Decoupled(new NetworkWord(params)))
  val buffer = Module(new DoubleBuffer(new NetworkWord(params)))
  buffer.io.i <> io.fromNetwork
  buffer.io.o <> buffered

  // From the output of that skid buffer we look at the header.
  // We work out what directions it wants to go.
  // ----------------------------------------------------------
  val bufferedHeader = buffered.bits.data.asTypeOf(new PacketHeader(params))
  // What direction we go if this is a normal route
  val regularDirections = calculateRegularRouting(bufferedHeader.xDest, bufferedHeader.yDest)
  // What directions we go if this is a broadcast route
  val broadcastResult = calculateBroadcastRouting(bufferedHeader.broadcastDirection, bufferedHeader.xDest, bufferedHeader.yDest)
  val broadcastDirections = broadcastResult._1
  val badBroadcastRoute = broadcastResult._2

  // Get the actual directions based on whether we are broadcasting or forwarding or neither
  val directions = Wire(UInt(5.W))
  when(bufferedHeader.isBroadcast) {
    directions := broadcastDirections
  }.elsewhen(bufferedHeader.forward) {
    // Packet needs forwarding - use forward direction plus regular routing
    val fwdDir = DirectionBits.directionToMask(io.forward.bits.networkDirection)
    directions := regularDirections | fwdDir
  }.otherwise {
    // Regular routing only
    directions := regularDirections
  }

  // Filter out input direction and check for routing error

  // Todo (3)
  // We send handlerRequest to all the PacketOutHandlers it wants to go to. (except back in same dir)
  val inputDirMask = UIntToOH(io.inputDirection.asUInt, 5)
  val otherDirections = directions & ~inputDirMask

  // This is comes from otherDirections when we're processing the header and
  // otherwise comes from a registered version from the last header.
  val connectionDirections = Wire(UInt(5.W))
  when(buffered.bits.isHeader) {
    connectionDirections := otherDirections
  }.otherwise {
    connectionDirections := bufferedDirections
  }

  val badRegularRoute = (connectionDirections & inputDirMask) =/= 0.U
  // We get ready back from those that can accept it. (have to reverse because of Uint vs Seq ordering default)
  val outputReadys = Cat(io.outputs.map(_.ready).reverse)
  dontTouch(outputReadys)
  dontTouch(connectionDirections)
  // We sent valid to them all if we get ready back from all of them.
  val allTargetOutputsReady = (outputReadys | ~connectionDirections).andR
  dontTouch(allTargetOutputsReady)

  // Whenever we have a header coming out of the buffer we are trying to
  // make a new connection.

  io.handlerRequest := VecInit(Seq.fill(5)(false.B))

  when(buffered.valid && buffered.bits.isHeader) {
    remainingWords := bufferedHeader.length
    when (bufferedHeader.isBroadcast) {
      io.errors.broadcastError := badBroadcastRoute
    }
    io.errors.routingError := badRegularRoute
    when(bufferedHeader.forward) {
      io.forward.ready := true.B
    }
    when(!bufferedHeader.forward || io.forward.valid) {
      // We send the request unless we don't have forward data.
      val requestBits = connectionDirections & ~inputDirMask
      io.handlerRequest := VecInit((0 until 5).map(i => requestBits(i)))
      // All our targets are ready to receive
      when(allTargetOutputsReady) {
        // Buffer the routing directions for the reset of the packet.
        bufferedDirections := otherDirections
      }
    }
    // Determine append mode from forward data if forwarding, otherwise false
    when(bufferedHeader.forward && io.forward.valid) {
      val forwardHeader = io.forward.bits.header.asTypeOf(new PacketHeader(params))
      isAppend := io.forward.bits.append
    }.otherwise {
      isAppend := false.B
    }
  }
  when(buffered.valid && buffered.ready && !buffered.bits.isHeader) {
    remainingWords := remainingWords - 1.U
  }
  // For each direction, check if all OTHER directions that need outputs are ready
  val otherOutputsReady = Wire(Vec(5, Bool()))
  for (i <- 0 until 5) {
    val otherDirectionsMask = connectionDirections & ~(1.U << i).asUInt
    val otherReadys = Cat((0 until 5).map(j => 
      if (j == i) true.B else (io.outputs(j).ready || !otherDirectionsMask(j))
    ))
    otherOutputsReady(i) := otherReadys.andR
  }

  buffered.ready := allTargetOutputsReady

  io.outputs.zipWithIndex.foreach { case (out, idx) =>
    val shouldOutput = connectionDirections(idx)
    out.valid := buffered.valid && shouldOutput && otherOutputsReady(idx)
    out.bits.data := buffered.bits.data
    out.bits.isHeader := buffered.bits.isHeader
    out.bits.last := !isAppend && ((!buffered.bits.isHeader && remainingWords === 1.U) || (buffered.bits.isHeader && bufferedHeader.length === 0.U))
    out.bits.append := isAppend && ((!buffered.bits.isHeader && remainingWords === 1.U) || (buffered.bits.isHeader && bufferedHeader.length === 0.U))
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
