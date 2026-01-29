package zamlet.utils

import chisel3._
import chisel3.util._
import zamlet.ModuleGenerator
import io.circe._
import io.circe.parser._
import io.circe.generic.auto._
import io.circe.generic.semiauto._
import scala.io.Source

/** Parameters for DroppingFifo module loaded from JSON config file. */
case class DroppingFifoParams(
  width: Int = 4,
  depth: Int = 8,
  countBits: Int = 4
)

/** Companion object for DroppingFifoParams with factory methods. */
object DroppingFifoParams {
  implicit val DroppingFifoParamsDecoder: Decoder[DroppingFifoParams] = deriveDecoder[DroppingFifoParams]

  /** Load DroppingFifo parameters from a JSON configuration file.
    *
    * @param fileName Path to the JSON configuration file
    * @return DroppingFifoParams instance with configuration loaded from file
    */
  def fromFile(fileName: String): DroppingFifoParams = {
    val jsonContent = Source.fromFile(fileName).mkString
    val paramsResult = decode[DroppingFifoParams](jsonContent)
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

// This FIFO takes an additional input 'drop' that indicates that the input at
// 'i' can be discarded.
//
// It produces an output 'count' which indicates how many inputs have been consumed
// since that item was consumed.

class DroppingFifo[T <: Data](t: T, depth: Int, countBits: Int) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(DecoupledIO(t))
    // If drop is high we discard the value on o
    val drop = Input(Bool())
    val o = DecoupledIO(t)
    // How many inputs we've consumed since this item entered the fifo.
    val count = Output(UInt(countBits.W))
    // Expose all internal contents and counts for dependency checking
    val allContents = Output(Vec(depth, t))
    val allCounts = Output(Vec(depth, UInt(countBits.W)))
    val allValids = Output(Vec(depth, Bool()))
    // Whether they are at the output of the fifo.
    val allAtOutput = Output(Vec(depth, Bool()))
  })

  val contents = Reg(Vec(depth, t))
  val counts = Reg(Vec(depth, UInt(countBits.W)))
  val writePtr = RegInit(UInt(log2Ceil(depth).W), 0.U)
  val readPtr = RegInit(UInt(log2Ceil(depth).W), 0.U)
  val empty = RegInit(Bool(), true.B)
  val full = RegInit(Bool(), false.B)

  io.i.ready := !full || io.drop || (full && io.o.ready)

  when (io.i.valid && io.i.ready) {
    // Increment all counts since an input was consumed
    for (i <- 0 until depth) {
      counts(i) := counts(i) + 1.U
    }
    when (!io.drop) {
      contents(writePtr) := io.i.bits
      counts(writePtr) := 0.U
      writePtr := (writePtr + 1.U) % depth.U
      empty := false.B
      full := (writePtr + 1.U) % depth.U === readPtr
    }
  }
  io.o.valid := !empty
  io.o.bits := contents(readPtr)
  io.count := counts(readPtr)

  when (io.o.valid && io.o.ready) {
    readPtr := (readPtr + 1.U) % depth.U
    empty := (readPtr + 1.U) % depth.U === writePtr
    full := false.B
  }

  // If we're writing (not dropping), we can't be empty
  when (io.i.valid && io.i.ready && !io.drop) {
    empty := false.B
  }

  // Connect outputs for internal state
  io.allContents := contents
  io.allCounts := counts
  
  // Determine which entries are valid based on read/write pointers
  val validBits = Wire(Vec(depth, Bool()))
  val iLTWritePtr = Wire(Vec(depth, Bool()))
  for (i <- 0 until depth) {
    if (i == depth-1) {
      iLTWritePtr(i) := false.B
    } else {
      iLTWritePtr(i) := (i.U < writePtr)
    }
    when (readPtr === writePtr) {
      validBits(i) := full
    } .elsewhen (writePtr > readPtr) {
      validBits(i) := (i.U >= readPtr && iLTWritePtr(i))
    } .otherwise {
      validBits(i) := (i.U >= readPtr || iLTWritePtr(i))
    }

    io.allAtOutput(i) := (i.U === readPtr)


    when (empty) {
      validBits(i) := false.B
    } .elsewhen (full) {
      validBits(i) := true.B
    } .otherwise {
      
      if (i == 0) {
        validBits(i) := (writePtr > readPtr && 0.U >= readPtr && 0.U < writePtr) || 
                        (writePtr <= readPtr && (0.U >= readPtr || 0.U < writePtr))
      } else if (i == depth - 1) {
        // For the last index, readPtr <= (depth-1) is always true for valid pointers
        validBits(i) := (writePtr > readPtr && true.B && false.B) || 
                        (writePtr <= readPtr && (true.B || false.B))
      } else {
        validBits(i) := (writePtr > readPtr && i.U >= readPtr && i.U < writePtr) || 
                        (writePtr <= readPtr && (i.U >= readPtr || i.U < writePtr))
      }
    }
  }
  io.allValids := validBits

}

object DroppingFifoGenerator extends ModuleGenerator {
  /** Create a DroppingFifo module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return DroppingFifo module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> DroppingFifo <configFileName>")
      null
    } else {
      val params = DroppingFifoParams.fromFile(args(0))
      new DroppingFifo(UInt(params.width.W), params.depth, params.countBits)
    }
  }
}

object DroppingFifoMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  DroppingFifoGenerator.generate(args(0), Seq(args(1)))
}
