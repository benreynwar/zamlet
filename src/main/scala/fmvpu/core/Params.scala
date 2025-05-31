package fmvpu.core

// Import circe libraries for JSON parsing
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import scala.io.Source

case class FMPVUParams(
  nChannels: Int,
  width: Int,
  // Max depth of the output buffers in the network node.
  networkMemoryDepth: Int,
  // Number of regisers in the distributed register file.
  nDRF: Int,
  // Number of vectors stored in the distributed data memory.
  ddmBankDepth: Int,
  ddmNBanks: Int,
  ddmAddrWidth: Int,
  // Number of entries in the network configuration.
  depthNetworkConfig: Int,
  // Number of rows and columns in a LaneGrid
  nColumns: Int,
  nRows: Int,
  // Maximum packet length for network switching
  maxPacketLength: Int,
)

object FMPVUParams {

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
