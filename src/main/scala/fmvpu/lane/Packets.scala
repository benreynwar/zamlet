package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Packet header format
 */
class PacketHeader(params: LaneParams) extends Bundle {
  val length = UInt(params.packetLengthWidth.W)
  val xDest = UInt(params.xPosWidth.W)
  val yDest = UInt(params.yPosWidth.W)
  val mode = PacketHeaderModes()
  val forward = Bool()
  val isBroadcast = Bool()
  val appendLength = UInt(params.packetLengthWidth.W)
  // Backward compatibility: destination field as concatenated x,y
  def destination: UInt = Cat(yDest, xDest)
}

/**
 * Network word with header indication
 */
class NetworkWord(params: LaneParams) extends Bundle {
  val data = UInt(params.width.W)
  val isHeader = Bool()
}

/**
 * Network word with header indication
 * Extended with channel information
 */
class FromHereNetworkWord(params: LaneParams) extends Bundle {
  val data = UInt(params.width.W)
  val channel = UInt(log2Ceil(params.nChannels).W)
  val isHeader = Bool()
}

/**
 * Instruction memory write bundle
 */
class IMWrite(params: LaneParams) extends Bundle {
  val address = UInt(params.instrAddrWidth.W)
  val data = UInt(params.width.W)
}

/**
 * Packet forward bundle
 */
class PacketForward(params: LaneParams) extends Bundle {
  val networkDirection = NetworkDirections()
  val xDest = UInt(params.xPosWidth.W)
  val yDest = UInt(params.yPosWidth.W)
  val forward = Bool()
  val append = Bool()
  val toggle = Bool()
}

/**
 * Packet routing utilities
 */
object PacketRouting {
  /**
   * Calculate the next network direction for dimension-order routing
   */
  def calculateNextDirection(params: LaneParams, thisX: UInt, thisY: UInt, targetX: UInt, targetY: UInt): NetworkDirections.Type = {
    val needsEast = targetX > thisX
    val needsWest = targetX < thisX
    val needsNorth = targetY < thisY
    val needsSouth = targetY > thisY
    
    // Use dimension-order routing (X first, then Y)
    val direction = Wire(NetworkDirections())
    when(needsEast) {
      direction := NetworkDirections.East
    }.elsewhen(needsWest) {
      direction := NetworkDirections.West
    }.elsewhen(needsNorth) {
      direction := NetworkDirections.North
    }.elsewhen(needsSouth) {
      direction := NetworkDirections.South
    }.otherwise {
      direction := NetworkDirections.Here
    }
    
    direction
  }
  
}

