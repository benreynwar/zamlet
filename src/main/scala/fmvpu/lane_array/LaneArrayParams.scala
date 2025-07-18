package fmvpu.lane_array

import fmvpu.lane.LaneParams
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import io.circe.generic.semiauto._
import scala.io.Source

/**
 * Configuration parameters for LaneArray implementation
 */
case class LaneArrayParams(
  nColumns: Int = 4,
  nRows: Int = 4,
  lane: LaneParams = LaneParams()
) {
  val nLanes = nColumns * nRows
}

/** Companion object for LaneArrayParams with factory methods. */
object LaneArrayParams {
  
  // Explicit decoder for LaneArrayParams
  implicit val laneArrayParamsDecoder: Decoder[LaneArrayParams] = deriveDecoder[LaneArrayParams]

  /** Load LaneArray parameters from a JSON configuration file.
    *
    * @param fileName Path to the JSON configuration file
    * @return LaneArrayParams instance with configuration loaded from file
    * @throws RuntimeException if the file cannot be parsed or contains invalid parameters
    */
  def fromFile(fileName: String): LaneArrayParams = {
    val jsonContent = Source.fromFile(fileName).mkString;
    val paramsResult = decode[LaneArrayParams](jsonContent);
    paramsResult match {
      case Right(params) =>
        params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}
