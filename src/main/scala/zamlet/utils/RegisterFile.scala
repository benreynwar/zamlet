package zamlet.utils

import chisel3._
import chisel3.util._
import scala.math.max
import io.circe.generic.semiauto._
import io.circe._
import io.circe.parser._
import scala.io.Source


case class RFParams(
  width: Int = 32,
  nRegs: Int = 16,
  nTags: Int = 8,
  nReads: Int = 2,
  nWrites: Int = 2,
  iaForwardBuffer: Boolean = true,
  iaBackwardBuffer: Boolean = true,
  iaResultsBuffer: Boolean = true,
  aoBuffer: Boolean = true
) {
  // Calculated parameters
  val tagWidth = log2Ceil(nTags)
  val addrWidth = log2Ceil(nRegs)
  
  // Create RFBuilderParams from RFParams (excludes port count info)
  def toBuilderParams(): RFBuilderParams = {
    RFBuilderParams(
      width = width,
      nRegs = nRegs,
      nTags = nTags,
      iaForwardBuffer = iaForwardBuffer,
      iaBackwardBuffer = iaBackwardBuffer,
      iaResultsBuffer = iaResultsBuffer,
      aoBuffer = aoBuffer
    )
  }
}

case class RFBuilderParams(
  width: Int = 32,
  nRegs: Int = 16,
  nTags: Int = 8,
  iaForwardBuffer: Boolean = true,
  iaBackwardBuffer: Boolean = true,
  iaResultsBuffer: Boolean = true,
  aoBuffer: Boolean = true
) {
  // Calculated parameters
  val tagWidth = log2Ceil(nTags)
  val addrWidth = log2Ceil(nRegs)
  
  // Convert to RFParams with specified port counts
  def toRFParams(nReads: Int, nWrites: Int): RFParams = {
    RFParams(
      width = width,
      nRegs = nRegs,
      nTags = nTags,
      nReads = nReads,
      nWrites = nWrites,
      iaForwardBuffer = iaForwardBuffer,
      iaBackwardBuffer = iaBackwardBuffer,
      iaResultsBuffer = iaResultsBuffer,
      aoBuffer = aoBuffer
    )
  }
}

object RFParams {
  implicit val RFParamsDecoder: Decoder[RFParams] = deriveDecoder[RFParams]

  def fromFile(fileName: String): RFParams = {
    val jsonContent = Source.fromFile(fileName).mkString
    val paramsResult = decode[RFParams](jsonContent)
    paramsResult match {
      case Right(params) =>
        params
      case Left(error) =>
        println(s"Failed to parse RFParams from $fileName: $error")
        RFParams()
    }
  }
}

class WriteAccessOut(params: RFBuilderParams) extends Bundle {
  val addr = UInt(params.addrWidth.W)
  val tag = UInt(params.tagWidth.W)
}

class ReadAccessOut(params: RFBuilderParams) extends Bundle {
  val addr = UInt(params.addrWidth.W)
  val tag = UInt(params.tagWidth.W)
  val value = UInt(params.width.W)
  val resolved = Bool()
}

class RegisterState(params: RFBuilderParams) extends Bundle {
  /** Current value stored in the register */
  val value = UInt(params.width.W)
  
  /** Bit vector indicating which rename tags are pending */
  val pendingTags = Vec(params.nTags, Bool())
  
  /** The last rename tag that was issued for this register */
  val tag = UInt(params.tagWidth.W)
}

class Result(params: RFBuilderParams) extends Bundle {
  val value = UInt(params.width.W)
  val addr = UInt(params.addrWidth.W)
  val tag = UInt(params.tagWidth.W)
  val force = Bool()
}

class AccessIn(params: RFParams) extends Bundle {
  val reads = Vec(params.nReads, Valid(UInt(params.addrWidth.W)))
  val writes = Vec(params.nWrites, Valid(UInt(params.addrWidth.W)))
}

class AccessOut(params: RFParams) extends Bundle {
  val builderParams = params.toBuilderParams()
  val reads = Vec(params.nReads, Valid(new ReadAccessOut(builderParams)))
  val writes = Vec(params.nWrites, Valid(new WriteAccessOut(builderParams)))
}

/**
 * Register File - handles register file and tagging
 */
class RegisterFile(params: RFParams) extends Module {
  // Create builder params for internal use
  val builderParams = params.toBuilderParams()

  val io = IO(new Bundle {
    val iAccess = Flipped(Decoupled(new AccessIn(params)))
    val iResults = Input(Vec(params.nWrites, Valid(new Result(builderParams))))
    val oAccess = Decoupled(new AccessOut(params))
  })

  val resetBuffered = ResetStage(clock, reset)

  withReset(resetBuffered) {

    val stateInitial = Wire(Vec(params.nRegs, new RegisterState(builderParams)))

    // Initialize all registers to 0 with no in-flight writes
    for (i <- 0 until params.nRegs) {
      stateInitial(i).value := 0.U
      for (j <- 0 until params.nTags) {
        stateInitial(i).pendingTags(j) := false.B  // No writes currently pending
      }
      stateInitial(i).tag := 0.U  // No rename tags issued yet
    }
    val stateNext = Wire(Vec(params.nRegs, new RegisterState(builderParams)))
    val state = RegNext(stateNext, stateInitial)

    // i -> a
    val aAccessIn = DoubleBuffer(io.iAccess, params.iaForwardBuffer, params.iaBackwardBuffer)
    val aAccessOut = Wire(Decoupled(new AccessOut(params)))

    // Combinational 'a' logic

    // Reads
    for (i <- 0 until params.nReads) {
      aAccessOut.bits.reads(i).valid := aAccessIn.bits.reads(i).valid
      val addr = aAccessIn.bits.reads(i).bits
      val tag = state(addr).tag
      when (aAccessIn.bits.reads(i).valid) {
        aAccessOut.bits.reads(i).bits.resolved := !state(addr).pendingTags(tag)
        aAccessOut.bits.reads(i).bits.value := state(addr).value
        aAccessOut.bits.reads(i).bits.tag := tag
        aAccessOut.bits.reads(i).bits.addr := aAccessIn.bits.reads(i).bits
      } .otherwise {
        // If read is not enabled we set resolved to true.
        // That way we don't wait for this value in Reservation Stations.
        aAccessOut.bits.reads(i).bits.resolved := true.B
        aAccessOut.bits.reads(i).bits.value := DontCare
        aAccessOut.bits.reads(i).bits.tag := DontCare
        aAccessOut.bits.reads(i).bits.addr := DontCare
      }
    }

    // Writes
    for (i <- 0 until params.nWrites) {
      aAccessOut.bits.writes(i).valid := aAccessIn.bits.writes(i).valid
      aAccessOut.bits.writes(i).bits.addr := aAccessIn.bits.writes(i).bits
      val addr = aAccessIn.bits.writes(i).bits
      val nextTag = Wire(UInt(params.tagWidth.W))
      when (state(addr).tag === (params.nTags-1).U) {
        nextTag := 0.U
      } .otherwise {
        nextTag := state(addr).tag + 1.U
      }
      aAccessOut.bits.writes(i).bits.tag := nextTag
    }

    // Indicates that one of the write access wasn't able to acquire a new
    // tag and so we stall.
    val stalled = Wire(Bool())
    stalled := false.B
    
    // Backpressure: ready when output can accept and no tag stalls
    aAccessOut.valid := aAccessIn.valid && !stalled
    aAccessIn.ready := aAccessOut.ready && !stalled

    // a -> o
    val oAccess = DecoupledBuffer(aAccessOut, params.aoBuffer)
    io.oAccess <> oAccess

    // Logic to update the state
 
    // Input buffers for write initialization and results
    val aResults = Wire(Vec(params.nWrites, Valid(new Result(builderParams))))
    for (i <- 0 until params.nWrites) {
      aResults(i) := ValidBuffer(io.iResults(i), params.iaResultsBuffer)
    }

    // Initialize stateNext with current state
    stateNext := state

    // State update logic: iResult and iAccess should not conflict because:
    // - iResult clears pendingTags[result.tag] and may update value
    // - iAccess sets pendingTags[nextTag] and updates tag field
    // - Different pendingTags bits are modified (result.tag vs nextTag)
    // - Different fields are updated (value vs tag)
    // - nextTag can never equal a pending result.tag since we stall if nextTag is already pending
    for (regIndex <- 0 until params.nRegs) {
      for (writeIndex <- 0 until params.nWrites) {
        // When a result arrives we write the value in and
        // we update the pendingTag to indicate that we're not still
        // waiting on this result.
        val result = aResults(writeIndex)
        when (result.valid && result.bits.addr === regIndex.U) {
          val tag = Wire(UInt(params.tagWidth.W))
          when (result.bits.force) {
            // If this value is forced it doesn't come with a tag and we
            // automatically increment the tag.

            // Note: If a CommandPacket writes to a register while the running program is
            // writing to a register there is no protection against them stomping on
            // each other and potentially putting us into an unrecoverable state that
            // requires a reset to recover from.

            tag := state(regIndex).tag + 1.U
            stateNext(regIndex).value := result.bits.value
            stateNext(regIndex).tag := tag
          } .otherwise {
            tag := result.bits.tag
            stateNext(regIndex).value := result.bits.value
          }
          stateNext(regIndex).pendingTags(tag) := false.B
        }
        
        // When a write access arrives we need to increment the tag
        // and update the pendingTag to indicate we're waiting on this
        // result.
        val write = aAccessIn.bits.writes(writeIndex)
        when (aAccessIn.valid && write.valid && write.bits === regIndex.U) {
          val nextTag = Wire(UInt(params.tagWidth.W))
          when (state(regIndex).tag === (params.nTags-1).U) {
            nextTag := 0.U
          } .otherwise {
            nextTag := state(regIndex).tag + 1.U
          }
          when (state(regIndex).pendingTags(nextTag)) {
            stalled := true.B
          } .otherwise {
            stateNext(regIndex).tag := nextTag
            stateNext(regIndex).pendingTags(nextTag) := true.B
          }
        }
      }
    }

  }
}

/** Generator object for creating RegisterFile modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of RegisterFile modules with configurable parameters.
  */
/**
 * Port wrapper for register file read operations
 */
class ReadPort(params: RFBuilderParams) {
  val input = Wire(Valid(UInt(params.addrWidth.W)))
  var output: Valid[ReadAccessOut] = _
  
  // Default values
  input.valid := false.B
  input.bits := DontCare
}

/**
 * Port wrapper for register file write operations
 */
class WritePort(params: RFBuilderParams) {
  val input = Wire(Valid(UInt(params.addrWidth.W)))
  var output: Valid[WriteAccessOut] = _
  var result: Valid[Result] = _
  
  // Default values
  input.valid := false.B
  input.bits := DontCare
}

/**
 * Builder class for creating register files with multiple ports
 */
class RegisterFileBuilder(val params: RFBuilderParams) {
  private var readPorts = List[ReadPort]()
  private var writePorts = List[WritePort]()
  
  /**
   * Create a new read port for the register file
   */
  def makeReadPort(): ReadPort = {
    val port = new ReadPort(params)
    readPorts = readPorts :+ port
    port
  }
  
  /**
   * Create a new write port for the register file
   */
  def makeWritePort(): WritePort = {
    val port = new WritePort(params)
    writePorts = writePorts :+ port
    port
  }
  
  /**
   * Create the actual RegisterFile module and connect all ports
   */
  def makeModule(): RegisterFile = {
    // Convert to RFParams with actual port counts
    val actualParams = params.toRFParams(
      nReads = readPorts.length,
      nWrites = writePorts.length
    )
    
    val rf = Module(new RegisterFile(actualParams))
    
    // Initialize output wires for ports
    for (i <- readPorts.indices) {
      readPorts(i).output = Wire(Valid(new ReadAccessOut(params)))
    }
    
    for (i <- writePorts.indices) {
      writePorts(i).output = Wire(Valid(new WriteAccessOut(params)))
      writePorts(i).result = Wire(Valid(new Result(params)))
      writePorts(i).result.valid := false.B
      writePorts(i).result.bits := DontCare
    }
    
    // Connect data ports
    for (i <- readPorts.indices) {
      rf.io.iAccess.bits.reads(i) := readPorts(i).input
      readPorts(i).output := rf.io.oAccess.bits.reads(i)
    }
    
    for (i <- writePorts.indices) {
      rf.io.iAccess.bits.writes(i) := writePorts(i).input
      writePorts(i).output := rf.io.oAccess.bits.writes(i)
      rf.io.iResults(i) := writePorts(i).result
    }
    
    // Note: Control signals (valid/ready) for rf.io.iAccess and rf.io.oAccess
    // need to be handled by the parent module using this RegisterFile
    
    rf
  }
}

/**
 * Factory object for creating RegisterFileBuilder instances
 */
object RegisterFileBuilder {
  def apply(params: RFBuilderParams): RegisterFileBuilder = {
    new RegisterFileBuilder(params)
  }
}

object RegisterFileGenerator extends zamlet.ModuleGenerator {
  /** Create a RegisterFile module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return RegisterFile module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> RegisterFile <RFParamsFileName>")
      null
    } else {
      val params = RFParams.fromFile(args(0))
      new RegisterFile(params)
    }
  }
}
