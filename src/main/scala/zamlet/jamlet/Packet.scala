package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams

/**
 * Send type enumeration
 */
object SendType extends ChiselEnum {
  val Single = Value(0.U)
  val Broadcast = Value(1.U)
}

/**
 * Message type enumeration
 */
object MessageType extends ChiselEnum {
  val Send = Value(0.U)
  val Instructions = Value(1.U)
  val Reserved2 = Value(2.U)
  val Reserved3 = Value(3.U)
  val WriteLine = Value(4.U)
  val WriteLineResp = Value(5.U)
  val ReadLine = Value(6.U)
  val ReadLineResp = Value(7.U)
  val WriteLineReadLine = Value(8.U)
  val WriteLineReadLineResp = Value(9.U)
  val ReadByte = Value(10.U)
  val ReadByteResp = Value(11.U)
  val Reserved12 = Value(12.U)
  val Reserved13 = Value(13.U)
  val Reserved14 = Value(14.U)
  val Reserved15 = Value(15.U)
  val LoadJ2JWordsReq = Value(16.U)
  val LoadJ2JWordsResp = Value(17.U)
  val LoadJ2JWordsDrop = Value(18.U)
  val LoadJ2JWordsRetry = Value(19.U)
  val StoreJ2JWordsReq = Value(20.U)
  val StoreJ2JWordsResp = Value(21.U)
  val StoreJ2JWordsDrop = Value(22.U)
  val StoreJ2JWordsRetry = Value(23.U)
  val LoadWordReq = Value(24.U)
  val LoadWordResp = Value(25.U)
  val LoadWordDrop = Value(26.U)
  val LoadWordRetry = Value(27.U)
  val StoreWordReq = Value(28.U)
  val StoreWordResp = Value(29.U)
  val StoreWordDrop = Value(30.U)
  val StoreWordRetry = Value(31.U)
  val ReadMemWordReq = Value(32.U)
  val ReadMemWordResp = Value(33.U)
  val ReadMemWordDrop = Value(34.U)
  val Reserved35 = Value(35.U)
  val WriteMemWordReq = Value(36.U)
  val WriteMemWordResp = Value(37.U)
  val WriteMemWordDrop = Value(38.U)
  val WriteMemWordRetry = Value(39.U)
  val IdentQueryResp = Value(40.U)
  val Reserved41 = Value(41.U)
  val WriteLineReadLineDrop = Value(42.U)
  val Reserved43 = Value(43.U)
  val Reserved44 = Value(44.U)
  val Reserved45 = Value(45.U)
  val Reserved46 = Value(46.U)
  val Reserved47 = Value(47.U)
  val Reserved48 = Value(48.U)
  val Reserved49 = Value(49.U)
  val Reserved50 = Value(50.U)
  val LoadIndexedElementResp = Value(51.U)
  val Reserved52 = Value(52.U)
  val StoreIndexedElementResp = Value(53.U)
}

/**
 * Packet header structure (base class) - not instantiated directly
 * Python: 43 bits (target_x:8, target_y:8, source_x:8, source_y:8, length:4, message_type:5, send_type:2)
 */
class PacketHeader(params: ZamletParams) extends Bundle {
  val targetX = UInt(params.xPosWidth.W)
  val targetY = UInt(params.yPosWidth.W)
  val sourceX = UInt(params.xPosWidth.W)
  val sourceY = UInt(params.yPosWidth.W)
  val length = UInt(4.W)
  val messageType = MessageType()
  val sendType = SendType()
}

/**
 * Header with instruction identifier - not instantiated directly
 * Python: 48 bits (+5 for ident)
 * Note: Python uses 5-bit ident, params.identWidth is 7
 */
class IdentHeader(params: ZamletParams) extends PacketHeader(params) {
  val ident = UInt(params.identWidth.W)
}

/**
 * Header with ident and tag for multi-response protocols
 * Python: 52 bits (+4 for tag)
 */
class TaggedHeader(params: ZamletParams) extends IdentHeader(params) {
  val tag = UInt(4.W)
}

/**
 * Tagged header with per-word mask for J2J operations
 * 10-bit mask (reduced from Python's 12 to fit with 7-bit ident)
 */
class MaskedTaggedHeader(params: ZamletParams) extends TaggedHeader(params) {
  val mask = UInt(10.W)

  require(this.getWidth <= params.wordWidth,
    s"MaskedTaggedHeader exceeds word width: ${this.getWidth} > ${params.wordWidth}")
}

/**
 * Header for WriteMemWord requests
 * Python: TaggedHeader + dst_byte_in_word(3) + n_bytes(3)
 */
class WriteMemWordHeader(params: ZamletParams) extends TaggedHeader(params) {
  val dstByteInWord = UInt(3.W)
  val nBytes = UInt(3.W)

  require(this.getWidth <= params.wordWidth,
    s"WriteMemWordHeader exceeds word width: ${this.getWidth} > ${params.wordWidth}")
}

/**
 * Header for ReadMemWord requests
 * Python: TaggedHeader + fault flag
 */
class ReadMemWordHeader(params: ZamletParams) extends TaggedHeader(params) {
  val fault = Bool()

  require(this.getWidth <= params.wordWidth,
    s"ReadMemWordHeader exceeds word width: ${this.getWidth} > ${params.wordWidth}")
}

/**
 * Network word
 */
class NetworkWord(params: ZamletParams) extends Bundle {
  val data = UInt(params.wordWidth.W)
  val isHeader = Bool()
}

/**
 * Network directions
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
class PacketData(params: ZamletParams) extends Bundle {
  val data = UInt(params.wordWidth.W)
  val isHeader = Bool()
  val last = Bool()
}

/**
 * Packet routing utilities
 */
object PacketRouting {
  def calculateNextDirection(params: ZamletParams, thisX: UInt, thisY: UInt,
                             targetX: UInt, targetY: UInt): NetworkDirections.Type = {
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
