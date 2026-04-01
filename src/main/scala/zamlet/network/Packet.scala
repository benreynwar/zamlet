package zamlet.network

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
  val WriteLineData = Value(2.U)
  val Reserved3 = Value(3.U)
  val WriteLineAddr = Value(4.U)
  val WriteLineResp = Value(5.U)
  val ReadLineAddr = Value(6.U)
  val ReadLineResp = Value(7.U)
  val WriteLineReadLineAddr = Value(8.U)
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
  val WriteLineReadLineAddrDrop = Value(42.U)
  val ReadLineAddrDrop = Value(43.U)
  val WriteLineAddrDrop = Value(44.U)
  val WriteLineDataDrop = Value(45.U)
  val Reserved46 = Value(46.U)
  val Reserved47 = Value(47.U)
  val Reserved48 = Value(48.U)
  val Reserved49 = Value(49.U)
  val Reserved50 = Value(50.U)
  val LoadIndexedElementResp = Value(51.U)
  val Reserved52 = Value(52.U)
  val StoreIndexedElementResp = Value(53.U)
  val Reserved54 = Value(54.U)
  val Reserved55 = Value(55.U)
  val Reserved56 = Value(56.U)
  val Reserved57 = Value(57.U)
  val Reserved58 = Value(58.U)
  val Reserved59 = Value(59.U)
  val Reserved60 = Value(60.U)
  val Reserved61 = Value(61.U)
  val Reserved62 = Value(62.U)
  val Reserved63 = Value(63.U)
}

object PacketConstants {
  val lengthWidth = 4.W
  val tagWidth = 4.W
  val maskWidth = 4.W
}

/**
 * Abstract packet header with shared routing fields.
 * Not instantiated directly — use PacketHeader for decoding routing fields,
 * or a concrete subclass (AddressHeader, etc.) for full headers.
 */
abstract class AbstractPacketHeader(params: ZamletParams) extends Bundle {
  val targetX = UInt(params.xPosWidth.W)
  val targetY = UInt(params.yPosWidth.W)
  val sourceX = UInt(params.xPosWidth.W)
  val sourceY = UInt(params.yPosWidth.W)
  val length = UInt(PacketConstants.lengthWidth)
  val messageType = MessageType()
  val sendType = SendType()

  def baseWidth: Int = 2 * params.xPosWidth + 2 * params.yPosWidth +
    PacketConstants.lengthWidth.get + MessageType.getWidth + SendType.getWidth
}

/**
 * Concrete packet header padded to word width. Safe to use for decoding
 * routing fields from any header type since the shared fields are always
 * at the same MSB positions.
 */
class PacketHeader(params: ZamletParams) extends AbstractPacketHeader(params) {
  val _padding = UInt((params.wordWidth - baseWidth).W)
}

/**
 * Abstract header with instruction identifier.
 */
abstract class AbstractIdentHeader(params: ZamletParams) extends AbstractPacketHeader(params) {
  val ident = UInt(params.identWidth.W)

  def identHeaderWidth: Int = baseWidth + params.identWidth
}

/**
 * Concrete ident header padded to word width.
 */
class IdentHeader(params: ZamletParams) extends AbstractIdentHeader(params) {
  val _padding = UInt((params.wordWidth - identHeaderWidth).W)
}

/**
 * Abstract header with ident and tag for multi-response protocols.
 */
abstract class AbstractTaggedHeader(params: ZamletParams) extends AbstractIdentHeader(params) {
  val tag = UInt(PacketConstants.tagWidth)

  def taggedHeaderWidth: Int = identHeaderWidth + PacketConstants.tagWidth.get
}

/**
 * Concrete tagged header padded to word width.
 */
class TaggedHeader(params: ZamletParams) extends AbstractTaggedHeader(params) {
  val _padding = UInt((params.wordWidth - taggedHeaderWidth).W)
}

/**
 * Masked tagged header with per-word mask for J2J operations.
 */
class MaskedTaggedHeader(params: ZamletParams) extends AbstractTaggedHeader(params) {
  val mask = UInt(PacketConstants.maskWidth)
  val _padding = UInt((params.wordWidth - taggedHeaderWidth -
    PacketConstants.maskWidth.get).W)
}

/**
 * Abstract header with ident and SRAM word address for cache line operations.
 */
abstract class AbstractAddressHeader(params: ZamletParams) extends AbstractIdentHeader(params) {
  val address = UInt(params.sramAddrWidth.W)

  def addressHeaderWidth: Int = identHeaderWidth + params.sramAddrWidth
}

/**
 * Concrete address header padded to word width.
 */
class AddressHeader(params: ZamletParams) extends AbstractAddressHeader(params) {
  val _padding = UInt((params.wordWidth - addressHeaderWidth).W)
}

/**
 * Header for WriteMemWord requests.
 */
class WriteMemWordHeader(params: ZamletParams) extends AbstractTaggedHeader(params) {
  val dstByteInWord = UInt(3.W)
  val nBytes = UInt(3.W)
  val _padding = UInt((params.wordWidth - taggedHeaderWidth - 6).W)
}

/**
 * Header for ReadMemWord requests.
 */
class ReadMemWordHeader(params: ZamletParams) extends AbstractTaggedHeader(params) {
  val fault = Bool()
  val _padding = UInt((params.wordWidth - taggedHeaderWidth - 1).W)
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
