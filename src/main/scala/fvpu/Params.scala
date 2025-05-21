package fvpu

// Import circe libraries for JSON parsing
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import scala.io.Source

case class FVPUParams(
  nBuses: Int,
  width: Int,
  // Max depth of the output buffers in the network node.
  maxNetworkOutputDelay: Int
)

object FVPUParams {

  def fromFile(fileName: String): FVPUParams = {
    val jsonContent = Source.fromFile(fileName).mkString;
    val paramsResult = decode[FVPUParams](jsonContent);
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
