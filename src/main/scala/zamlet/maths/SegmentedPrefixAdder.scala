package zamlet.maths

import chisel3._
import chisel3.util._
import io.circe._
import io.circe.generic.semiauto._
import io.circe.parser._
import scala.io.Source
import zamlet.utils.ValidBuffer

class SegmentedPrefixAdderInput(width: Int) extends Bundle {
  val a = UInt(width.W)
  val b = UInt(width.W)
  val subtract = Bool()
  val elementWidthLog2 = UInt(SegmentedPrefixAdder.modeWidth(width).W)
}

class SegmentedPrefixAdderOutput(width: Int) extends Bundle {
  val sum = UInt(width.W)
  val carryOut = UInt(width.W)
}

class SegmentedPrefixAdderIO(width: Int) extends Bundle {
  val input = Flipped(Valid(new SegmentedPrefixAdderInput(width)))
  val output = Valid(new SegmentedPrefixAdderOutput(width))
}

class SegmentedPrefixAdder(
    width: Int = 64,
    registerInput: Boolean = true,
    registerMiddle: Boolean = false,
    registerOutput: Boolean = true) extends Module {
  require(width >= 8, "width must be at least 8")
  require(isPow2(width), "width must be a power of two")

  val latency: Int =
    (if (registerInput) 1 else 0) +
    (if (registerMiddle) 1 else 0) +
    (if (registerOutput) 1 else 0)

  override def desiredName: String = s"SegmentedPrefixAdder${width}"

  val io = IO(new SegmentedPrefixAdderIO(width))
  val s0 = ValidBuffer(io.input, registerInput)
  val s0Input = s0.bits

  def isElementStart(bit: Int, elementWidthLog2: UInt): Bool = {
    if (bit == 0) {
      true.B
    } else {
      val starts = Seq(
        if (bit % 8 == 0) Some(elementWidthLog2 === 3.U) else None,
        if (bit % 16 == 0) Some(elementWidthLog2 === 4.U) else None,
        if (bit % 32 == 0) Some(elementWidthLog2 === 5.U) else None,
      ).flatten
      if (starts.isEmpty) false.B else starts.reduce(_ || _)
    }
  }

  val bEffective = s0Input.b ^ Fill(width, s0Input.subtract)
  val bitPropagate = (0 until width).map { bit => s0Input.a(bit) ^ bEffective(bit) }

  var groupGenerate: Seq[Bool] = (0 until width).map { bit =>
    val localGenerate = s0Input.a(bit) && bEffective(bit)
    localGenerate || (isElementStart(bit, s0Input.elementWidthLog2) && bitPropagate(bit) && s0Input.subtract)
  }
  var groupPropagate: Seq[Bool] = (0 until width).map { bit =>
    bitPropagate(bit) && !isElementStart(bit, s0Input.elementWidthLog2)
  }
  def prefixStep(
      distance: Int,
      inputGenerate: Seq[Bool],
      inputPropagate: Seq[Bool]): (Seq[Bool], Seq[Bool]) = {
    val nextGenerate = Wire(Vec(width, Bool()))
    val nextPropagate = Wire(Vec(width, Bool()))
    for (bit <- 0 until width) {
      if (bit >= distance) {
        nextGenerate(bit) := inputGenerate(bit) ||
          (inputPropagate(bit) && inputGenerate(bit - distance))
        nextPropagate(bit) := inputPropagate(bit) && inputPropagate(bit - distance)
      } else {
        nextGenerate(bit) := inputGenerate(bit)
        nextPropagate(bit) := inputPropagate(bit)
      }
    }
    ((0 until width).map(nextGenerate(_)), (0 until width).map(nextPropagate(_)))
  }

  val prefixDistances = Iterator.iterate(1)(_ * 2).takeWhile(_ < width).toSeq
  val middleRegisterAfterStages = (prefixDistances.length + 1) / 2
  val (earlyPrefixDistances, latePrefixDistances) =
    prefixDistances.splitAt(middleRegisterAfterStages)

  for (distance <- earlyPrefixDistances) {
    val (nextGenerate, nextPropagate) = prefixStep(distance, groupGenerate, groupPropagate)
    groupGenerate = nextGenerate
    groupPropagate = nextPropagate
  }

  val s1Valid = if (registerMiddle) RegNext(s0.valid, false.B) else s0.valid
  val s1BitPropagate =
    if (registerMiddle) RegNext(VecInit(bitPropagate)) else VecInit(bitPropagate)
  val s1GroupGenerate =
    if (registerMiddle) RegNext(VecInit(groupGenerate)) else VecInit(groupGenerate)
  val s1GroupPropagate =
    if (registerMiddle) RegNext(VecInit(groupPropagate)) else VecInit(groupPropagate)
  val s1Subtract = if (registerMiddle) RegNext(s0Input.subtract) else s0Input.subtract
  val s1ElementWidthLog2 =
    if (registerMiddle) RegNext(s0Input.elementWidthLog2) else s0Input.elementWidthLog2

  groupGenerate = (0 until width).map(s1GroupGenerate(_))
  groupPropagate = (0 until width).map(s1GroupPropagate(_))

  for (distance <- latePrefixDistances) {
    val (nextGenerate, nextPropagate) = prefixStep(distance, groupGenerate, groupPropagate)
    groupGenerate = nextGenerate
    groupPropagate = nextPropagate
  }

  val sumBits = (0 until width).map { bit =>
    val carryIn = if (bit == 0) {
      s1Subtract
    } else {
      Mux(isElementStart(bit, s1ElementWidthLog2), s1Subtract, groupGenerate(bit - 1))
    }
    s1BitPropagate(bit) ^ carryIn
  }

  val s1 = Wire(Valid(new SegmentedPrefixAdderOutput(width)))
  s1.valid := s1Valid
  s1.bits.sum := VecInit(sumBits).asUInt
  s1.bits.carryOut := VecInit(groupGenerate).asUInt

  io.output := ValidBuffer(s1, registerOutput)
}

object SegmentedPrefixAdder {
  def modeWidth(width: Int): Int = log2Ceil(log2Ceil(width) + 1)
}

case class SegmentedPrefixAdderParams(
    width: Int = 64,
    registerInput: Boolean = true,
    registerMiddle: Boolean = false,
    registerOutput: Boolean = true)

object SegmentedPrefixAdderParams {
  implicit val decoder: Decoder[SegmentedPrefixAdderParams] =
    deriveDecoder[SegmentedPrefixAdderParams]

  def fromFile(fileName: String): SegmentedPrefixAdderParams = {
    val jsonContent: String = Source.fromFile(fileName).mkString
    decode[SegmentedPrefixAdderParams](jsonContent) match {
      case Right(params) => params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}

object SegmentedPrefixAdderMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val params = SegmentedPrefixAdderParams.fromFile(args(1))
  _root_.circt.stage.ChiselStage.emitSystemVerilogFile(
    gen = new SegmentedPrefixAdder(
      width = params.width,
      registerInput = params.registerInput,
      registerMiddle = params.registerMiddle,
      registerOutput = params.registerOutput),
    args = Array("--target-dir", args(0)),
    firtoolOpts = Array(
      "-O=debug",
      "-disable-all-randomization",
      "-strip-debug-info",
      "-default-layer-specialization=enable",
      "-lowering-options=disallowLocalVariables,disallowPackedArrays",
    )
  )
}
