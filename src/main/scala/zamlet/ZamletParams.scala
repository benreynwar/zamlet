package zamlet

import chisel3._
import chisel3.util._
import io.circe._
import io.circe.parser._
import io.circe.generic.semiauto._
import scala.io.Source

class Ordering extends Bundle {
  val wf = WidthFormat()
  val laneOrder = LaneOrder()
}

case class RfSliceParams(
  // Mask port
  maskReqForwardBuffer: Boolean = false,
  maskReqBackwardBuffer: Boolean = false,
  maskRespForwardBuffer: Boolean = false,
  maskRespBackwardBuffer: Boolean = false,

  // Index port
  indexReqForwardBuffer: Boolean = false,
  indexReqBackwardBuffer: Boolean = false,
  indexRespForwardBuffer: Boolean = false,
  indexRespBackwardBuffer: Boolean = false,

  // Data port
  dataReqForwardBuffer: Boolean = false,
  dataReqBackwardBuffer: Boolean = false,
  dataRespForwardBuffer: Boolean = false,
  dataRespBackwardBuffer: Boolean = false,

  // LocalExec port
  localExecReqForwardBuffer: Boolean = false,
  localExecReqBackwardBuffer: Boolean = false,
  localExecRespForwardBuffer: Boolean = false,
  localExecRespBackwardBuffer: Boolean = false
)

case class SynchronizerParams(
  maxConcurrentSyncs: Int = 4,
  resultOutputReg: Boolean = false,
  portOutOutputReg: Boolean = false,
  minPipelineReg: Boolean = false
)

case class NetworkNodeParams(
  iaForwardBuffer: Boolean = false,
  iaBackwardBuffer: Boolean = true,
  abForwardBuffer: Boolean = true,
  abBackwardBuffer: Boolean = true,
  boForwardBuffer: Boolean = false,
  boBackwardBuffer: Boolean = true,
  hiForwardBuffer: Boolean = true,
  hiBackwardBuffer: Boolean = true,
  hoForwardBuffer: Boolean = true,
  hoBackwardBuffer: Boolean = true
)

case class IssueUnitParams(
  exForwardBuffer: Boolean = false,
  exBackwardBuffer: Boolean = false,
  tlbReqForwardBuffer: Boolean = false,
  tlbReqBackwardBuffer: Boolean = false,
  tlbRespInputReg: Boolean = false,
  toIdentTrackerForwardBuffer: Boolean = false,
  toIdentTrackerBackwardBuffer: Boolean = false,
  comOutputReg: Boolean = false,
  killInputReg: Boolean = false
)

case class JteStateParams(
  inputReqFB: Boolean = true,
  inputReqBB: Boolean = true,
  inputRespFB: Boolean = true,
  inputRespBB: Boolean = true,
  initiatorDispatchFB: Boolean = false,
  initiatorDispatchBB: Boolean = false,
  receiverUpdateFB: Boolean = false,
  receiverUpdateBB: Boolean = false,
  slotToRegReqFB: Boolean = false,
  slotToRegReqBB: Boolean = false,
  slotToRegRespFB: Boolean = false,
  slotToRegRespBB: Boolean = false,
  createBuffer: Boolean = true,
  clearBuffer: Boolean = true,
  initiatorCommitBuffer: Boolean = false,
  dispatchABFB: Boolean = true,
  dispatchABBB: Boolean = true,
  dispatchBCFB: Boolean = true,
  dispatchBCBB: Boolean = true,
)

case class JteInitiatorParams(
  inputFB: Boolean = false,
  inputBB: Boolean = false,
  rfDataReqFB: Boolean = true,
  rfDataReqBB: Boolean = true,
  rfMaskReqFB: Boolean = true,
  rfMaskReqBB: Boolean = true,
  rfIndexReqFB: Boolean = true,
  rfIndexReqBB: Boolean = true,
  abFB: Boolean = true,
  abBB: Boolean = true,
  bcFB: Boolean = true,
  bcBB: Boolean = true,
  rfMaskRespFB: Boolean = true,
  rfMaskRespBB: Boolean = true,
  rfDataRespFB: Boolean = true,
  rfDataRespBB: Boolean = true,
  rfIndexRespFB: Boolean = true,
  rfIndexRespBB: Boolean = true,
  cdFB: Boolean = true,
  cdBB: Boolean = true,
  deFB: Boolean = true,
  deBB: Boolean = true,
  tlbReqFB: Boolean = true,
  tlbReqBB: Boolean = true,
  orderingReqFB: Boolean = true,
  orderingReqBB: Boolean = true,
  efFB: Boolean = true,
  efBB: Boolean = true,
  fgFB: Boolean = true,
  fgBB: Boolean = true,
  ghFB: Boolean = true,
  ghBB: Boolean = true,
  tlbRespFB: Boolean = true,
  tlbRespBB: Boolean = true,
  orderingRespFB: Boolean = true,
  orderingRespBB: Boolean = true,
  commitBuffer: Boolean = false,
  hiFB: Boolean = true,
  hiBB: Boolean = true,
  packetFB: Boolean = true,
  packetBB: Boolean = true,
)

case class JteReceiverParams(
  packetFB: Boolean = true,
  packetBB: Boolean = true,
  slotToRegReqFB: Boolean = false,
  slotToRegReqBB: Boolean = false,
  abFB: Boolean = true,
  abBB: Boolean = true,
  slotToRegRespFB: Boolean = false,
  slotToRegRespBB: Boolean = false,
  rfWriteReqFB: Boolean = true,
  rfWriteReqBB: Boolean = true,
  bcFB: Boolean = true,
  bcBB: Boolean = true,
  rfWriteRespFB: Boolean = true,
  rfWriteRespBB: Boolean = true,
  cdFB: Boolean = true,
  cdBB: Boolean = true,
  updateMsgFB: Boolean = false,
  updateMsgBB: Boolean = false,
)

case class JteHandlerParams(
  packetInFB: Boolean = true,
  packetInBB: Boolean = true,
  abFB: Boolean = true,
  abBB: Boolean = true,
  cacheLineReqFB: Boolean = true,
  cacheLineReqBB: Boolean = true,
  bcFB: Boolean = true,
  bcBB: Boolean = true,
  cdFB: Boolean = true,
  cdBB: Boolean = true,
  cacheLineRespFB: Boolean = true,
  cacheLineRespBB: Boolean = true,
  deFB: Boolean = true,
  deBB: Boolean = true,
  sramReqFB: Boolean = true,
  sramReqBB: Boolean = true,
  efFB: Boolean = true,
  efBB: Boolean = true,
  fgFB: Boolean = true,
  fgBB: Boolean = true,
  sramRespFB: Boolean = true,
  sramRespBB: Boolean = true,
  ghFB: Boolean = true,
  ghBB: Boolean = true,
  packetOutFB: Boolean = true,
  packetOutBB: Boolean = true,
)

case class SramParams(
  localA: Boolean = true,
  localB: Boolean = false,
  localC: Boolean = true,
  jteAFB: Boolean = true,
  jteABB: Boolean = true,
  jteBFB: Boolean = false,
  jteBBB: Boolean = false,
  jteCFB: Boolean = true,
  jteCBB: Boolean = true,
) {
  def localResponseLatency: Int = Seq(localA, localB, localC).count(identity)
}

case class JceParams(
  opFB: Boolean = true,
  opBB: Boolean = true,
  sramReadReqFB: Boolean = true,
  sramReadReqBB: Boolean = true,
  abFB: Boolean = true,
  abBB: Boolean = true,
  bcFB: Boolean = true,
  bcBB: Boolean = true,
  sramReadRespFB: Boolean = true,
  sramReadRespBB: Boolean = true,
  cdFB: Boolean = true,
  cdBB: Boolean = true,
  packetOutFB: Boolean = true,
  packetOutBB: Boolean = true,
  packetInFB: Boolean = true,
  packetInBB: Boolean = true,
  sramWriteReqFB: Boolean = true,
  sramWriteReqBB: Boolean = true,
  sramWriteRespFB: Boolean = true,
  sramWriteRespBB: Boolean = true,
  rxABFB: Boolean = true,
  rxABBB: Boolean = true,
  rxBCFB: Boolean = true,
  rxBCBB: Boolean = true,
  rxDoneFB: Boolean = true,
)

case class ZamletParams(
  // Position widths
  xPosWidth: Int = 8,
  yPosWidth: Int = 8,

  // Grid dimensions (must all be powers of 2)
  kCols: Int = 2,
  kRows: Int = 1,
  jCols: Int = 2,
  jRows: Int = 2,

  // Word width (shared: SRAM, network, RF)
  wordBytes: Int = 8,

  // SRAM configuration
  sramDepth: Int = 256,      // Number of words in SRAM
  log2CacheSlotWordsPerJamlet: Int = 2,  // Words per jamlet per cache slot

  // Register file slice
  rfSliceWords: Int = 48,    // Number of words in RF slice

  // Address and index widths
  memAddrWidth: Int = 48,       // Global memory address width
  log2PageWordsPerJamlet: Int = 4,  // Page size in words per jamlet
  // Must hold j_in_l * word_bytes * max_lmul
  elementIndexWidth: Int = 22,
  log2NParams: Int = 4,

  // WitemTable configuration
  witemTableDepth: Int = 16,

  // Instruction identifier
  identWidth: Int = 7,
  writesetWidth: Int = 4,

  // Memlet configuration
  nMemletGatheringSlots: Int = 4, // Concurrent WRITE_LINE_READ_LINE operations
  nResponseBufferSlots: Int = 4,  // Concurrent read responses in flight
  memBeatWords: Int = 1,          // Words per external memory beat
  memAxiIdBits: Int = 4,          // AXI4 transaction ID width

  // Zamlet-level parameters
  maxResponseTags: Int = 128,   // Number of instruction identifiers
  instructionQueueLength: Int = 8,  // Instruction queue depth per kamlet
  lamletDispatchQueueDepth: Int = 8,  // Lamlet dispatch queue depth

  // IdentTracker buffering
  identTrackerOutForwardBuffer: Boolean = true,
  identTrackerOutBackwardBuffer: Boolean = true,

  // Network configuration
  nAChannels: Int = 1,
  nBChannels: Int = 1,
  networkNodeParams: NetworkNodeParams = NetworkNodeParams(),

  // IssueUnit configuration
  issueUnitParams: IssueUnitParams = IssueUnitParams(),

  // Synchronizer configuration
  synchronizerParams: SynchronizerParams = SynchronizerParams(),

  // RfSlice configuration
  rfSliceParams: RfSliceParams = RfSliceParams(),

  // JTE configuration
  jteStateParams: JteStateParams = JteStateParams(),
  jteInitiatorParams: JteInitiatorParams = JteInitiatorParams(),
  jteReceiverParams: JteReceiverParams = JteReceiverParams(),
  jteHandlerParams: JteHandlerParams = JteHandlerParams(),
  sramParams: SramParams = SramParams(),
  jceParams: JceParams = JceParams(),

  messageLengthWidth: Int = 4,
  messageTypeWidth: Int = 6

) {
  // Grid derived
  def jInK: Int = jCols * jRows
  def kInL: Int = kCols * kRows
  def jInL: Int = jInK * kInL
  def jTotalCols: Int = jCols * kCols
  def jTotalRows: Int = jRows * kRows
  def jTotal: Int = jTotalCols * jTotalRows

  // Grid dimensions must be powers of 2 for efficient bit-slice operations
  require((kCols & (kCols - 1)) == 0 && kCols > 0, s"kCols must be power of 2, got $kCols")
  require((kRows & (kRows - 1)) == 0 && kRows > 0, s"kRows must be power of 2, got $kRows")
  require((jCols & (jCols - 1)) == 0 && jCols > 0, s"jCols must be power of 2, got $jCols")
  require((jRows & (jRows - 1)) == 0 && jRows > 0, s"jRows must be power of 2, got $jRows")
  require((wordBytes & (wordBytes - 1)) == 0 && wordBytes > 0,
    s"wordBytes must be power of 2, got $wordBytes")
  require(cacheSlotWords % jInK == 0,
    s"cacheSlotWords ($cacheSlotWords) must be divisible by jInK ($jInK)")
  require(cacheSlotWords % memBeatWords == 0,
    s"cacheSlotWords ($cacheSlotWords) must be divisible by memBeatWords ($memBeatWords)")
  require(cacheSlotWordsPerJamlet <= 12,
    s"cacheSlotWordsPerJamlet ($cacheSlotWordsPerJamlet) must be <= 12 to fit in 4-bit " +
    s"packet length field (WRITE_LINE_READ_LINE needs 3 + wordsPerJamlet words)")

  def log2JInL: Int = Integer.numberOfTrailingZeros(jInL)
  def log2JTotalCols: Int = Integer.numberOfTrailingZeros(jTotalCols)
  def log2JTotalRows: Int = Integer.numberOfTrailingZeros(jTotalRows)
  def log2KCols: Int = Integer.numberOfTrailingZeros(kCols)
  def log2JCols: Int = Integer.numberOfTrailingZeros(jCols)
  def log2JRows: Int = Integer.numberOfTrailingZeros(jRows)
  def log2JTotal: Int = Integer.numberOfTrailingZeros(jTotal)
  def log2WordWidth: Int = Integer.numberOfTrailingZeros(wordWidth)
  def log2WordBytes: Int = Integer.numberOfTrailingZeros(wordBytes)
  def endElementIndexWidth: Int = log2JInL + log2WordBytes + 1

  def pageWordsPerJamlet: Int = 1 << log2PageWordsPerJamlet

  def cacheSlotWordsPerJamlet: Int = 1 << log2CacheSlotWordsPerJamlet
  def cacheSlotWords: Int = cacheSlotWordsPerJamlet * jInK
  def memBeatsPerCacheLine: Int = cacheSlotWords / memBeatWords

  def nMemletRouters: Int = {
    val edgeHeight = kRows * jRows
    val nSideCols = kCols / 2
    val nMemlets = nSideCols * kRows
    val nEdgeCols = (nMemlets + edgeHeight - 1) / edgeHeight
    val memletsPerCol = (nMemlets + nEdgeCols - 1) / nEdgeCols
    edgeHeight / memletsPerCol
  }
  def memletLocalJamlets: Int = jInK / nMemletRouters
  def memletLocalWords: Int = memletLocalJamlets * cacheSlotWordsPerJamlet

  def pageBytesPerJamlet: Int = pageWordsPerJamlet * wordBytes
  def pageBytesPerKamlet: Int = pageBytesPerJamlet * jInK
  def pageBytesPerZamlet: Int = pageBytesPerKamlet * kInL
  def log2PageBytesPerZamlet: Int = Integer.numberOfTrailingZeros(pageBytesPerZamlet)

  def log2StripeBytes: Int = log2JInL + log2WordBytes
  def log2StripesInPage: Int = log2PageWordsPerJamlet

  def pageAddrWidth: Int = memAddrWidth - log2PageWordsPerJamlet - log2JInL
  def cacheLineAddrWidth: Int = memAddrWidth - log2CacheSlotWordsPerJamlet - log2JInL

  // Calculated parameters
  def wordWidth: Int = wordBytes * 8
  def sramAddrWidth: Int = log2Ceil(sramDepth)
  def rfAddrWidth: Int = log2Ceil(rfSliceWords)
  def nCacheSlots: Int = sramDepth / cacheSlotWords
  def cacheSlotWidth: Int = log2Ceil(nCacheSlots)
  def kIndexWidth: Int = log2Ceil(kInL)
  def memStripeAddrWidth: Int = memAddrWidth - log2JInL

  class JCoords extends Bundle {
    val x = UInt(xPosWidth.W)
    val y = UInt(yPosWidth.W)
  }

  // Types
  def xPos(): UInt = UInt(xPosWidth.W)
  def yPos(): UInt = UInt(yPosWidth.W)
  def ident(): UInt = UInt(identWidth.W)
  def cacheSlot(): UInt = UInt(cacheSlotWidth.W)
  def cacheLineAddr(): UInt = UInt(cacheLineAddrWidth.W)
  def word(): UInt = UInt(wordWidth.W)
  def memAddr(): UInt = UInt(memAddrWidth.W)
  def elementIndex(): UInt = UInt(elementIndexWidth.W)
  def rfAddr(): UInt = UInt(rfAddrWidth.W)
  def writeset(): UInt = UInt(writesetWidth.W)
}


object ZamletParams {
  implicit val rfSliceParamsDecoder: Decoder[RfSliceParams] = deriveDecoder[RfSliceParams]
  implicit val synchronizerParamsDecoder: Decoder[SynchronizerParams] = deriveDecoder[SynchronizerParams]
  implicit val networkNodeParamsDecoder: Decoder[NetworkNodeParams] = deriveDecoder[NetworkNodeParams]
  implicit val issueUnitParamsDecoder: Decoder[IssueUnitParams] = deriveDecoder[IssueUnitParams]
  implicit val jteStateParamsDecoder: Decoder[JteStateParams] = deriveDecoder[JteStateParams]
  implicit val jteInitiatorParamsDecoder: Decoder[JteInitiatorParams] = deriveDecoder[JteInitiatorParams]
  implicit val jteReceiverParamsDecoder: Decoder[JteReceiverParams] = deriveDecoder[JteReceiverParams]
  implicit val jteHandlerParamsDecoder: Decoder[JteHandlerParams] = deriveDecoder[JteHandlerParams]
  implicit val sramParamsDecoder: Decoder[SramParams] = deriveDecoder[SramParams]
  implicit val jceParamsDecoder: Decoder[JceParams] = deriveDecoder[JceParams]
  implicit val zamletParamsDecoder: Decoder[ZamletParams] = deriveDecoder[ZamletParams]

  def fromFile(fileName: String): ZamletParams = {
    val jsonContent = Source.fromFile(fileName).mkString
    val paramsResult = decode[ZamletParams](jsonContent)
    paramsResult match {
      case Right(params) => params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}
