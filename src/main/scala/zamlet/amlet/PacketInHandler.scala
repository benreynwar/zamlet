package zamlet.amlet

import chisel3._
import chisel3.util._
import zamlet.utils._

/**
 * Packet In Handler error bundle
 */
class PacketInHandlerErrors extends Bundle {
  val routingError = Bool()     // Trying to send back in input direction
}

/**
 * Packet In Handler IO
 */
class PacketInHandlerIO(params: AmletParams) extends Bundle {
  // Current position
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))
  
  // Direction we're receiving from
  val inputDirection = Input(NetworkDirections())
  
  // Input from one direction (N/S/E/W)
  val fromNetwork = Flipped(Decoupled(new NetworkWord(params)))
  
  // Forward data input (from PacketInterface for forwarding packets)
  val forward = Flipped(Valid(new PacketForward(params)))
  
  // Outputs to packet handlers (5 connections)
  val outputs = Vec(5, Decoupled(new PacketData(params)))
  
  // Error outputs
  val errors = Output(new PacketInHandlerErrors)
}


/**
 * Packet In Handler Module
 */
class PacketInHandler(params: AmletParams) extends Module {
  val io = IO(new PacketInHandlerIO(params))
  
  // Register declarations
  val bufferedDirectionsNext = Wire(UInt(5.W))
  val bufferedDirections = RegNext(bufferedDirectionsNext, 0.U)
  bufferedDirectionsNext := bufferedDirections
  val bufferedFwdDirectionsNext = Wire(UInt(5.W))
  val bufferedFwdDirections = RegNext(bufferedFwdDirectionsNext, 0.U)
  bufferedFwdDirectionsNext := bufferedFwdDirections
  val remainingWordsNext = Wire(UInt(params.packetLengthWidth.W))
  val remainingWords = RegNext(remainingWordsNext, 0.U)
  remainingWordsNext := remainingWords
  val isAppendNext = Wire(Bool())
  val isAppend = RegNext(isAppendNext, false.B)
  isAppendNext := isAppend


  // Register the 'forward'
  val bufferedForwardInit = Wire(Valid(new PacketForward(params)))
  bufferedForwardInit.valid := false.B
  bufferedForwardInit.bits := DontCare
  val bufferedForward = RegNext(io.forward, bufferedForwardInit)

  // Forward change detection
  val prevForwardValid = RegInit(false.B)
  val prevForwardToggle = RegInit(false.B)
  prevForwardValid := bufferedForward.valid
  prevForwardToggle := bufferedForward.bits.toggle
  
  val freshForward = RegInit(false.B)
  when ((bufferedForward.valid && !prevForwardValid) || (bufferedForward.bits.toggle =/= prevForwardToggle)) {
    freshForward := true.B
  } .elsewhen (!bufferedForward.valid) {
    freshForward := false.B
  }

  // Default outputs
  io.outputs.foreach { out =>
    out.valid := false.B
    out.bits := DontCare
  }
  io.errors.routingError := false.B
  
  // Helper function for broadcast routing
  def calculateBroadcastRouting(targetX: UInt, targetY: UInt): UInt = {
    val directions = Wire(UInt(5.W))
    
    // Always go to 'here'
    val here = "b00001".U
    
    // Calculate which directions we can still go based on broadcast type and bounds
    val canGoNorth = (io.thisY > targetY)
    val canGoSouth = (io.thisY < targetY)
    val canGoEast = (io.thisX < targetX)
    val canGoWest = (io.thisX > targetX)
    
    // Bit mapping: North=0, East=1, South=2, West=3, Here=4
    directions := (canGoNorth << DirectionBits.NORTH_BIT) | 
                  (canGoEast << DirectionBits.EAST_BIT) | 
                  (canGoSouth << DirectionBits.SOUTH_BIT) | 
                  (canGoWest << DirectionBits.WEST_BIT) | 
                  DirectionBits.HERE_MASK.U
    
    directions
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
  val bufferedFromNetwork = Wire(Flipped(Decoupled(new NetworkWord(params))))
  bufferedFromNetwork <> DoubleBuffer(io.fromNetwork, params.networkNodeParams.iaForwardBuffer, params.networkNodeParams.iaBackwardBuffer)
  dontTouch(bufferedFromNetwork)

  // From the output of that skid buffer we look at the header.
  // We work out what directions it wants to go.
  // ----------------------------------------------------------
  val bufferedHeader = bufferedFromNetwork.bits.data.asTypeOf(new PacketHeader(params))
  // What direction we go if this is a normal route
  val regularDirections = calculateRegularRouting(bufferedHeader.xDest, bufferedHeader.yDest)
  // What directions we go if this is a broadcast route
  val broadcastDirections = calculateBroadcastRouting(bufferedHeader.xDest, bufferedHeader.yDest)
  val fwdDir = DirectionBits.directionToMask(bufferedForward.bits.networkDirection)

  // Get the actual directions based on whether we are broadcasting or forwarding or neither
  val directions = Wire(UInt(5.W))
  when(bufferedHeader.isBroadcast) {
    directions := broadcastDirections
  }.elsewhen(bufferedHeader.forward) {
    // Packet needs forwarding - use forward direction plus regular routing
    directions := regularDirections | fwdDir
  }.otherwise {
    // Regular routing only
    directions := regularDirections
  }

  // Filter out input direction and check for routing error
  // Send handlerRequest to all the PacketOutHandlers it wants to go to (except back in same direction)
  val inputDirMask = UIntToOH(io.inputDirection.asUInt, 5)
  val otherDirections = directions & ~inputDirMask
  dontTouch(otherDirections)

  // This is comes from otherDirections when we're processing the header and
  // otherwise comes from a registered version from the last header.
  val connectionDirections = Wire(UInt(5.W))
  val connectionFwdDirections = Wire(UInt(5.W))


  when (bufferedFromNetwork.bits.isHeader) {
    connectionDirections := otherDirections
    connectionFwdDirections := fwdDir
  } .otherwise {
    connectionDirections := bufferedDirections
    connectionFwdDirections := bufferedFwdDirections
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

  when(bufferedFromNetwork.valid && bufferedFromNetwork.bits.isHeader) {
    remainingWordsNext := bufferedHeader.length
    io.errors.routingError := badRegularRoute
    when(!bufferedHeader.forward || bufferedForward.valid) {
      // All our targets are ready to receive
      when(bufferedFromNetwork.ready) {
        // Buffer the routing directions for the reset of the packet.
        bufferedDirectionsNext := otherDirections
        bufferedFwdDirectionsNext := fwdDir
      }
    }
    // Determine append mode from forward data if forwarding, otherwise false
    when(bufferedHeader.forward && bufferedForward.valid) {
      // This packet is getting forwarded and we're also 
      // going to append some local data onto it.
      // We tell the PacketOutHandler this so it can switch it's state to
      // accept the data for appending.
      isAppendNext := bufferedForward.bits.append
      freshForward := false.B
    }.otherwise {
      isAppendNext := false.B
    }
  }
  when(bufferedFromNetwork.valid && bufferedFromNetwork.ready && !bufferedFromNetwork.bits.isHeader) {
    remainingWordsNext := remainingWords - 1.U
  }
  // For each direction, check if all OTHER directions that need outputs are ready
  val otherOutputsReady = Wire(Vec(5, Bool()))
  val otherDirectionsMask = Wire(Vec(5, UInt(5.W)))
  val otherReadys = Wire(Vec(5, UInt(5.W)))
  
  for (i <- 0 until 5) {
    otherDirectionsMask(i) := (connectionDirections) & ~(1.U(5.W) << i)
    otherReadys(i) := Cat((0 until 5).map(j => 
      if (j == i) true.B else (io.outputs(j).ready || !otherDirectionsMask(i)(j))
    ))
    otherOutputsReady(i) := otherReadys(i).andR
  }

  val missingForwardTarget = (bufferedFromNetwork.bits.isHeader && bufferedHeader.forward && !bufferedForward.valid)

  // We consume the buffer if we can send the data
  // or if we're appending this packet and can discard the header.
  bufferedFromNetwork.ready := (
    // The outputs are all ready and we have the forwarding info 
    (allTargetOutputsReady && (!missingForwardTarget)) ||
    // We're appending this packet and discarding the header
    (bufferedFromNetwork.bits.isHeader && bufferedHeader.mode === PacketHeaderModes.Append) 
  )

  io.outputs.zipWithIndex.foreach { case (out, idx) =>
    when (bufferedHeader.mode === PacketHeaderModes.Append && bufferedFromNetwork.bits.isHeader) {
      // We don't output the header if we're appending this packet.
      // FIXME: This feels sus. I don't understand why we have this logic.
      out.valid := false.B
    } .otherwise {
      out.valid := bufferedFromNetwork.valid && connectionDirections(idx) && otherOutputsReady(idx) && !missingForwardTarget
    }
    when (bufferedHeader.forward && connectionFwdDirections(idx) && bufferedFromNetwork.bits.isHeader) {
      val newHeader = Wire(new PacketHeader(params))
      newHeader.length := bufferedHeader.length + bufferedHeader.appendLength
      newHeader.xDest := bufferedForward.bits.xDest
      newHeader.yDest := bufferedForward.bits.yDest
      newHeader.mode := bufferedHeader.mode
      newHeader.forward := bufferedForward.bits.forward
      newHeader.isBroadcast := false.B
      newHeader.appendLength := bufferedHeader.appendLength
      out.bits.data := newHeader.asUInt
    } .otherwise {
      out.bits.data := bufferedFromNetwork.bits.data
    }
    out.bits.isHeader := bufferedFromNetwork.bits.isHeader
    when ((!bufferedFromNetwork.bits.isHeader && remainingWords === 1.U) || (bufferedFromNetwork.bits.isHeader && bufferedHeader.length === 0.U)) {
      if (idx == DirectionBits.HERE_BIT) {
        out.bits.last := true.B
        out.bits.append := false.B
      } else {
        out.bits.last := !isAppend
        out.bits.append := isAppend
      }
    } .otherwise {
      out.bits.last := false.B
      out.bits.append := false.B
    }
  }
}

/**
 * Module generator for PacketInHandler
 */
object PacketInHandlerGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> PacketInHandler <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new PacketInHandler(params)
    }
  }
}
