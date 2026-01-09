package zamlet

import chisel3._
import chisel3.util.log2Ceil
import io.circe._
import io.circe.parser._
import io.circe.generic.semiauto._
import scala.io.Source

case class SynchronizerParams(
  maxConcurrentSyncs: Int = 4,
  resultOutputReg: Boolean = false,
  portOutOutputReg: Boolean = false,
  minPipelineReg: Boolean = false
)

case class WitemMonitorParams(
  // Kamlet lifecycle interfaces (Valid)
  witemCreateInputReg: Boolean = false,
  witemCacheAvailInputReg: Boolean = false,
  witemRemoveInputReg: Boolean = false,
  witemCompleteOutputReg: Boolean = false,
  witemSrcUpdateInputReg: Boolean = false,
  witemDstUpdateInputReg: Boolean = false,

  // Sync interfaces (Valid)
  witemFaultReadyOutputReg: Boolean = false,
  witemCompleteReadyOutputReg: Boolean = false,
  witemFaultSyncInputReg: Boolean = false,
  witemCompletionSyncInputReg: Boolean = false,

  // Witem info lookup (Decoupled)
  witemInfoReqForwardBuffer: Boolean = false,
  witemInfoReqBackwardBuffer: Boolean = false,
  witemInfoRespForwardBuffer: Boolean = false,
  witemInfoRespBackwardBuffer: Boolean = false,

  // TLB interface (Decoupled)
  tlbReqForwardBuffer: Boolean = false,
  tlbReqBackwardBuffer: Boolean = false,
  tlbRespForwardBuffer: Boolean = false,
  tlbRespBackwardBuffer: Boolean = false,

  // SRAM interface (Decoupled)
  sramReqForwardBuffer: Boolean = false,
  sramReqBackwardBuffer: Boolean = false,
  sramRespForwardBuffer: Boolean = false,
  sramRespBackwardBuffer: Boolean = false,

  // RF interfaces (Decoupled)
  maskRfReqForwardBuffer: Boolean = false,
  maskRfReqBackwardBuffer: Boolean = false,
  maskRfRespForwardBuffer: Boolean = false,
  maskRfRespBackwardBuffer: Boolean = false,
  indexRfReqForwardBuffer: Boolean = false,
  indexRfReqBackwardBuffer: Boolean = false,
  indexRfRespForwardBuffer: Boolean = false,
  indexRfRespBackwardBuffer: Boolean = false,
  dataRfReqForwardBuffer: Boolean = false,
  dataRfReqBackwardBuffer: Boolean = false,
  dataRfRespForwardBuffer: Boolean = false,
  dataRfRespBackwardBuffer: Boolean = false,

  // Packet output (Decoupled)
  packetOutForwardBuffer: Boolean = false,
  packetOutBackwardBuffer: Boolean = false,

  // Error output
  errOutputReg: Boolean = false,

  // Pipeline stage buffers (S1→S2 through S14→S15)
  s1s2ForwardBuffer: Boolean = false,
  s1s2BackwardBuffer: Boolean = false,
  s2s3ForwardBuffer: Boolean = false,
  s2s3BackwardBuffer: Boolean = false,
  s3s4ForwardBuffer: Boolean = false,
  s3s4BackwardBuffer: Boolean = false,
  s4s5ForwardBuffer: Boolean = false,
  s4s5BackwardBuffer: Boolean = false,
  s5s6ForwardBuffer: Boolean = false,
  s5s6BackwardBuffer: Boolean = false,
  s6s7ForwardBuffer: Boolean = false,
  s6s7BackwardBuffer: Boolean = false,
  s7s8ForwardBuffer: Boolean = false,
  s7s8BackwardBuffer: Boolean = false,
  s8s9ForwardBuffer: Boolean = false,
  s8s9BackwardBuffer: Boolean = false,
  s9s10ForwardBuffer: Boolean = false,
  s9s10BackwardBuffer: Boolean = false,
  s10s11ForwardBuffer: Boolean = false,
  s10s11BackwardBuffer: Boolean = false,
  s11s12ForwardBuffer: Boolean = false,
  s11s12BackwardBuffer: Boolean = false,
  s12s13ForwardBuffer: Boolean = false,
  s12s13BackwardBuffer: Boolean = false,
  s13s14ForwardBuffer: Boolean = false,
  s13s14BackwardBuffer: Boolean = false,
  s14s15ForwardBuffer: Boolean = false,
  s14s15BackwardBuffer: Boolean = false,
  s15s16ForwardBuffer: Boolean = false,
  s15s16BackwardBuffer: Boolean = false
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

case class LamletParams(
  // Position widths
  xPosWidth: Int = 8,
  yPosWidth: Int = 8,

  // Grid dimensions (must all be powers of 2)
  kCols: Int = 2,
  kRows: Int = 1,
  jCols: Int = 1,
  jRows: Int = 1,

  // Word width (shared: SRAM, network, RF)
  wordBytes: Int = 8,

  // SRAM configuration
  sramDepth: Int = 256,      // Number of words in SRAM
  cacheSlotWords: Int = 16,  // Words per cache slot

  // Register file slice
  rfSliceWords: Int = 48,    // Number of words in RF slice

  // Address and index widths
  memAddrWidth: Int = 48,       // Global memory address width
  pageWordsPerJamlet: Int = 4,  // Page size in words per jamlet
  // Must hold j_in_l * word_bytes * max_lmul
  elementIndexWidth: Int = 22,

  // WitemTable configuration
  witemTableDepth: Int = 16,

  // Instruction identifier
  identWidth: Int = 7,

  // Lamlet-level parameters
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

  // WitemMonitor configuration
  witemMonitorParams: WitemMonitorParams = WitemMonitorParams(),

  // IssueUnit configuration
  issueUnitParams: IssueUnitParams = IssueUnitParams(),

  // Synchronizer configuration
  synchronizerParams: SynchronizerParams = SynchronizerParams()
) {
  // Grid derived
  def jInK: Int = jCols * jRows
  def kInL: Int = kCols * kRows
  def jInL: Int = jInK * kInL
  def jTotalCols: Int = jCols * kCols
  def jTotalRows: Int = jRows * kRows

  // Grid dimensions must be powers of 2 for efficient bit-slice operations
  require((kCols & (kCols - 1)) == 0 && kCols > 0, s"kCols must be power of 2, got $kCols")
  require((kRows & (kRows - 1)) == 0 && kRows > 0, s"kRows must be power of 2, got $kRows")
  require((jCols & (jCols - 1)) == 0 && jCols > 0, s"jCols must be power of 2, got $jCols")
  require((jRows & (jRows - 1)) == 0 && jRows > 0, s"jRows must be power of 2, got $jRows")
  require((wordBytes & (wordBytes - 1)) == 0 && wordBytes > 0,
    s"wordBytes must be power of 2, got $wordBytes")

  def log2JInL: Int = Integer.numberOfTrailingZeros(jInL)
  def log2JTotalCols: Int = Integer.numberOfTrailingZeros(jTotalCols)
  def log2KCols: Int = Integer.numberOfTrailingZeros(kCols)
  def log2JCols: Int = Integer.numberOfTrailingZeros(jCols)
  def log2JRows: Int = Integer.numberOfTrailingZeros(jRows)
  def log2WordWidth: Int = Integer.numberOfTrailingZeros(wordWidth)
  def log2WordBytes: Int = Integer.numberOfTrailingZeros(wordBytes)

  def pageBytesPerJamlet: Int = pageWordsPerJamlet * wordBytes
  def pageBytesPerKamlet: Int = pageBytesPerJamlet * jInK
  def pageBytesPerLamlet: Int = pageBytesPerKamlet * kInL
  def log2PageBytesPerLamlet: Int = Integer.numberOfTrailingZeros(pageBytesPerLamlet)

  // Calculated parameters
  def wordWidth: Int = wordBytes * 8
  def sramAddrWidth: Int = log2Ceil(sramDepth)
  def rfAddrWidth: Int = log2Ceil(rfSliceWords)
  def nCacheSlots: Int = sramDepth / cacheSlotWords
  def cacheSlotWidth: Int = log2Ceil(nCacheSlots)
  def kIndexWidth: Int = log2Ceil(kInL)

  // Types
  def xPos(): UInt = UInt(xPosWidth.W)
  def yPos(): UInt = UInt(yPosWidth.W)
  def ident(): UInt = UInt(identWidth.W)
  def cacheSlot(): UInt = UInt(cacheSlotWidth.W)
  def word(): UInt = UInt(wordWidth.W)
  def memAddr(): UInt = UInt(memAddrWidth.W)
  def elementIndex(): UInt = UInt(elementIndexWidth.W)
  def rfAddr(): UInt = UInt(rfAddrWidth.W)
}

object LamletParams {
  implicit val synchronizerParamsDecoder: Decoder[SynchronizerParams] = deriveDecoder[SynchronizerParams]
  implicit val witemMonitorParamsDecoder: Decoder[WitemMonitorParams] = deriveDecoder[WitemMonitorParams]
  implicit val networkNodeParamsDecoder: Decoder[NetworkNodeParams] = deriveDecoder[NetworkNodeParams]
  implicit val issueUnitParamsDecoder: Decoder[IssueUnitParams] = deriveDecoder[IssueUnitParams]
  implicit val lamletParamsDecoder: Decoder[LamletParams] = deriveDecoder[LamletParams]

  def fromFile(fileName: String): LamletParams = {
    val jsonContent = Source.fromFile(fileName).mkString
    val paramsResult = decode[LamletParams](jsonContent)
    paramsResult match {
      case Right(params) => params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}
