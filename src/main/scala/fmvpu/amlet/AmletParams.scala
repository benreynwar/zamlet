package fmvpu.amlet

import chisel3._
import chisel3.util.log2Ceil
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import io.circe.generic.semiauto._
import scala.io.Source

case class AmletParams(
  // Width of the words in the ALU and Network
  width: Int = 32,
  // The width of the identifier for renaming uses of a given register.
  wIdentWidth: Int = 2,
  // Similar but for masks
  mIdentWidth: Int = 3,
  // Width of the words in the ALULite
  aWidth: Int = 16,
  // Number of data registers
  nDRegs: Int = 16,
  // Number of address registers
  nARegs: Int = 16,
  // Depth of the data memory
  dataMemoryDepth: Int = 64,
  // Number of write back ports
  nWriteBacks: Int = 4,
  
  // Width of a coordinates
  xPosWidth: Int = 8,
  yPosWidth: Int = 8,
  // Width to describe length of a packet.
  packetLengthWidth: Int = 8,

  // ALU configuration
  aluLatency: Int = 1,
  nAluRSSlots: Int = 4,

  // Load Store configuration
  nLoadStoreRSSlots: Int = 4,

  // Packet configuration
  nPacketNSSlots: Int = 2,
  nPacketOutIdents: Int = 4,
  
  // Network configuration
  nChannels: Int = 2
) {
  // Calculated parameters
  val nWriteIdents = 1 << wIdentWidth
  val aRegWidth = log2Ceil(nARegs)
  val dRegWidth = log2Ceil(nDRegs)
  val bRegWidth = scala.math.max(aRegWidth, dRegWidth) + 1

  val addrWidth = log2Ceil(dataMemoryDepth)

  // Types
  def dReg(): UInt = UInt(dRegWidth.W)
  def aReg(): UInt = UInt(aRegWidth.W)
  def bReg(): UInt = UInt(bRegWidth.W)

  def dWord(): UInt = UInt(width.W)
  def aWord(): UInt = UInt(aWidth.W)
  def bWord(): UInt = UInt(width.W)

  def wIdent(): UInt = UInt(wIdentWidth.W)
}

class DRegWithIdent(params: AmletParams) extends Bundle {
  val addr = params.dReg()
  val ident = UInt(params.wIdentWidth.W)
}

class DRegReadInfo(params: AmletParams) extends Bundle {
  val value = params.dWord()
  val resolved = Bool()
  val addr = params.dReg()
  val ident = UInt(params.wIdentWidth.W)
  
  def getData: UInt = value
  def update(writes: WriteBacks): DRegReadInfo = {
    val result = Wire(new DRegReadInfo(params))
    
    // Start with original values
    result.value := value
    result.resolved := resolved
    result.addr := addr
    result.ident := ident

    // Check each write port for a match
    for (j <- 0 until params.nWriteBacks) {
      when (!resolved && writes.writes(j).valid && 
            addr === writes.writes(j).address.addr &&
            ident === writes.writes(j).address.ident) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.writes(j).value
      }
    }
    
    result
  }
}

class ARegWithIdent(params: AmletParams) extends Bundle {
  val addr = params.aReg()
  val ident = UInt(params.wIdentWidth.W)
}

class ARegReadInfo(params: AmletParams) extends Bundle {
  val value = params.aWord()
  val resolved = Bool()
  val addr = params.aReg()
  val ident = UInt(params.wIdentWidth.W)
}

class BRegWithIdent(params: AmletParams) extends Bundle {
  val addr = params.bReg()
  val ident = UInt(params.wIdentWidth.W)
}

class WriteResult(params: AmletParams) extends Bundle {
  val valid = Bool()
  val value = UInt(params.width.W)
  val address = new BRegWithIdent(params)
  val force = Bool() // from command packet, bypasses writeIdent system
}

class MaskResult(params: AmletParams) extends Bundle {
  val valid = Bool()
  val value = Bool()
  val ident = UInt(params.mIdentWidth.W)
}

class MaskInfo(params: AmletParams) extends Bundle {
  val value = Bool()
  val resolved = Bool()
  val ident = UInt(params.mIdentWidth.W)

  def getData: Bool = value
  def update(writes: WriteBacks): MaskInfo = {
    val result = Wire(new MaskInfo(params))
    result.value := value
    result.resolved := resolved
    result.ident := ident
    
    // Check each mask write port for a match
    for (j <- 0 until params.nWriteBacks) {
      when (!resolved && writes.masks(j).valid && 
            ident === writes.masks(j).ident) {
        result.resolved := true.B
        result.value := writes.masks(j).value
      }
    }
    
    result
  }
}

class WriteBacks(params: AmletParams) extends Bundle {
  val writes = Vec(params.nWriteBacks, new WriteResult(params))
  val masks = Vec(params.nWriteBacks, new MaskResult(params))
}


/** Companion object for AmletParams with factory methods. */
object AmletParams {
  
  // Explicit decoder for AmletParams
  implicit val amletParamsDecoder: Decoder[AmletParams] = deriveDecoder[AmletParams]

  /** Load Amlet parameters from a JSON configuration file.
    *
    * @param fileName Path to the JSON configuration file
    * @return AmletParams instance with configuration loaded from file
    * @throws RuntimeException if the file cannot be parsed or contains invalid parameters
    */
  def fromFile(fileName: String): AmletParams = {
    val jsonContent = Source.fromFile(fileName).mkString;
    val paramsResult = decode[AmletParams](jsonContent);
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
