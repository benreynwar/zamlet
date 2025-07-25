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
  // The width of the register rename tag identifier.
  regTagWidth: Int = 2,
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
  // Number of result bus ports for completion events
  nResultPorts: Int = 4,
  // Maximum number of nested loop levels supported
  nLoopLevels: Int = 4,
  
  // Width of a coordinates
  xPosWidth: Int = 8,
  yPosWidth: Int = 8,
  // Width to describe length of a packet.
  packetLengthWidth: Int = 8,

  // ALU configuration
  aluLatency: Int = 1,
  nAluRSSlots: Int = 4,
  
  // ALULite configuration
  nAluLiteRSSlots: Int = 4,

  // Load Store configuration
  nLoadStoreRSSlots: Int = 4,

  // Packet configuration
  nSendPacketRSSlots: Int = 2,
  nReceivePacketRSSlots: Int = 2,
  nPacketOutIdents: Int = 4,
  
  // Network configuration
  nChannels: Int = 2,

  instrAddrWidth: Int = 8
) {
  // Calculated parameters
  val nWriteIdents = 1 << regTagWidth
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

  def wIdent(): UInt = UInt(regTagWidth.W)
}

class DTaggedReg(params: AmletParams) extends Bundle {
  val addr = params.dReg()
  val tag = UInt(params.regTagWidth.W)
}

class DTaggedSource(params: AmletParams) extends Bundle {
  val value = params.dWord()
  val resolved = Bool()
  val addr = params.dReg()
  val tag = UInt(params.regTagWidth.W)
  
  def getData: UInt = value
  def update(writes: ResultBus): DTaggedSource = {
    val result = Wire(new DTaggedSource(params))
    
    // Start with original values
    result.value := value
    result.resolved := resolved
    result.addr := addr
    result.tag := tag

    // Check each write port for a match
    for (j <- 0 until params.nResultPorts) {
      val writeAddr = writes.writes(j).address.addr
      val isDRegWrite = writeAddr(params.bRegWidth-1)  // Upper bit = 1 for D-registers
      val regIndex = writeAddr(params.dRegWidth-1, 0)  // Lower bits = register index
      
      when (!resolved && writes.writes(j).valid && 
            isDRegWrite &&  // Upper bit = 1 (D-register)
            addr === regIndex &&  // Lower bits match our D-register index  
            tag === writes.writes(j).address.tag) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.writes(j).value
      }
    }
    
    result
  }
}

class ATaggedReg(params: AmletParams) extends Bundle {
  val addr = params.aReg()
  val tag = UInt(params.regTagWidth.W)
}

class ATaggedSource(params: AmletParams) extends Bundle {
  val value = params.aWord()
  val resolved = Bool()
  val addr = params.aReg()
  val tag = UInt(params.regTagWidth.W)
  
  def getData: UInt = value
  def update(writes: ResultBus): ATaggedSource = {
    val result = Wire(new ATaggedSource(params))
    
    // Start with original values
    result.value := value
    result.resolved := resolved
    result.addr := addr
    result.tag := tag

    // Check each write port for a match
    for (j <- 0 until params.nResultPorts) {
      val writeAddr = writes.writes(j).address.addr
      val isARegWrite = !writeAddr(params.bRegWidth-1)  // Upper bit = 0 for A-registers
      val regIndex = writeAddr(params.aRegWidth-1, 0)  // Lower bits = register index
      
      when (!resolved && writes.writes(j).valid && 
            isARegWrite &&  // Upper bit = 0 (A-register)
            addr === regIndex &&  // Lower bits match our A-register index
            tag === writes.writes(j).address.tag) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.writes(j).value
      }
    }
    
    result
  }
}

class BTaggedReg(params: AmletParams) extends Bundle {
  val addr = params.bReg()
  val tag = UInt(params.regTagWidth.W)
}

class BTaggedSource(params: AmletParams) extends Bundle {
  val value = params.bWord()
  val resolved = Bool()
  val addr = params.bReg()
  val tag = UInt(params.regTagWidth.W)
  
  def getData: UInt = value
  def update(writes: ResultBus): BTaggedSource = {
    val result = Wire(new BTaggedSource(params))
    
    // Start with original values
    result.value := value
    result.resolved := resolved
    result.addr := addr
    result.tag := tag

    // Check each write port for a match
    for (j <- 0 until params.nResultPorts) {
      when (!resolved && writes.writes(j).valid && 
            addr === writes.writes(j).address.addr &&
            tag === writes.writes(j).address.tag) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.writes(j).value
      }
    }
    
    result
  }
}

class WriteResult(params: AmletParams) extends Bundle {
  val valid = Bool()
  val value = UInt(params.width.W)
  val address = new BTaggedReg(params)
  val force = Bool() // from command packet, bypasses writeIdent system
}

class WriteEvent(params: AmletParams) extends Bundle {
  val address = new BTaggedReg(params)
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
  def update(writes: ResultBus): MaskInfo = {
    val result = Wire(new MaskInfo(params))
    result.value := value
    result.resolved := resolved
    result.ident := ident
    
    // Check each mask write port for a match
    for (j <- 0 until params.nResultPorts) {
      when (!resolved && writes.masks(j).valid && 
            ident === writes.masks(j).ident) {
        result.resolved := true.B
        result.value := writes.masks(j).value
      }
    }
    
    result
  }
}

class ResultBus(params: AmletParams) extends Bundle {
  val writes = Vec(params.nResultPorts, new WriteResult(params))
  val masks = Vec(params.nResultPorts, new MaskResult(params))
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
