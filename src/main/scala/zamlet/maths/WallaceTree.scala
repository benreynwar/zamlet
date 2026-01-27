package zamlet.maths

import chisel3._
import chisel3.util._
import zamlet.ModuleGenerator
import io.circe._
import io.circe.parser._
import io.circe.generic.semiauto._
import scala.io.Source

// Carry-Save Adder: 3:2 compressor
// Takes 3 numbers, produces 2 numbers (sum + carry) with no carry propagation
// sum + carry represents the same value as a + b + c
class CSA3to2(width: Int) extends Module {
  val io = IO(new Bundle {
    val a = Input(UInt(width.W))
    val b = Input(UInt(width.W))
    val c = Input(UInt(width.W))
    val sum = Output(UInt(width.W))
    val carry = Output(UInt(width.W))
  })

  io.sum := io.a ^ io.b ^ io.c
  io.carry := ((io.a & io.b) | (io.c & (io.a ^ io.b))) << 1
  //io.carry := ((io.a & io.b) | (io.a & io.c) | (io.b & io.c)) << 1
}

// One stage of Wallace reduction
// Takes N inputs, groups into 3s, applies CSAs, outputs fewer numbers
class WallaceStage(numInputs: Int, width: Int) extends Module {
  require(numInputs >= 3, "WallaceStage needs at least 3 inputs")

  // Number of full groups of 3
  val numCSAs: Int = numInputs / 3
  // Leftover inputs (0, 1, or 2)
  val leftover: Int = numInputs % 3
  // Each CSA: 3 -> 2, plus leftovers pass through
  val numOutputs: Int = numCSAs * 2 + leftover

  val io = IO(new Bundle {
    val inputs = Input(Vec(numInputs, UInt(width.W)))
    val outputs = Output(Vec(numOutputs, UInt(width.W)))
  })

  val csas: Seq[CSA3to2] = Seq.fill(numCSAs)(Module(new CSA3to2(width)))

  var outputIdx: Int = 0

  // Process full groups of 3
  for (i <- 0 until numCSAs) {
    csas(i).io.a := io.inputs(i * 3)
    csas(i).io.b := io.inputs(i * 3 + 1)
    csas(i).io.c := io.inputs(i * 3 + 2)
    io.outputs(outputIdx) := csas(i).io.sum
    io.outputs(outputIdx + 1) := csas(i).io.carry
    outputIdx += 2
  }

  // Pass through leftovers
  for (i <- 0 until leftover) {
    io.outputs(outputIdx) := io.inputs(numCSAs * 3 + i)
    outputIdx += 1
  }
}

// Wallace tree adder: adds N numbers using carry-save adders
// Depth is O(log N) CSA stages + O(log W) for final addition
object WallaceTreeAdder {
  // Compute number of outputs after one reduction stage
  def stageOutputCount(n: Int): Int = (n / 3) * 2 + (n % 3)

  // Compute sequence of input counts for each stage
  def stageSizes(numInputs: Int): Seq[Int] = {
    var sizes = Seq(numInputs)
    var n = numInputs
    while (n > 2) {
      n = stageOutputCount(n)
      sizes = sizes :+ n
    }
    sizes
  }
}

case class WallaceTreeAdderParams(
  inputWidth: Int,
  numInputs: Int,
  registerInput: Boolean = false,
  registerOutput: Boolean = false,
  regEveryNStages: Option[Int] = None,
  regBeforeFinalAdd: Boolean = false,
  finalAdderSectionWidth: Option[Int] = None,
  finalAdderRegAfterSectionCalc: Boolean = false,
  finalAdderRegAfterCarryCalc: Boolean = false
) {
  val outputWidth: Int = inputWidth + log2Ceil(numInputs)
  val sizes: Seq[Int] = WallaceTreeAdder.stageSizes(numInputs)
  val numStages: Int = sizes.length - 1

  def shouldRegisterAfterStage(stageIdx: Int): Boolean = {
    regEveryNStages match {
      case Some(n) if n > 0 => ((stageIdx + 1) % n) == 0
      case _ => false
    }
  }
}

object WallaceTreeAdderParams {
  implicit val decoder: Decoder[WallaceTreeAdderParams] = deriveDecoder[WallaceTreeAdderParams]

  def fromFile(fileName: String): WallaceTreeAdderParams = {
    val jsonContent: String = Source.fromFile(fileName).mkString
    decode[WallaceTreeAdderParams](jsonContent) match {
      case Right(params) => params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}

class WallaceTreeAdder(numInputs: Int, inputWidth: Int) extends Module {
  require(numInputs >= 2, "Need at least 2 inputs")

  val outputWidth: Int = inputWidth + log2Ceil(numInputs)
  val sizes: Seq[Int] = WallaceTreeAdder.stageSizes(numInputs)
  val numStages: Int = sizes.length - 1

  val io = IO(new Bundle {
    val inputs = Input(Vec(numInputs, UInt(inputWidth.W)))
    val sum = Output(UInt(outputWidth.W))
  })

  // Pad inputs to output width
  val paddedInputs: Vec[UInt] = Wire(Vec(numInputs, UInt(outputWidth.W)))
  for (i <- 0 until numInputs) {
    paddedInputs(i) := io.inputs(i).pad(outputWidth)
  }

  if (numInputs == 2) {
    // No CSA stages needed, just add
    io.sum := paddedInputs(0) + paddedInputs(1)
  } else {
    // Create all stages
    val stages: Seq[WallaceStage] = (0 until numStages).map { i =>
      Module(new WallaceStage(sizes(i), outputWidth))
    }

    // Connect first stage to padded inputs
    for (i <- 0 until numInputs) {
      stages(0).io.inputs(i) := paddedInputs(i)
    }

    // Chain stages together
    for (i <- 1 until numStages) {
      for (j <- 0 until sizes(i)) {
        stages(i).io.inputs(j) := stages(i - 1).io.outputs(j)
      }
    }

    // Final stage outputs 2 numbers, add them
    val lastStage: WallaceStage = stages(numStages - 1)
    io.sum := lastStage.io.outputs(0) + lastStage.io.outputs(1)
  }
}

class ConfigurableWallaceTreeAdder(params: WallaceTreeAdderParams) extends Module {
  import params._
  require(numInputs >= 2, "Need at least 2 inputs")

  override def desiredName = {
    val regStr = (registerInput, registerOutput) match {
      case (true, true) => "_RegIO"
      case (true, false) => "_RegI"
      case (false, true) => "_RegO"
      case (false, false) => ""
    }
    val pipeStr = regEveryNStages.map(n => s"_Pipe$n").getOrElse("")
    s"WallaceTreeAdder${numInputs}x${inputWidth}${regStr}${pipeStr}"
  }

  val io = IO(new Bundle {
    val inputs = Input(Vec(numInputs, UInt(inputWidth.W)))
    val sum = Output(UInt(outputWidth.W))
  })

  // Optionally register inputs
  val inputsToUse: Vec[UInt] = if (registerInput) RegNext(io.inputs) else io.inputs

  // Pad inputs to output width
  val paddedInputs: Vec[UInt] = Wire(Vec(numInputs, UInt(outputWidth.W)))
  for (i <- 0 until numInputs) {
    paddedInputs(i) := inputsToUse(i).pad(outputWidth)
  }

  val result: UInt = if (numInputs == 2) {
    // No CSA stages needed, just add
    paddedInputs(0) + paddedInputs(1)
  } else {
    // Create all stages
    val stages: Seq[WallaceStage] = (0 until numStages).map { i =>
      Module(new WallaceStage(sizes(i), outputWidth))
    }

    // Connect first stage to padded inputs
    for (i <- 0 until numInputs) {
      stages(0).io.inputs(i) := paddedInputs(i)
    }

    // Chain stages together, optionally inserting pipeline registers
    for (i <- 1 until numStages) {
      val prevOutputs: Vec[UInt] = stages(i - 1).io.outputs
      val maybeRegistered: Vec[UInt] = if (shouldRegisterAfterStage(i - 1)) {
        RegNext(prevOutputs)
      } else {
        prevOutputs
      }
      for (j <- 0 until sizes(i)) {
        stages(i).io.inputs(j) := maybeRegistered(j)
      }
    }

    // Final stage outputs 2 numbers, add them
    val lastStage: WallaceStage = stages(numStages - 1)
    val needRegBeforeFinalAdd: Boolean =
      regBeforeFinalAdd || shouldRegisterAfterStage(numStages - 1)
    val finalOutputs: Vec[UInt] = if (needRegBeforeFinalAdd) {
      RegNext(lastStage.io.outputs)
    } else {
      lastStage.io.outputs
    }

    finalAdderSectionWidth match {
      case Some(secWidth) =>
        val adderParams = CarrySelectAdderParams(outputWidth, secWidth,
          regAfterSectionCalc = finalAdderRegAfterSectionCalc,
          regAfterCarryCalc = finalAdderRegAfterCarryCalc)
        val adder = Module(new CarrySelectAdder(adderParams))
        adder.io.a := finalOutputs(0)
        adder.io.b := finalOutputs(1)
        adder.io.sum(outputWidth - 1, 0)
      case None =>
        finalOutputs(0) + finalOutputs(1)
    }
  }

  // Optionally register output
  io.sum := (if (registerOutput) RegNext(result) else result)
}

object WallaceTreeAdderGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <outputDir> <configFile>")
      null
    } else {
      new ConfigurableWallaceTreeAdder(WallaceTreeAdderParams.fromFile(args(0)))
    }
  }
}

object WallaceTreeAdderMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  WallaceTreeAdderGenerator.generate(args(0), Seq(args(1)))
}
