package zamlet.jamlet

import chisel3._
import chisel3.util.log2Ceil
import io.circe._
import io.circe.parser._
import io.circe.generic.semiauto._
import scala.io.Source

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

case class JamletParams(
  // Position widths
  xPosWidth: Int = 8,
  yPosWidth: Int = 8,

  // Word width (shared: SRAM, network, RF)
  wordBytes: Int = 8,

  // SRAM configuration
  sramDepth: Int = 256,      // Number of words in SRAM
  cacheSlotWords: Int = 16,  // Words per cache slot

  // Register file slice
  rfSliceWords: Int = 48,    // Number of words in RF slice

  // Address and index widths
  memAddrWidth: Int = 48,       // Global memory address width
  // Must hold j_in_l * word_bytes * max_lmul
  elementIndexWidth: Int = 22,

  // WitemTable configuration
  witemTableDepth: Int = 16,

  // Instruction identifier
  identWidth: Int = 7,

  // Network configuration
  nAChannels: Int = 1,
  nBChannels: Int = 1,
  networkNodeParams: NetworkNodeParams = NetworkNodeParams()
) {
  // Calculated parameters
  def wordWidth: Int = wordBytes * 8
  def sramAddrWidth: Int = log2Ceil(sramDepth)
  def rfAddrWidth: Int = log2Ceil(rfSliceWords)
  def nCacheSlots: Int = sramDepth / cacheSlotWords
  def cacheSlotWidth: Int = log2Ceil(nCacheSlots)

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

object JamletParams {
  implicit val networkNodeParamsDecoder: Decoder[NetworkNodeParams] = deriveDecoder[NetworkNodeParams]
  implicit val jamletParamsDecoder: Decoder[JamletParams] = deriveDecoder[JamletParams]

  def fromFile(fileName: String): JamletParams = {
    val jsonContent = Source.fromFile(fileName).mkString
    val paramsResult = decode[JamletParams](jsonContent)
    paramsResult match {
      case Right(params) => params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}
