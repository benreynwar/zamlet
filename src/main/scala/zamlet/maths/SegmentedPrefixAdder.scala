package zamlet.maths

import chisel3._
import chisel3.util._
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
    registerOutput: Boolean = true) extends Module {
  require(width >= 8, "width must be at least 8")
  require(isPow2(width), "width must be a power of two")

  val latency: Int =
    (if (registerInput) 1 else 0) +
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
  for (distance <- Iterator.iterate(1)(_ * 2).takeWhile(_ < width)) {
    val nextGenerate = Wire(Vec(width, Bool()))
    val nextPropagate = Wire(Vec(width, Bool()))
    for (bit <- 0 until width) {
      if (bit >= distance) {
        nextGenerate(bit) := groupGenerate(bit) ||
          (groupPropagate(bit) && groupGenerate(bit - distance))
        nextPropagate(bit) := groupPropagate(bit) && groupPropagate(bit - distance)
      } else {
        nextGenerate(bit) := groupGenerate(bit)
        nextPropagate(bit) := groupPropagate(bit)
      }
    }
    groupGenerate = nextGenerate
    groupPropagate = nextPropagate
  }

  val sumBits = (0 until width).map { bit =>
    val carryIn = if (bit == 0) {
      s0Input.subtract
    } else {
      Mux(isElementStart(bit, s0Input.elementWidthLog2), s0Input.subtract, groupGenerate(bit - 1))
    }
    bitPropagate(bit) ^ carryIn
  }

  val s1 = Wire(Valid(new SegmentedPrefixAdderOutput(width)))
  s1.valid := s0.valid
  s1.bits.sum := VecInit(sumBits).asUInt
  s1.bits.carryOut := VecInit(groupGenerate).asUInt

  io.output := ValidBuffer(s1, registerOutput)
}

object SegmentedPrefixAdder {
  def modeWidth(width: Int): Int = log2Ceil(log2Ceil(width) + 1)
}

object SegmentedPrefixAdderMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir> [width]")
    System.exit(1)
  }
  val width = if (args.length >= 2) args(1).toInt else 64
  _root_.circt.stage.ChiselStage.emitSystemVerilogFile(
    gen = new SegmentedPrefixAdder(width),
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
