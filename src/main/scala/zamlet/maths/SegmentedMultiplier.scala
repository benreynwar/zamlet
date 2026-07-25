package zamlet.maths

import chisel3._
import chisel3.util._
import zamlet.utils.ValidBuffer

class SegmentedMultiplierInput(width: Int) extends Bundle {
  val a = UInt(width.W)
  val b = UInt(width.W)
  val signedA = Bool()
  val signedB = Bool()
  val elementWidthLog2 = UInt(SegmentedMultiplier.modeWidth(width).W)
}

class SegmentedMultiplierOutput(width: Int) extends Bundle {
  val product = UInt((2 * width).W)
}

class SegmentedMultiplierIO(width: Int) extends Bundle {
  val input = Flipped(Valid(new SegmentedMultiplierInput(width)))
  val output = Valid(new SegmentedMultiplierOutput(width))
}

class SegmentedMultiplier(
    width: Int,
    minWidth: Int = 8,
    registerInput: Boolean = true,
    registerLeafInput: Boolean = true,
    recombineBufferMinWidth: Int = 32,
    recombineFinalAdderBufferMinWidth: Int = 128,
    registerOutput: Boolean = true) extends Module {
  require(width >= minWidth, "width must be at least minWidth")
  require(isPow2(width), "width must be a power of two")
  require(isPow2(minWidth), "minWidth must be a power of two")
  require(width % minWidth == 0, "width must be a multiple of minWidth")
  require(recombineBufferMinWidth >= minWidth, "recombineBufferMinWidth must be at least minWidth")
  require(isPow2(recombineFinalAdderBufferMinWidth), "recombineFinalAdderBufferMinWidth must be a power of two")

  val registerRecombine: Boolean = width >= recombineBufferMinWidth
  val registerRecombineFinalAdderMiddle: Boolean = 2 * width >= recombineFinalAdderBufferMinWidth
  val latency: Int = SegmentedMultiplier.latency(
    width,
    minWidth,
    registerInput,
    registerLeafInput,
    recombineBufferMinWidth,
    recombineFinalAdderBufferMinWidth,
    registerOutput)

  override def desiredName: String = s"SegmentedMultiplier${width}x$width"

  val io = IO(new SegmentedMultiplierIO(width))
  val s0 = ValidBuffer(io.input, registerInput)
  val s0Input = s0.bits
  val s1 = Wire(Valid(new SegmentedMultiplierOutput(width)))

  if (width == minWidth) {
    val s0AExt = Cat(s0Input.signedA && s0Input.a(width - 1), s0Input.a).asSInt
    val s0BExt = Cat(s0Input.signedB && s0Input.b(width - 1), s0Input.b).asSInt
    s1.valid := s0.valid
    s1.bits.product := (s0AExt * s0BExt).asUInt(2 * width - 1, 0)
  } else {
    val halfWidth = width / 2

    def child(name: String): SegmentedMultiplier = {
      val module = Module(new SegmentedMultiplier(
        halfWidth,
        minWidth,
        registerInput = registerLeafInput && halfWidth == minWidth,
        registerLeafInput = registerLeafInput,
        recombineBufferMinWidth = recombineBufferMinWidth,
        recombineFinalAdderBufferMinWidth = recombineFinalAdderBufferMinWidth,
        registerOutput = true))
      module.suggestName(name)
      module.io.input.valid := s0.valid
      module.io.input.bits.elementWidthLog2 := s0Input.elementWidthLog2(
        SegmentedMultiplier.modeWidth(halfWidth) - 1, 0)
      module
    }

    val loLo = child("loLo")
    val loHi = child("loHi")
    val hiLo = child("hiLo")
    val hiHi = child("hiHi")

    val s0ALo = s0Input.a(halfWidth - 1, 0)
    val s0AHi = s0Input.a(width - 1, halfWidth)
    val s0BLo = s0Input.b(halfWidth - 1, 0)
    val s0BHi = s0Input.b(width - 1, halfWidth)

    loLo.io.input.bits.a := s0ALo
    loLo.io.input.bits.b := s0BLo
    loLo.io.input.bits.signedA := Mux(s0Input.elementWidthLog2 < log2Ceil(width).U, s0Input.signedA, false.B)
    loLo.io.input.bits.signedB := Mux(s0Input.elementWidthLog2 < log2Ceil(width).U, s0Input.signedB, false.B)

    hiHi.io.input.bits.a := s0AHi
    hiHi.io.input.bits.b := s0BHi
    hiHi.io.input.bits.signedA := s0Input.signedA
    hiHi.io.input.bits.signedB := s0Input.signedB

    loHi.io.input.bits.a := s0ALo
    loHi.io.input.bits.b := s0BHi
    loHi.io.input.bits.signedA := false.B
    loHi.io.input.bits.signedB := s0Input.signedB

    hiLo.io.input.bits.a := s0AHi
    hiLo.io.input.bits.b := s0BLo
    hiLo.io.input.bits.signedA := s0Input.signedA
    hiLo.io.input.bits.signedB := false.B

    val s1ChildElementMode = SegmentedMultiplier.delay(
      s0Input.elementWidthLog2 < log2Ceil(width).U, loLo.latency)
    val s1SignedA = SegmentedMultiplier.delay(s0Input.signedA, loLo.latency)
    val s1SignedB = SegmentedMultiplier.delay(s0Input.signedB, loLo.latency)

    val recombine = Module(new SegmentedMultiplierRecombine(
      width,
      registerInput = false,
      registerCarrySaveOutput = registerRecombine,
      registerFinalAdderMiddle = registerRecombineFinalAdderMiddle,
      registerOutput = false))
    recombine.io.input.valid := loLo.io.output.valid
    recombine.io.input.bits.loLo := loLo.io.output.bits.product
    recombine.io.input.bits.loHi := loHi.io.output.bits.product
    recombine.io.input.bits.hiLo := hiLo.io.output.bits.product
    recombine.io.input.bits.hiHi := hiHi.io.output.bits.product
    recombine.io.input.bits.signedA := s1SignedA
    recombine.io.input.bits.signedB := s1SignedB
    recombine.io.input.bits.childElementMode := s1ChildElementMode

    s1.valid := recombine.io.output.valid
    s1.bits.product := recombine.io.output.bits.product
  }

  io.output := ValidBuffer(s1, registerOutput)
}

object SegmentedMultiplier {
  def modeWidth(width: Int): Int = log2Ceil(log2Ceil(width) + 1)

  def latency(
      width: Int,
      minWidth: Int,
      registerInput: Boolean,
      registerLeafInput: Boolean,
      recombineBufferMinWidth: Int,
      recombineFinalAdderBufferMinWidth: Int,
      registerOutput: Boolean): Int = {
    val inputLatency = if (registerInput) 1 else 0
    val outputLatency = if (registerOutput) 1 else 0
    val internalLatency =
      if (width == minWidth) {
        0
      } else {
        latency(
          width / 2,
          minWidth,
          registerInput = registerLeafInput && width / 2 == minWidth,
          registerLeafInput = registerLeafInput,
          recombineBufferMinWidth = recombineBufferMinWidth,
          recombineFinalAdderBufferMinWidth = recombineFinalAdderBufferMinWidth,
          registerOutput = true) +
          SegmentedMultiplierRecombine.latency(
            registerInput = false,
            registerCarrySaveOutput = width >= recombineBufferMinWidth,
            registerFinalAdderMiddle = 2 * width >= recombineFinalAdderBufferMinWidth,
            registerOutput = false)
      }
    inputLatency + internalLatency + outputLatency
  }

  def delay[T <: Data](value: T, cycles: Int): T = {
    if (cycles == 0) value else ShiftRegister(value, cycles)
  }
}

object SegmentedMultiplierMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <width> [minWidth]")
    System.exit(1)
  }
  val width = args(1).toInt
  val minWidth = if (args.length >= 3) args(2).toInt else 8
  _root_.circt.stage.ChiselStage.emitSystemVerilogFile(
    gen = new SegmentedMultiplier(width, minWidth),
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
