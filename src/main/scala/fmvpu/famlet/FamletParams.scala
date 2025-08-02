package fmvpu.famlet

import chisel3._
import chisel3.util._
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import io.circe.generic.semiauto._
import scala.io.Source

case class FamletParams(
  // Width of the words in the ALU and Network
  width: Int = 32,
  // Width of the words in the ALULite
  aWidth: Int = 16,
  // Number of data registers
  nDRegs: Int = 16,
  nDPhysRegs: Int = 32,
  // Number of address registers
  nARegs: Int = 16,
  nAPhysRegs: Int = 32,
  // Number of global registers (at the bamlet level)
  nGRegs: Int = 16,
  // The number of masking predicates
  // We need at least one of each loop-level and if-statement
  // level.
  nPRegs: Int = 16,

  // Depth of the data memory
  dataMemoryDepth: Int = 64,
  // Maximum number of nested loop levels supported
  nLoopLevels: Int = 4,
  
  // Number of predicate rename tags per predicate register
  nPTags: Int = 4,
  
  // Width for tracking pending reads
  pendingReadsWidth: Int = 8,
  
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
  // Number of write ports for A and D registers  
  // Baked into RTL. Not configurable
  val nAOnlyWritePorts: Int = 1
  val nDOnlyWritePorts: Int = 0
  val nBWritePorts: Int = 4

  // Number of read ports for A and D registers  
  // Baked into RTL. Not configurable
  val nAOnlyReadPorts: Int = 5  
  val nDOnlyReadPorts: Int = 2
  val nBReadPorts: Int = 4
  
  // Calculated parameters
  val aRegWidth = log2Ceil(nARegs)
  val aPhysRegWidth = log2Ceil(nAPhysRegs)
  val dRegWidth = log2Ceil(nDRegs)
  val dPhysRegWidth = log2Ceil(nDPhysRegs)
  val pRegWidth = log2Ceil(nPRegs)
  // B-register width: max(A-reg, D-reg) width + 1 bit for A/D selection
  val bRegWidth = scala.math.max(aRegWidth, dRegWidth) + 1
  val bPhysRegWidth = scala.math.max(aPhysRegWidth, dPhysRegWidth) + 1
  val gRegWidth = log2Ceil(nGRegs)
  // C-register width: max(A-reg, D-reg, P-reg, G-reg) width + 2 bit for A/D/P/G selection
  val cRegWidth = scala.math.max(scala.math.max(scala.math.max(aRegWidth, dRegWidth), gRegWidth), pRegWidth) + 2
  val cPhysRegWidth = scala.math.max(scala.math.max(scala.math.max(aPhysRegWidth, dPhysRegWidth), gRegWidth), pRegWidth) + 2

  val addrWidth = log2Ceil(dataMemoryDepth)

  val nAWritePorts = nAOnlyWritePorts + nBWritePorts
  val nDWritePorts = nDOnlyWritePorts + nBWritePorts

  // Types
  def dReg(): UInt = UInt(dRegWidth.W)
  def aReg(): UInt = UInt(aRegWidth.W)
  def bReg(): UInt = UInt(bRegWidth.W)
  def pReg(): UInt = UInt(pRegWidth.W)
  def pTagWidth: Int = log2Ceil(nPTags)

  def aPhysReg(): UInt = UInt(aPhysRegWidth.W)
  def dPhysReg(): UInt = UInt(dPhysRegWidth.W)
  def bPhysReg(): UInt = UInt(bPhysRegWidth.W)

  def dWord(): UInt = UInt(width.W)
  def aWord(): UInt = UInt(aWidth.W)
  def bWord(): UInt = UInt(width.W)
}

class DSource(params: FamletParams) extends Bundle {
  val value = params.dWord()
  val resolved = Bool()
  val addr = params.dPhysReg()
  
  def getData: UInt = value
  def update(writes: ResultBus): DSource = {
    val result = Wire(new DSource(params))
    
    // Start with original values
    result.value := value
    result.resolved := resolved
    result.addr := addr

    // Check each write port for a match
    for (j <- 0 until writes.bWrites.length) {
      val writeAddr = writes.bWrites(j).bits.address
      val isDRegWrite = writeAddr(params.bPhysRegWidth-1)  // Upper bit = 1 for D-registers
      val regIndex = writeAddr(params.dPhysRegWidth-1, 0)  // Lower bits = register index
      
      when (!resolved && writes.bWrites(j).valid && 
            isDRegWrite &&  // Upper bit = 1 (D-register)
            addr === regIndex  // Lower bits match our D-register index  
            ) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.bWrites(j).bits.value
      }
    }
    
    result
  }
}

class ASource(params: FamletParams) extends Bundle {
  val value = params.aWord()
  val resolved = Bool()
  val addr = params.aPhysReg()
  
  def getData: UInt = value
  def update(writes: ResultBus): ASource = {
    val result = Wire(new ASource(params))
    
    // Start with original values
    result.value := value
    result.resolved := resolved
    result.addr := addr

    // Check A-only write ports
    for (j <- 0 until writes.aWrites.length) {
      when (!resolved && writes.aWrites(j).valid && 
            addr === writes.aWrites(j).bits.address) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.aWrites(j).bits.value
      }
    }
    
    // Check B write ports for A-registers (upper bit = 0)
    for (j <- 0 until writes.bWrites.length) {
      val writeAddr = writes.bWrites(j).bits.address
      val isARegWrite = !writeAddr(params.bPhysRegWidth-1)  // Upper bit = 0 for A-registers
      val regIndex = writeAddr(params.aPhysRegWidth-1, 0)  // Lower bits = register index
      
      when (!resolved && writes.bWrites(j).valid && 
            isARegWrite &&  // Upper bit = 0 (A-register)
            addr === regIndex  // Lower bits match our A-register index
            ) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.bWrites(j).bits.value
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

class BSource(params: FamletParams) extends Bundle {
  val value = params.bWord()
  val resolved = Bool()
  val addr = params.bPhysReg()
  
  def getData: UInt = value
  def update(writes: ResultBus): BSource = {
    val result = Wire(new BSource(params))
    
    // Start with original values
    result.value := value
    result.resolved := resolved
    result.addr := addr

    // Check each write port for a match
    for (j <- 0 until writes.bWrites.length) {
      when (!resolved && writes.bWrites(j).valid && 
            addr === writes.bWrites(j).bits.address) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writes.bWrites(j).bits.value
      }
    }
    
    result
  }
}


class PTaggedReg(params: FamletParams) extends Bundle {
  val addr = params.pReg()
  val tag = UInt(params.pTagWidth.W)
}

class PTaggedSource(params: FamletParams) extends Bundle {
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

class WriteAResult(params: FamletParams) extends Bundle {
  val value = UInt(params.width.W)
  val address = params.aPhysReg()
  val force = Bool() // from command packet, bypasses writeIdent system
  val predicate = Bool()
}

class WriteResult(params: FamletParams) extends Bundle {
  val value = UInt(params.width.W)
  val address = params.bPhysReg()
  val force = Bool() // from command packet, bypasses writeIdent system
  val predicate = Bool()
}

class BWriteEvent(params: FamletParams) extends Bundle {
  val address = params.bPhysReg()
  val force = Bool() // from command packet, bypasses writeIdent system
}

class PredicateResult(params: FamletParams) extends Bundle {
  val value = Bool()
  val address = new PTaggedReg(params) 
}

class NoticeBus(params: FamletParams) extends Bundle {
  // Writes for ALU, ALULite, Load & ReceivePacket
  val dReads = Vec(params.nDOnlyReadPorts, Valid(params.dPhysReg()))
  val aReads = Vec(params.nAOnlyReadPorts, Valid(params.aPhysReg()))
  val bReads = Vec(params.nBReadPorts, Valid(params.bPhysReg()))
}

class ResultBus(params: FamletParams) extends Bundle {
  val aWrites = Vec(params.nAOnlyWritePorts, Valid(new WriteAResult(params)))
  val bWrites = Vec(params.nBWritePorts, Valid(new WriteResult(params)))
  val predicate = Vec(2, Valid(new PredicateResult(params)))
}


/** Companion object for FamletParams with factory methods. */
object FamletParams {
  
  // Explicit decoder for FamletParams
  implicit val famletParamsDecoder: Decoder[FamletParams] = deriveDecoder[FamletParams]

  /** Load Famlet parameters from a JSON configuration file.
    *
    * @param fileName Path to the JSON configuration file
    * @return FamletParams instance with configuration loaded from file
    * @throws RuntimeException if the file cannot be parsed or contains invalid parameters
    */
  def fromFile(fileName: String): FamletParams = {
    val jsonContent = Source.fromFile(fileName).mkString;
    val paramsResult = decode[FamletParams](jsonContent);
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
