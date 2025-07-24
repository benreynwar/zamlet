package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * Packet header structure
 */
class PacketHeader(params: AmletParams) extends Bundle {
  val length = UInt(params.packetLengthWidth.W)
  val xDest = UInt(params.xPosWidth.W)
  val yDest = UInt(params.yPosWidth.W)
  val mode = PacketHeaderModes()
  val forward = Bool()
  val isBroadcast = Bool()
  val appendLength = UInt(4.W)
}

/**
 * Network word from this node
 */
class FromHereNetworkWord(params: AmletParams) extends Bundle {
  val data = UInt(params.width.W)
  val isHeader = Bool()
  val channel = UInt(log2Ceil(params.nChannels).W)
}

/**
 * Network word to this node
 */
class NetworkWord(params: AmletParams) extends Bundle {
  val data = UInt(params.width.W)
  val isHeader = Bool()
}


/**
 * Packet forward information
 */
class PacketForward(params: AmletParams) extends Bundle {
  val networkDirection = NetworkDirections()
  val xDest = UInt(params.xPosWidth.W)
  val yDest = UInt(params.yPosWidth.W)
  val forward = Bool()
  val append = Bool()
  val toggle = Bool()
}

/**
 * Instruction memory write
 */
class IMWrite(params: AmletParams) extends Bundle {
  val address = UInt(16.W) // instrAddrWidth equivalent
  val data = UInt(32.W)    // instructionWidth equivalent
}

/**
 * Packet header modes enumeration
 */
object PacketHeaderModes extends ChiselEnum {
  val Normal = Value(0.U)
  val Command = Value(1.U)
  val Append = Value(2.U)
  val Undefined = Value(3.U)
}

/**
 * Network directions for forwarding
 */
object NetworkDirections extends ChiselEnum {
  val North = Value(0.U)
  val East = Value(1.U)
  val South = Value(2.U)
  val West = Value(3.U)
  val Here = Value(4.U)
}

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
class PacketData(params: AmletParams) extends Bundle {
  val data = UInt(params.width.W)
  val isHeader = Bool()
  val last = Bool()
  val append = Bool()
}

/**
 * Packet routing utilities
 */
object PacketRouting {
  def calculateNextDirection(params: AmletParams, thisX: UInt, thisY: UInt, targetX: UInt, targetY: UInt): NetworkDirections.Type = {
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
    }.elsewhen(needsSouth) {
      direction := NetworkDirections.South
    }.elsewhen(needsNorth) {
      direction := NetworkDirections.North
    }.otherwise {
      direction := NetworkDirections.Here
    }
    
    direction
  }
}
