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
case class FMPVUParams(
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
)

/** Companion object for FMPVUParams with factory methods. */
object FMPVUParams {

  /** Load FMVPU parameters from a JSON configuration file.
    *
    * @param fileName Path to the JSON configuration file
    * @return FMPVUParams instance with configuration loaded from file
    * @throws RuntimeException if the file cannot be parsed or contains invalid parameters
    *
    * @example
    * {{{
    * val params = FMPVUParams.fromFile("config/default.json")
    * val grid = Module(new LaneGrid(params))
    * }}}
    */
  def fromFile(fileName: String): FMPVUParams = {
    val jsonContent = Source.fromFile(fileName).mkString;
    val paramsResult = decode[FMPVUParams](jsonContent);
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
