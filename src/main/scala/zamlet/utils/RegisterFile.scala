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

class WriteAccessOut(params: RFParams) extends Bundle {
  val addr = UInt(params.addrWidth.W)
  val tag = UInt(params.tagWidth.W)
}

class ReadAccessOut(params: RFParams) extends Bundle {
  val addr = UInt(params.addrWidth.W)
  val tag = UInt(params.tagWidth.W)
  val value = UInt(params.width.W)
  val resolved = Bool()
}

class RegisterState(params: RFParams) extends Bundle {
  /** Current value stored in the register */
  val value = UInt(params.width.W)
  
  /** Bit vector indicating which rename tags are pending */
  val pendingTags = Vec(params.nTags, Bool())
  
  /** The last rename tag that was issued for this register */
  val tag = UInt(params.tagWidth.W)
}

class Result(params: RFParams) extends Bundle {
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
  val reads = Vec(params.nReads, Valid(new ReadAccessOut(params)))
  val writes = Vec(params.nWrites, Valid(new WriteAccessOut(params)))
}

/**
 * Register File - handles register file and tagging
 */
class RegisterFile(params: RFParams) extends Module {

  val io = IO(new Bundle {
    val iAccess = Flipped(Decoupled(new AccessIn(params)))
    val iResults = Input(Vec(params.nWrites, Valid(new Result(params))))
    val oAccess = Decoupled(new AccessOut(params))
  })

  val resetBuffered = ResetStage(clock, reset)

  withReset(resetBuffered) {

    val stateInitial = Wire(Vec(params.nRegs, new RegisterState(params)))

    // Initialize all registers to 0 with no in-flight writes
    for (i <- 0 until params.nRegs) {
      stateInitial(i).value := 0.U
      for (j <- 0 until params.nTags) {
        stateInitial(i).pendingTags(j) := false.B  // No writes currently pending
      }
      stateInitial(i).tag := 0.U  // No rename tags issued yet
    }
    val stateNext = Wire(Vec(params.nRegs, new RegisterState(params)))
    val state = RegNext(stateNext, stateInitial)

    // i -> a
    val aAccessIn = DoubleBuffer(io.iAccess, params.iaForwardBuffer, params.iaBackwardBuffer)
    val aAccessOut = Wire(Decoupled(new AccessOut(params)))

    // Combinational 'a' logic

    // Reads
    for (i <- 0 until params.nReads) {
      aAccessOut.bits.reads(i).valid := aAccessIn.bits.reads(i).valid
      aAccessOut.bits.reads(i).bits.addr := aAccessIn.bits.reads(i).bits
      val addr = aAccessIn.bits.reads(i).bits
      val tag = state(addr).tag
      aAccessOut.bits.reads(i).bits.tag := tag
      aAccessOut.bits.reads(i).bits.value := state(addr).value
      aAccessOut.bits.reads(i).bits.resolved := !state(addr).pendingTags(tag)
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
    val aResults = Wire(Vec(params.nWrites, Valid(new Result(params))))
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
          stateNext(regIndex).pendingTags(result.bits.tag) := false.B
          when (state(regIndex).tag === result.bits.tag || result.bits.force) {
            stateNext(regIndex).value := result.bits.value
          }
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
