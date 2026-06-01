package zamlet.maths

import chisel3._
import chisel3.util._
import zamlet.utils.ValidBuffer

class SegmentedMultiplierRecombineAddInput(width: Int) extends Bundle {
  val a = UInt(width.W)
  val b = UInt(width.W)
}

class SegmentedMultiplierRecombineAddOutput(width: Int) extends Bundle {
  val sum = UInt(width.W)
}

class SegmentedMultiplierRecombineAddIO(width: Int) extends Bundle {
  val input = Flipped(Valid(new SegmentedMultiplierRecombineAddInput(width)))
  val output = Valid(new SegmentedMultiplierRecombineAddOutput(width))
}

class SegmentedMultiplierRecombineAddStage(
    width: Int,
    registerOutput: Boolean,
    prefixAdderMinWidth: Int) extends Module {
  require(width >= 8, "width must be at least 8")
  require(isPow2(width), "width must be a power of two")
  require(isPow2(prefixAdderMinWidth), "prefixAdderMinWidth must be a power of two")

  val latency: Int = SegmentedMultiplierRecombineAddStage.latency(registerOutput)

  override def desiredName: String = s"SegmentedMultiplierRecombineAddStage$width"

  val io = IO(new SegmentedMultiplierRecombineAddIO(width))

  if (width >= prefixAdderMinWidth) {
    val adder = Module(new SegmentedPrefixAdder(
      width,
      registerInput = false,
      registerOutput = registerOutput))
    adder.io.input.valid := io.input.valid
    adder.io.input.bits.a := io.input.bits.a
    adder.io.input.bits.b := io.input.bits.b
    adder.io.input.bits.subtract := false.B
    adder.io.input.bits.elementWidthLog2 := log2Ceil(width).U

    io.output.valid := adder.io.output.valid
    io.output.bits.sum := adder.io.output.bits.sum
  } else {
    val output = Wire(Valid(new SegmentedMultiplierRecombineAddOutput(width)))
    output.valid := io.input.valid
    output.bits.sum := io.input.bits.a + io.input.bits.b
    io.output := ValidBuffer(output, registerOutput)
  }
}

class SegmentedMultiplierRecombineInput(width: Int) extends Bundle {
  val loLo = UInt(width.W)
  val loHi = UInt(width.W)
  val hiLo = UInt(width.W)
  val hiHi = UInt(width.W)
  val signedA = Bool()
  val signedB = Bool()
  val childElementMode = Bool()
}

class SegmentedMultiplierRecombineOutput(width: Int) extends Bundle {
  val product = UInt((2 * width).W)
}

class SegmentedMultiplierRecombineIO(width: Int) extends Bundle {
  val input = Flipped(Valid(new SegmentedMultiplierRecombineInput(width)))
  val output = Valid(new SegmentedMultiplierRecombineOutput(width))
}

class SegmentedMultiplierRecombine(
    width: Int,
    registerInput: Boolean = false,
    registerMiddle: Boolean = true,
    registerOutput: Boolean = true,
    prefixAdderMinWidth: Int = 32) extends Module {
  require(width >= 4, "width must be at least 4")
  require(isPow2(width), "width must be a power of two")
  require(isPow2(prefixAdderMinWidth), "prefixAdderMinWidth must be a power of two")

  val latency: Int = SegmentedMultiplierRecombine.latency(
    registerInput,
    registerMiddle,
    registerOutput)

  override def desiredName: String = s"SegmentedMultiplierRecombine$width"

  val io = IO(new SegmentedMultiplierRecombineIO(width))
  val s0 = ValidBuffer(io.input, registerInput)
  val halfWidth = width / 2
  val adderWidth = 2 * width

  def extendPartial(product: UInt, signed: Bool): UInt = {
    Cat(Fill(width, signed && product(width - 1)), product)
  }

  val loAdd = Module(new SegmentedMultiplierRecombineAddStage(
    adderWidth,
    registerOutput = registerMiddle,
    prefixAdderMinWidth = prefixAdderMinWidth))
  loAdd.suggestName("lo")

  val hiAdd = Module(new SegmentedMultiplierRecombineAddStage(
    adderWidth,
    registerOutput = registerMiddle,
    prefixAdderMinWidth = prefixAdderMinWidth))
  hiAdd.suggestName("hi")

  val finalAdd = Module(new SegmentedMultiplierRecombineAddStage(
    adderWidth,
    registerOutput = false,
    prefixAdderMinWidth = prefixAdderMinWidth))
  finalAdd.suggestName("final")

  val s0LoLoWide = extendPartial(s0.bits.loLo, false.B)
  val s0LoHiWide = extendPartial(s0.bits.loHi, s0.bits.signedB)
  val s0HiLoWide = extendPartial(s0.bits.hiLo, s0.bits.signedA)
  val s0HiHiWide = extendPartial(s0.bits.hiHi, s0.bits.signedA || s0.bits.signedB)

  loAdd.io.input.valid := s0.valid
  loAdd.io.input.bits.a := s0LoLoWide
  loAdd.io.input.bits.b := (s0LoHiWide << halfWidth)(adderWidth - 1, 0)

  hiAdd.io.input.valid := s0.valid
  hiAdd.io.input.bits.a := (s0HiLoWide << halfWidth)(adderWidth - 1, 0)
  hiAdd.io.input.bits.b := (s0HiHiWide << width)(adderWidth - 1, 0)

  val middleLatency = SegmentedMultiplierRecombineAddStage.latency(registerMiddle)
  val s1PackedProduct = SegmentedMultiplier.delay(
    Cat(s0.bits.hiHi(width - 1, 0), s0.bits.loLo(width - 1, 0)),
    middleLatency)
  val s1ChildElementMode = SegmentedMultiplier.delay(s0.bits.childElementMode, middleLatency)

  finalAdd.io.input.valid := loAdd.io.output.valid
  finalAdd.io.input.bits.a := loAdd.io.output.bits.sum
  finalAdd.io.input.bits.b := hiAdd.io.output.bits.sum

  val output = Wire(Valid(new SegmentedMultiplierRecombineOutput(width)))
  output.valid := finalAdd.io.output.valid
  output.bits.product := Mux(
    s1ChildElementMode,
    s1PackedProduct,
    finalAdd.io.output.bits.sum)

  io.output := ValidBuffer(output, registerOutput)
}

object SegmentedMultiplierRecombineAddStage {
  def latency(registerOutput: Boolean): Int = {
    if (registerOutput) 1 else 0
  }
}

object SegmentedMultiplierRecombine {
  def latency(
      registerInput: Boolean,
      registerMiddle: Boolean,
      registerOutput: Boolean): Int = {
    (if (registerInput) 1 else 0) +
      SegmentedMultiplierRecombineAddStage.latency(registerOutput = registerMiddle) +
      SegmentedMultiplierRecombineAddStage.latency(registerOutput = false) +
      (if (registerOutput) 1 else 0)
  }
}
