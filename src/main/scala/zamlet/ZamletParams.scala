package zamlet

import chisel3._
import chisel3.util._
import io.circe._
import io.circe.parser._
import io.circe.generic.semiauto._
import java.io.File
import scala.io.Source
import scala.util.control.NonFatal

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

case class PacketMergeParams(
  inputFB: Boolean = true,
  inputBB: Boolean = true,
  outputFB: Boolean = true,
  outputBB: Boolean = true,
)

case class MessageTypePacketRouterParams(
  inputFB: Boolean = true,
  inputBB: Boolean = true,
  outputFB: Boolean = true,
  outputBB: Boolean = true,
)

case class ReservationStationParams(
  renamedInFB: Boolean = false,
  renamedInBB: Boolean = false,
  issue01FB: Boolean = true,
  issue01BB: Boolean = true,
  issue12FB: Boolean = true,
  issue12BB: Boolean = true,
  immediateKinstrBuffer: Boolean = false,
  kteIssueFB: Boolean = false,
  kteIssueBB: Boolean = false,
  kceClaimSlotReqFB: Boolean = false,
  kceClaimSlotReqBB: Boolean = false,
  kceClaimSlotRespFB: Boolean = false,
  kceClaimSlotRespBB: Boolean = false,
  rfReleaseFB: Boolean = false,
  rfReleaseBB: Boolean = false,
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
  zFB: Boolean = true,
  zBB: Boolean = true,
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
  efFB: Boolean = true,
  efBB: Boolean = true,
  fgFB: Boolean = true,
  fgBB: Boolean = true,
  ghFB: Boolean = true,
  ghBB: Boolean = true,
  tlbRespFB: Boolean = true,
  tlbRespBB: Boolean = true,
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

case class KceCacheTableParams(
  hasSlotReqFB: Boolean = true,
  hasSlotReqBB: Boolean = true,
  hasSlotRespFB: Boolean = true,
  hasSlotRespBB: Boolean = true,
  allocSlotReqFB: Boolean = true,
  allocSlotReqBB: Boolean = true,
  allocSlotRespFB: Boolean = true,
  allocSlotRespBB: Boolean = true,
  rsHasSlotReqBuffer: Boolean = true,
  rsHasSlotRespBuffer: Boolean = true,
  slotIsAvailableBuffer: Boolean = true,
  memletPacketInFB: Boolean = true,
  memletPacketInBB: Boolean = true,
  memletPacketOutFB: Boolean = true,
  memletPacketOutBB: Boolean = true,
  maxActiveUsesPerCacheSlot: Int = 7,
)

case class KceScannerParams(
  emptyQueueDepth: Int = 16,
  emptyQueueScanBackpressureDepth: Int = 8,
)

case class TagTableParams(
  nUsesWidth: Int = 3,
  freeQueueDepth: Int = 16,
  fillReqQueueDepth: Int = 16,
  scanBackpressureDepth: Int = 8,
  allocReqFB: Boolean = true,
  allocReqBB: Boolean = true,
  alloc01FB: Boolean = true,
  alloc01BB: Boolean = true,
  allocRespFB: Boolean = true,
  allocRespBB: Boolean = true,
  claimReqFB: Boolean = true,
  claimReqBB: Boolean = true,
  claimRespFB: Boolean = true,
  claimRespBB: Boolean = true,
  fillBuffer: Boolean = true,
  releaseBuffer: Boolean = true,
  scan01FB: Boolean = true,
  scan01BB: Boolean = true,
) {
  def nUses(): UInt = UInt(nUsesWidth.W)
}

case class KcePendingTableParams(
  cacheLineReqFB: Boolean = true,
  cacheLineReqBB: Boolean = true,
  cacheLineRespFB: Boolean = true,
  cacheLineRespBB: Boolean = true,
  replayFB: Boolean = true,
  replayBB: Boolean = true,
  cacheLineReleaseBuffer: Boolean = true,
  claimSlotReqFB: Boolean = true,
  claimSlotReqBB: Boolean = true,
  claimSlotRespFB: Boolean = true,
  claimSlotRespBB: Boolean = true,
  allocSlotReqFB: Boolean = true,
  allocSlotReqBB: Boolean = true,
  allocSlotRespFB: Boolean = true,
  allocSlotRespBB: Boolean = true,
  releaseSlotBuffer: Boolean = true,
  slotIsAvailableBuffer: Boolean = true,
  req01FB: Boolean = true,
  req01BB: Boolean = true,
  req23FB: Boolean = true,
  req23BB: Boolean = true,
  req34FB: Boolean = true,
  req34BB: Boolean = true,
  req45FB: Boolean = true,
  req45BB: Boolean = true,
  alloc01FB: Boolean = true,
  alloc01BB: Boolean = true,
  alloc12FB: Boolean = true,
  alloc12BB: Boolean = true,
)

case class KceMemletInterfaceParams(
  fetchSlotReqFB: Boolean = true,
  fetchSlotReqBB: Boolean = true,
  fetchSlotCompleteBuffer: Boolean = true,
  jceWritebackReqBuffer: Boolean = true,
  jceFetchDoneBuffer: Boolean = true,
  writebackSlotReqFB: Boolean = true,
  writebackSlotReqBB: Boolean = true,
  writebackSlotCompleteBuffer: Boolean = true,
  packetInFB: Boolean = true,
  packetInBB: Boolean = true,
  packetOutFB: Boolean = true,
  packetOutBB: Boolean = true,
  fetch01FB: Boolean = true,
  fetch01BB: Boolean = true,
  fetchTx01FB: Boolean = true,
  fetchTx01BB: Boolean = true,
)

case class KamletTlbParams(
  tlbReqFB: Boolean = true,
  tlbReqBB: Boolean = true,
  tlbRespFB: Boolean = true,
  tlbRespBB: Boolean = true,
  tlbAvailableBuffer: Boolean = true,
  localOrderingUpdateBuffer: Boolean = true,
  packetInFB: Boolean = true,
  packetInBB: Boolean = true,
  packetOutFB: Boolean = true,
  packetOutBB: Boolean = true,
  lookup01FB: Boolean = true,
  lookup01BB: Boolean = true,
  lookup12FB: Boolean = true,
  lookup12BB: Boolean = true,
  reqTx01FB: Boolean = true,
  reqTx01BB: Boolean = true,
  resp01FB: Boolean = true,
  resp01BB: Boolean = true,
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
  memAddrWidth: Int = 44,       // Global memory address width
  log2PageWordsPerJamlet: Int = 4,  // Page size in words per jamlet
  // Must hold j_in_l * word_bytes * max_lmul
  elementIndexWidth: Int = 22,
  log2NParams: Int = 6,
  paramRefIdxWidth: Int = 3,

  // WitemTable configuration
  witemTableDepth: Int = 16,
  kcePendingTableDepth: Int = 16,
  kteCacheWaitTableDepth: Int = 16,
  tlbReqTableDepth: Int = 16,
  tlbCacheTableDepth: Int = 64,

  // Instruction identifier
  identWidth: Int = 8,
  syncIdentWidth: Int = 3,
  syncValueWidth: Int = 16,
  writesetWidth: Int = 4,

  // Memlet configuration
  nMemletGatheringSlots: Int = 4, // Concurrent WRITE_LINE_READ_LINE operations
  nCacheRequests: Int = 16,       // Concurrent cache line requests from KCE
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
  resetPipelineDepth: Int = 8,
  networkNodeParams: NetworkNodeParams = NetworkNodeParams(),
  kamletPacketMergeParams: PacketMergeParams = PacketMergeParams(),
  kamletAIngressPacketRouterParams: MessageTypePacketRouterParams = MessageTypePacketRouterParams(),
  kamletBIngressPacketRouterParams: MessageTypePacketRouterParams = MessageTypePacketRouterParams(),
  reservationStationParams: ReservationStationParams = ReservationStationParams(),

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

  // KCE cache table configuration
  kceCacheTableParams: KceCacheTableParams = KceCacheTableParams(),
  kceScannerParams: KceScannerParams = KceScannerParams(),
  kceTagTableParams: TagTableParams = TagTableParams(),
  kcePendingTableParams: KcePendingTableParams = KcePendingTableParams(),
  kceMemletInterfaceParams: KceMemletInterfaceParams = KceMemletInterfaceParams(),
  kamletTlbParams: KamletTlbParams = KamletTlbParams(),
  tlbTagTableParams: TagTableParams = TagTableParams(),

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
  require((1 << identWidth) > maxResponseTags,
    s"identWidth ($identWidth) must be able to represent maxResponseTags ($maxResponseTags)")

  def log2JInL: Int = Integer.numberOfTrailingZeros(jInL)
  def log2JTotalCols: Int = Integer.numberOfTrailingZeros(jTotalCols)
  def log2JTotalRows: Int = Integer.numberOfTrailingZeros(jTotalRows)
  def log2KCols: Int = Integer.numberOfTrailingZeros(kCols)
  def log2JCols: Int = Integer.numberOfTrailingZeros(jCols)
  def log2JRows: Int = Integer.numberOfTrailingZeros(jRows)
  def log2JInK: Int = Integer.numberOfTrailingZeros(jInK)
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
  def maxConcurrentSyncs: Int = 1 << syncIdentWidth
  class JCoords extends Bundle {
    val x = UInt(xPosWidth.W)
    val y = UInt(yPosWidth.W)
  }

  // Types
  def xPos(): UInt = UInt(xPosWidth.W)
  def yPos(): UInt = UInt(yPosWidth.W)
  def ident(): UInt = UInt(identWidth.W)
  def syncIdent(): UInt = UInt(syncIdentWidth.W)
  def syncValue(): UInt = UInt(syncValueWidth.W)
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
  implicit val packetMergeParamsDecoder: Decoder[PacketMergeParams] = deriveDecoder[PacketMergeParams]
  implicit val messageTypePacketRouterParamsDecoder: Decoder[MessageTypePacketRouterParams] =
    deriveDecoder[MessageTypePacketRouterParams]
  implicit val reservationStationParamsDecoder: Decoder[ReservationStationParams] =
    deriveDecoder[ReservationStationParams]
  implicit val issueUnitParamsDecoder: Decoder[IssueUnitParams] = deriveDecoder[IssueUnitParams]
  implicit val jteStateParamsDecoder: Decoder[JteStateParams] = deriveDecoder[JteStateParams]
  implicit val jteInitiatorParamsDecoder: Decoder[JteInitiatorParams] = deriveDecoder[JteInitiatorParams]
  implicit val jteReceiverParamsDecoder: Decoder[JteReceiverParams] = deriveDecoder[JteReceiverParams]
  implicit val jteHandlerParamsDecoder: Decoder[JteHandlerParams] = deriveDecoder[JteHandlerParams]
  implicit val sramParamsDecoder: Decoder[SramParams] = deriveDecoder[SramParams]
  implicit val jceParamsDecoder: Decoder[JceParams] = deriveDecoder[JceParams]
  implicit val kceCacheTableParamsDecoder: Decoder[KceCacheTableParams] = deriveDecoder[KceCacheTableParams]
  implicit val kceScannerParamsDecoder: Decoder[KceScannerParams] = deriveDecoder[KceScannerParams]
  implicit val tagTableParamsDecoder: Decoder[TagTableParams] = deriveDecoder[TagTableParams]
  implicit val kcePendingTableParamsDecoder: Decoder[KcePendingTableParams] = deriveDecoder[KcePendingTableParams]
  implicit val kceMemletInterfaceParamsDecoder: Decoder[KceMemletInterfaceParams] = deriveDecoder[KceMemletInterfaceParams]
  implicit val kamletTlbParamsDecoder: Decoder[KamletTlbParams] = deriveDecoder[KamletTlbParams]
  implicit val zamletParamsDecoder: Decoder[ZamletParams] = deriveDecoder[ZamletParams]

  private def readFile(file: File): String = {
    val source = Source.fromFile(file)
    try {
      source.mkString
    } finally {
      source.close()
    }
  }

  private def deepMerge(base: Json, overrideJson: Json): Json = {
    (base.asObject, overrideJson.asObject) match {
      case (Some(baseObject), Some(overrideObject)) =>
        val mergedKeys = baseObject.keys.toSet ++ overrideObject.keys.toSet
        Json.fromJsonObject(JsonObject.fromIterable(mergedKeys.toSeq.map { key =>
          val mergedValue = (baseObject(key), overrideObject(key)) match {
            case (Some(baseValue), Some(overrideValue)) => deepMerge(baseValue, overrideValue)
            case (Some(baseValue), None) => baseValue
            case (None, Some(overrideValue)) => overrideValue
            case (None, None) => Json.Null
          }
          key -> mergedValue
        }))
      case _ => overrideJson
    }
  }

  private def withoutMetadata(json: Json): Json = {
    json.mapObject(_.remove("base"))
  }

  private def loadJsonWithBase(file: File, stack: List[String]): Either[String, Json] = {
    val canonical = file.getCanonicalFile
    val path = canonical.getPath
    if (stack.contains(path)) {
      Left(s"Config inheritance cycle: ${(path :: stack).reverse.mkString(" -> ")}")
    } else {
      val jsonContent = try {
        Right(readFile(canonical))
      } catch {
        case NonFatal(error) => Left(s"Failed to read JSON config $path: ${error.getMessage}")
      }
      jsonContent.flatMap { content =>
        parse(content).left.map(error => s"Failed to parse JSON in $path: $error")
      }.flatMap { json =>
        json.hcursor.downField("base").focus match {
          case Some(baseJson) =>
            baseJson.as[String] match {
              case Right(basePath) =>
                val baseFile = new File(basePath)
                val resolvedBaseFile =
                  if (baseFile.isAbsolute) baseFile else new File(canonical.getParentFile, basePath)
                loadJsonWithBase(resolvedBaseFile, path :: stack).map { loadedBaseJson =>
                  withoutMetadata(deepMerge(loadedBaseJson, json))
                }
              case Left(error) =>
                Left(s"Invalid base field in $path: $error")
            }
          case None =>
            Right(withoutMetadata(json))
        }
      }
    }
  }

  def fromFile(fileName: String): ZamletParams = {
    val paramsResult = loadJsonWithBase(new File(fileName), Nil).flatMap(_.as[ZamletParams].left.map(_.toString))
    paramsResult match {
      case Right(params) => params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}
