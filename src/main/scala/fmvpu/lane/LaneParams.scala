package fmvpu.lane

import chisel3._
import chisel3.util.log2Ceil
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import io.circe.generic.semiauto._
import scala.io.Source

/**
 * ALU operation modes
 */
object ALUModes extends ChiselEnum {
  val Add = Value(0.U)
  val Addi = Value(1.U)
  val Sub = Value(2.U)
  val Subi = Value(3.U)
  val Mult = Value(4.U)
  val MultAcc = Value(5.U)
  val Reserved6 = Value(6.U)
  val Reserved7 = Value(7.U)
  val Reserved8 = Value(8.U)
  val Reserved9 = Value(9.U)
  val Reserved10 = Value(10.U)
  val Reserved11 = Value(11.U)
  val Reserved12 = Value(12.U)
  val Reserved13 = Value(13.U)
  val Reserved14 = Value(14.U)
  val Reserved15 = Value(15.U)
}

/**
 * Load/Store operation modes
 */
object LdStModes extends ChiselEnum {
  val Load = Value(0.U)
  val Store = Value(1.U)
  val Reserved2 = Value(2.U)
  val Reserved3 = Value(3.U)
}

/**
 * Packet header modes
 */
object PacketHeaderModes extends ChiselEnum {
  val Normal = Value(0.U)
  val Command = Value(1.U)
}

/**
 * Broadcast directions
 */
object BroadcastDirections extends ChiselEnum {
  val NE = Value(0.U)
  val SE = Value(1.U)
  val SW = Value(2.U)
  val NW = Value(3.U)
}

/**
 * Network directions for forwarding
 */
object NetworkDirections extends ChiselEnum {
  val North = Value(0.U)
  val East = Value(1.U)
  val South = Value(2.U)
  val West = Value(3.U)
  val Here = Value(4.U)
}


/**
 * Packet operation modes
 */
object PacketModes extends ChiselEnum {
  val Receive = Value(0.U)
  val ReceiveAndForward = Value(1.U)
  val ReceiveForwardAndAppend = Value(2.U)
  val ForwardAndAppend = Value(3.U)
  val Send = Value(4.U)
  val GetWord = Value(5.U)
  val Unused6 = Value(6.U)
  val Unused7 = Value(7.U)
}

/**
 * Configuration parameters for Lane implementation
 */
case class LaneParams(
  width: Int = 32,
  writeIdentWidth: Int = 2,
  nRegs: Int = 8,
  instructionMemoryDepth: Int = 64,
  dataMemoryDepth: Int = 64,
  nWritePorts: Int = 3,
  
  // Instruction field widths
  aluModeWidth: Int = 4,
  ldstModeWidth: Int = 2,
  packetModeWidth: Int = 3,
  xPosWidth: Int = 5,
  yPosWidth: Int = 5,
  packetLengthWidth: Int = 8,
  addressWidth: Int = 8,
  instrAddrWidth: Int = 10,
  
  // Special register assignments
  packetWordOutRegAddr: Int = 0,
  accumRegAddr: Int = 1,
  maskRegAddr: Int = 2,
  baseAddrRegAddr: Int = 3,
  channelRegAddr: Int = 4,
  
  // ALU configuration
  aluLatency: Int = 1,
  nAluRSSlots: Int = 4,
  
  // Load/Store configuration
  nLdStRSSlots: Int = 4,
  
  // Packet configuration
  nPacketRSSlots: Int = 2,
  nPacketOutIdents: Int = 4,
  
  // Network configuration
  nChannels: Int = 2
) {
  // Calculated parameters
  val nWriteIdents = 1 << writeIdentWidth
  val regAddrWidth = log2Ceil(nRegs)
  val regWithIdentWidth = regAddrWidth + writeIdentWidth
  val targetWidth = xPosWidth + yPosWidth
  
  // Constants
  val instructionWidth = 16
}

/** Companion object for LaneParams with factory methods. */
object LaneParams {
  
  // Explicit decoder for LaneParams
  implicit val laneParamsDecoder: Decoder[LaneParams] = deriveDecoder[LaneParams]

  /** Load Lane parameters from a JSON configuration file.
    *
    * @param fileName Path to the JSON configuration file
    * @return LaneParams instance with configuration loaded from file
    * @throws RuntimeException if the file cannot be parsed or contains invalid parameters
    */
  def fromFile(fileName: String): LaneParams = {
    val jsonContent = Source.fromFile(fileName).mkString;
    val paramsResult = decode[LaneParams](jsonContent);
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
