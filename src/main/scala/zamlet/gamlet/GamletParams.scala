package zamlet.gamlet

import chisel3._
import chisel3.util.log2Ceil
import zamlet.famlet.FamletParams
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import io.circe.generic.semiauto._
import scala.io.Source

case class GamletParams(
  // Number of famlet columns and rows
  nFamletColumns: Int = 2,
  nFamletRows: Int = 1,
  famlet: FamletParams,
  // Instruction memory depth
  instructionMemoryDepth: Int = 64,
  // Rename module parameters
  rename: RenameParams = RenameParams()
) {
  // Calculated parameters
  def nFamlets: Int = nFamletColumns * nFamletRows
  
  // Delegate common fields to famlet params
  def aWidth: Int = famlet.aWidth
  def nLoopLevels: Int = famlet.nLoopLevels
}


/** Companion object for GamletParams with factory methods. */
object GamletParams {
  
  // Explicit decoder for GamletParams
  implicit val GamletParamsDecoder: Decoder[GamletParams] = deriveDecoder[GamletParams]

  /** Load Gamlet parameters from a JSON configuration file.
    *
    * @param fileName Path to the JSON configuration file
    * @return GamletParams instance with configuration loaded from file
    * @throws RuntimeException if the file cannot be parsed or contains invalid parameters
    */
  def fromFile(fileName: String): GamletParams = {
    val jsonContent = Source.fromFile(fileName).mkString;
    val paramsResult = decode[GamletParams](jsonContent);
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