package fmvpu.amlet

import chisel3._
import chisel3.util._
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
  // Width of the words in the ALULite
  aWidth: Int = 16,
  // Number of data registers
  nDRegs: Int = 16,
  // Number of address registers
  nARegs: Int = 16,
  // Number of global registers (at the bamlet level)
  nGRegs: Int = 16,
  // Depth of the data memory
  dataMemoryDepth: Int = 64,
  // Number of result bus ports for completion events
  nResultPorts: Int = 4,
  // Maximum number of nested loop levels supported
  nLoopLevels: Int = 4,

  // The number of masking predicates
  // We need at least one of each loop-level and if-statement
  // level.
  nPRegs: Int = 16,
  
  // Number of predicate rename tags per predicate register
  nPTags: Int = 4,
  
  // Width of a coordinates
  xPosWidth: Int = 8,
  yPosWidth: Int = 8,
  // Width to describe length of a packet.
  packetLengthWidth: Int = 8,

  // ALU configuration
  aluLatency: Int = 1,
  nAluRSSlots: Int = 4,
  
  // ALULite configuration
  aluLiteLatency: Int = 1,
  nAluLiteRSSlots: Int = 4,

  // ALU Predicate configuration
  aluPredicateLatency: Int = 1,
  nAluPredicateRSSlots: Int = 4,

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
  val pRegWidth = log2Ceil(nPRegs)
  // B-register width: max(A-reg, D-reg) width + 1 bit for A/D selection
  val bRegWidth = scala.math.max(aRegWidth, dRegWidth) + 1
  val gRegWidth = log2Ceil(nGRegs)
  val regWidth = scala.math.max(scala.math.max(scala.math.max(aRegWidth, dRegWidth), gRegWidth), pRegWidth) + 2

  val addrWidth = log2Ceil(dataMemoryDepth)

  // Types
  def dReg(): UInt = UInt(dRegWidth.W)
  def aReg(): UInt = UInt(aRegWidth.W)
  def bReg(): UInt = UInt(bRegWidth.W)

  def pReg(): UInt = UInt(pRegWidth.W)
  def pTagWidth: Int = log2Ceil(nPTags)

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
      val writeAddr = writes.writes(j).bits.address.addr
      val isDRegWrite = writeAddr(params.bRegWidth-1)  // Upper bit = 1 for D-registers
      val regIndex = writeAddr(params.dRegWidth-1, 0)  // Lower bits = register index
      
      when (!resolved && writes.writes(j).valid && 
            isDRegWrite &&  // Upper bit = 1 (D-register)
            addr === regIndex &&  // Lower bits match our D-register index  
            tag === writes.writes(j).bits.address.tag) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.writes(j).bits.value
      }
    }
    
    result
  }
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
      val writeAddr = writes.writes(j).bits.address.addr
      val isARegWrite = !writeAddr(params.bRegWidth-1)  // Upper bit = 0 for A-registers
      val regIndex = writeAddr(params.aRegWidth-1, 0)  // Lower bits = register index
      
      when (!resolved && writes.writes(j).valid && 
            isARegWrite &&  // Upper bit = 0 (A-register)
            addr === regIndex &&  // Lower bits match our A-register index
            tag === writes.writes(j).bits.address.tag) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.writes(j).bits.value
      }
    }
    
    result
  }
}

/**
 * B-register addressing system unifies A-registers and D-registers
 * 
 * The B-register address space uses an encoding where:
 * - Upper bit = 0: References an A-register (address registers, aWidth bits)
 * - Upper bit = 1: References a D-register (data registers, width bits)
 * - Lower bits: Index within the A-register or D-register file
 * 
 * This allows instructions to reference either address or data registers
 * using a single address field, simplifying instruction encoding.
 * 
 * See readBReg() and assignWrite() for implementation details.
 */
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
            addr === writes.writes(j).bits.address.addr &&
            tag === writes.writes(j).bits.address.tag) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.writes(j).bits.value
      }
    }
    
    result
  }
}


class PTaggedReg(params: AmletParams) extends Bundle {
  val addr = params.pReg()
  val tag = UInt(params.pTagWidth.W)
}

class PTaggedSource(params: AmletParams) extends Bundle {
  val value = Bool()
  val resolved = Bool()
  val addr = params.pReg()
  val tag = UInt(params.pTagWidth.W)
  
  def getData: Bool = value
  def update(writes: ResultBus): PTaggedSource = {
    val result = Wire(new PTaggedSource(params))
    
    // Start with original values
    result.value := value
    result.resolved := resolved
    result.addr := addr
    result.tag := tag

    // Check each predicate write port for a match
    for (i <- 0 until 2) {
      when (!resolved && writes.predicate(i).valid && 
            addr === writes.predicate(i).bits.address.addr &&
            tag === writes.predicate(i).bits.address.tag) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.predicate(i).bits.value
      }
    }
    result
  }
}

class WriteResult(params: AmletParams) extends Bundle {
  val value = UInt(params.width.W)
  val address = new BTaggedReg(params)
  val force = Bool() // from command packet, bypasses writeIdent system
}

class WriteEvent(params: AmletParams) extends Bundle {
  val address = new BTaggedReg(params)
  val force = Bool() // from command packet, bypasses writeIdent system
}

class PredicateResult(params: AmletParams) extends Bundle {
  val value = Bool()
  val address = new PTaggedReg(params) 
}


class ResultBus(params: AmletParams) extends Bundle {
  val writes = Vec(params.nResultPorts, Valid(new WriteResult(params)))
  val predicate = Vec(2, Valid(new PredicateResult(params)))
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
