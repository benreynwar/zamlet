package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
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
class PacketInHandlerIO(params: ZamletParams) extends Bundle {
  // Current position
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))

  // Direction we're receiving from
  val inputDirection = Input(NetworkDirections())

  // Input from one direction (N/S/E/W)
  val fromNetwork = Flipped(Decoupled(new NetworkWord(params)))

  // Outputs to packet handlers (5 connections)
  val outputs = Vec(5, Decoupled(new PacketData(params)))

  val errors = Output(new PacketInHandlerErrors)
}


/**
 * Packet In Handler Module
 *
 * Routes incoming packets to the appropriate output directions based on:
 * - Single send: dimension-order routing to target
 * - Broadcast: flood to all directions within bounds
 */
class PacketInHandler(params: ZamletParams) extends Module {
  val io = IO(new PacketInHandlerIO(params))
  
  // Register declarations
  val bufferedDirectionsNext = Wire(UInt(5.W))
  val bufferedDirections = RegNext(bufferedDirectionsNext, 0.U)
  bufferedDirectionsNext := bufferedDirections

  val remainingWordsNext = Wire(UInt(4.W))
  val remainingWords = RegNext(remainingWordsNext, 0.U)
  remainingWordsNext := remainingWords

  // Default outputs
  io.outputs.foreach { out =>
    out.valid := false.B
    out.bits := DontCare
  }
  io.errors.routingError := false.B
  
  // Helper function for broadcast routing
  def calculateBroadcastRouting(targetX: UInt, targetY: UInt): UInt = {
    val directions = Wire(UInt(5.W))

    // Calculate which directions we can still go based on broadcast bounds
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
  val bufferedFromNetwork = Wire(Flipped(Decoupled(new NetworkWord(params))))
  bufferedFromNetwork <> DoubleBuffer(io.fromNetwork,
    params.networkNodeParams.iaForwardBuffer, params.networkNodeParams.iaBackwardBuffer)
  dontTouch(bufferedFromNetwork)

  // From the output of that skid buffer we look at the header.
  // We work out what directions it wants to go.
  val bufferedHeader = bufferedFromNetwork.bits.data.asTypeOf(new PacketHeader(params))
  // What direction we go if this is a normal route
  val regularDirections = calculateRegularRouting(bufferedHeader.targetX, bufferedHeader.targetY)
  // What directions we go if this is a broadcast route
  val broadcastDirections = calculateBroadcastRouting(bufferedHeader.targetX, bufferedHeader.targetY)

  // Get the actual directions based on send type
  val directions = Wire(UInt(5.W))
  when(bufferedHeader.sendType === SendType.Broadcast) {
    directions := broadcastDirections
  }.otherwise {
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

  when (bufferedFromNetwork.bits.isHeader) {
    connectionDirections := otherDirections
  } .otherwise {
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
  when(bufferedFromNetwork.valid && bufferedFromNetwork.bits.isHeader) {
    remainingWordsNext := bufferedHeader.length
    io.errors.routingError := badRegularRoute
    when(bufferedFromNetwork.ready) {
      // Buffer the routing directions for the rest of the packet.
      bufferedDirectionsNext := otherDirections
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

  // We consume the buffer if we can send the data to all target outputs
  bufferedFromNetwork.ready := allTargetOutputsReady

  io.outputs.zipWithIndex.foreach { case (out, idx) =>
    out.valid := bufferedFromNetwork.valid && connectionDirections(idx) && otherOutputsReady(idx)
    out.bits.data := bufferedFromNetwork.bits.data
    out.bits.isHeader := bufferedFromNetwork.bits.isHeader
    val isLastWord = (!bufferedFromNetwork.bits.isHeader && remainingWords === 1.U) ||
                     (bufferedFromNetwork.bits.isHeader && bufferedHeader.length === 0.U)
    out.bits.last := isLastWord
  }
}

/**
 * Module generator for PacketInHandler
 */
object PacketInHandlerGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> PacketInHandler <jamletParamsFileName>")
      null
    } else {
      val params = ZamletParams.fromFile(args(0))
      new PacketInHandler(params)
    }
  }
}
