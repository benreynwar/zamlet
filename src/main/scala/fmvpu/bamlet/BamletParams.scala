package fmvpu.bamlet

import chisel3._
import chisel3.util.log2Ceil
import fmvpu.amlet.AmletParams
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import io.circe.generic.semiauto._
import scala.io.Source

case class BamletParams(
  // Number of amlet columns and rows
  nAmletColumns: Int = 2,
  nAmletRows: Int = 1,
  amlet: AmletParams,
  // Instruction memory depth
  instructionMemoryDepth: Int = 64
) {
  // Calculated parameters
  def nAmlets: Int = nAmletColumns * nAmletRows
  
  // Delegate common fields to amlet params
  def aWidth: Int = amlet.aWidth
  def nLoopLevels: Int = amlet.nLoopLevels
}


/** Companion object for BamletParams with factory methods. */
object BamletParams {
  
  // Explicit decoder for BamletParams
  implicit val BamletParamsDecoder: Decoder[BamletParams] = deriveDecoder[BamletParams]

  /** Load Bamlet parameters from a JSON configuration file.
    *
    * @param fileName Path to the JSON configuration file
    * @return BamletParams instance with configuration loaded from file
    * @throws RuntimeException if the file cannot be parsed or contains invalid parameters
    */
  def fromFile(fileName: String): BamletParams = {
    val jsonContent = Source.fromFile(fileName).mkString;
    val paramsResult = decode[BamletParams](jsonContent);
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
