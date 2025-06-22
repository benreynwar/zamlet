package fmvpu.core

// Import circe libraries for JSON parsing
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import scala.io.Source

/** Configuration parameters for the FMVPU system.
  *
  * This case class contains all the parameters needed to configure an FMVPU instance,
  * including grid dimensions, memory sizes, and network configuration. Parameters are
  * typically loaded from JSON configuration files.
  *
  * @param nChannels Number of parallel network channels between lanes
  * @param width Data width in bits for all data paths
  * @param networkMemoryDepth Maximum depth of output buffers in network nodes
  * @param nDRF Number of registers in the distributed register file per lane
  * @param ddmBankDepth Number of entries per bank in the distributed data memory
  * @param ddmNBanks Number of banks in the distributed data memory
  * @param ddmAddrWidth Address width in bits for distributed data memory
  * @param depthNetworkConfig Number of entries in the network configuration table
  * @param nColumns Number of columns in the LaneGrid
  * @param nRows Number of rows in the LaneGrid
  * @param maxPacketLength Maximum packet length for network switching
  */
case class FMVPUParams(
  nChannels: Int,
  width: Int,
  networkMemoryDepth: Int,
  nDRF: Int,
  ddmBankDepth: Int,
  ddmNBanks: Int,
  ddmAddrWidth: Int,
  depthNetworkConfig: Int,
  nColumns: Int,
  nRows: Int,
  maxPacketLength: Int,
  maxNetworkControlDelay: Int,
  nSlowNetworkControlSlots: Int,
  nFastNetworkControlSlots: Int,
  networkIdentWidth: Int,
) {
  // Calculated parameters based on actual control structure sizes
  import chisel3.util.log2Ceil
  
  // Calculate bit widths for control structures
  private def bitsForChannelSlowControl: Int = {
    1 + // IsPacketMode
    4 * log2Ceil(networkMemoryDepth + 1) + // delays
    1 + // isOutputDelay  
    4 * nChannels + // drive enables
    2 * log2Ceil(maxNetworkControlDelay + 1) + // input sel delays
    2 * log2Ceil(maxNetworkControlDelay + 1) // crossbar sel delays
  }
  
  private def bitsForGeneralSlowControl: Int = {
    2 * log2Ceil(maxNetworkControlDelay + 1) // drf and ddm sel delays
  }
  
  private def bitsForChannelFastControl: Int = {
    2 + // nsInputSel + weInputSel
    2 * log2Ceil(nChannels + 2) // crossbar selections
  }
  
  private def bitsForGeneralFastControl: Int = {
    2 * log2Ceil(nChannels * 2) // drf and ddm selections
  }
  
  val wordsPerChannelSlowNetworkControl = (bitsForChannelSlowControl + width - 1) / width
  val wordsPerGeneralSlowNetworkControl = (bitsForGeneralSlowControl + width - 1) / width  
  val wordsPerChannelFastNetworkControl = (bitsForChannelFastControl + width - 1) / width
  val wordsPerGeneralFastNetworkControl = (bitsForGeneralFastControl + width - 1) / width
  
  // Round slot sizes up to powers of 2 for cleaner addressing
  private val rawWordsPerSlowSlot = wordsPerGeneralSlowNetworkControl + nChannels * wordsPerChannelSlowNetworkControl
  val wordsPerSlowNetworkControlSlot = 1 << scala.math.ceil(scala.math.log(rawWordsPerSlowSlot) / scala.math.log(2)).toInt
  
  private val rawWordsPerFastSlot = wordsPerGeneralFastNetworkControl + nChannels * wordsPerChannelFastNetworkControl  
  val wordsPerFastNetworkControlSlot = 1 << scala.math.ceil(scala.math.log(rawWordsPerFastSlot) / scala.math.log(2)).toInt
  
  // Calculate fastNetworkControlOffset as total slow control space
  val fastNetworkControlOffset = nSlowNetworkControlSlots * wordsPerSlowNetworkControlSlot
  
  val networkControlAddrWidth = scala.math.max(1, 
    32 - Integer.numberOfLeadingZeros(fastNetworkControlOffset + nFastNetworkControlSlots * wordsPerFastNetworkControlSlot - 1)
  )
}

/** Companion object for FMVPUParams with factory methods. */
object FMVPUParams {

  /** Load FMVPU parameters from a JSON configuration file.
    *
    * @param fileName Path to the JSON configuration file
    * @return FMVPUParams instance with configuration loaded from file
    * @throws RuntimeException if the file cannot be parsed or contains invalid parameters
    *
    * @example
    * {{{
    * val params = FMVPUParams.fromFile("config/default.json")
    * val grid = Module(new LaneGrid(params))
    * }}}
    */
  def fromFile(fileName: String): FMVPUParams = {
    val jsonContent = Source.fromFile(fileName).mkString;
    val paramsResult = decode[FMVPUParams](jsonContent);
    paramsResult match {
      case Right(params) =>
        return params;
      case Left(error) =>
        println(s"Failed to parse JSON: ${error.getMessage}")
        System.exit(1)
        null
    }
  }

}
