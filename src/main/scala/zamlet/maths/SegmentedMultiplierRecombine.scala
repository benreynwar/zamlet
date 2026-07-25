package zamlet.maths

import chisel3._
import chisel3.util._
import zamlet.utils.ValidBuffer

class SegmentedMultiplierRecombineAdderIO(width: Int) extends Bundle {
  val input = Flipped(Valid(Vec(4, UInt(width.W))))
  val output = Valid(UInt(width.W))
}

class SegmentedMultiplierRecombineAdder(
    width: Int,
    registerCarrySaveOutput: Boolean,
    registerFinalAdderMiddle: Boolean,
    registerOutput: Boolean,
    prefixAdderMinWidth: Int) extends Module {
  require(width >= 8, "width must be at least 8")
  require(isPow2(width), "width must be a power of two")
  require(isPow2(prefixAdderMinWidth), "prefixAdderMinWidth must be a power of two")
  require(!registerFinalAdderMiddle || width >= prefixAdderMinWidth, "middle register requires prefix adder")

  val latency: Int = SegmentedMultiplierRecombineAdder.latency(
    registerCarrySaveOutput,
    registerFinalAdderMiddle,
    registerOutput)

  override def desiredName: String = s"SegmentedMultiplierRecombineAdder$width"

  val io = IO(new SegmentedMultiplierRecombineAdderIO(width))

  val reduce0 = Module(new CSA3to2(width))
  val reduce1 = Module(new CSA3to2(width))

  reduce0.io.a := io.input.bits(0)
  reduce0.io.b := io.input.bits(1)
  reduce0.io.c := io.input.bits(2)

  reduce1.io.a := reduce0.io.sum
  reduce1.io.b := reduce0.io.carry
  reduce1.io.c := io.input.bits(3)

  val carrySave = Wire(Valid(Vec(2, UInt(width.W))))
  carrySave.valid := io.input.valid
  carrySave.bits(0) := reduce1.io.sum
  carrySave.bits(1) := reduce1.io.carry
  val s1 = ValidBuffer(carrySave, registerCarrySaveOutput)

  if (width >= prefixAdderMinWidth) {
    val adder = Module(new SegmentedPrefixAdder(
      width,
      registerInput = false,
      registerMiddle = registerFinalAdderMiddle,
      registerOutput = registerOutput))
    adder.io.input.valid := s1.valid
    adder.io.input.bits.a := s1.bits(0)
    adder.io.input.bits.b := s1.bits(1)
    adder.io.input.bits.subtract := false.B
    adder.io.input.bits.elementWidthLog2 := log2Ceil(width).U

    io.output.valid := adder.io.output.valid
    io.output.bits := adder.io.output.bits.sum
  } else {
    val output = Wire(Valid(UInt(width.W)))
    output.valid := s1.valid
    output.bits := s1.bits(0) + s1.bits(1)
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
    registerCarrySaveOutput: Boolean = true,
    registerFinalAdderMiddle: Boolean = false,
    registerOutput: Boolean = true,
    prefixAdderMinWidth: Int = 32) extends Module {
  require(width >= 4, "width must be at least 4")
  require(isPow2(width), "width must be a power of two")
  require(isPow2(prefixAdderMinWidth), "prefixAdderMinWidth must be a power of two")

  val latency: Int = SegmentedMultiplierRecombine.latency(
    registerInput,
    registerCarrySaveOutput,
    registerFinalAdderMiddle,
    registerOutput)

  override def desiredName: String = s"SegmentedMultiplierRecombine$width"

  val io = IO(new SegmentedMultiplierRecombineIO(width))
  val s0 = ValidBuffer(io.input, registerInput)
  val halfWidth = width / 2
  val adderWidth = 2 * width

  def extendPartial(product: UInt, signed: Bool): UInt = {
    Cat(Fill(width, signed && product(width - 1)), product)
  }

  val recombineAdder = Module(new SegmentedMultiplierRecombineAdder(
    adderWidth,
    registerCarrySaveOutput = registerCarrySaveOutput,
    registerFinalAdderMiddle = registerFinalAdderMiddle,
    registerOutput = false,
    prefixAdderMinWidth = prefixAdderMinWidth))
  recombineAdder.suggestName("adder")

  val s0LoLoWide = extendPartial(s0.bits.loLo, false.B)
  val s0LoHiWide = extendPartial(s0.bits.loHi, s0.bits.signedB)
  val s0HiLoWide = extendPartial(s0.bits.hiLo, s0.bits.signedA)
  val s0HiHiWide = extendPartial(s0.bits.hiHi, s0.bits.signedA || s0.bits.signedB)

  recombineAdder.io.input.valid := s0.valid
  recombineAdder.io.input.bits(0) := s0LoLoWide
  recombineAdder.io.input.bits(1) := (s0LoHiWide << halfWidth)(adderWidth - 1, 0)
  recombineAdder.io.input.bits(2) := (s0HiLoWide << halfWidth)(adderWidth - 1, 0)
  recombineAdder.io.input.bits(3) := (s0HiHiWide << width)(adderWidth - 1, 0)

  val adderLatency = SegmentedMultiplierRecombineAdder.latency(
    registerCarrySaveOutput = registerCarrySaveOutput,
    registerFinalAdderMiddle = registerFinalAdderMiddle,
    registerOutput = false)
  val s1PackedProduct = SegmentedMultiplier.delay(
    Cat(s0.bits.hiHi(width - 1, 0), s0.bits.loLo(width - 1, 0)),
    adderLatency)
  val s1ChildElementMode = SegmentedMultiplier.delay(s0.bits.childElementMode, adderLatency)

  val output = Wire(Valid(new SegmentedMultiplierRecombineOutput(width)))
  output.valid := recombineAdder.io.output.valid
  output.bits.product := Mux(
    s1ChildElementMode,
    s1PackedProduct,
    recombineAdder.io.output.bits)

  io.output := ValidBuffer(output, registerOutput)
}

object SegmentedMultiplierRecombineAdder {
  def latency(
      registerCarrySaveOutput: Boolean,
      registerFinalAdderMiddle: Boolean,
      registerOutput: Boolean): Int = {
    (if (registerCarrySaveOutput) 1 else 0) +
      (if (registerFinalAdderMiddle) 1 else 0) +
      (if (registerOutput) 1 else 0)
  }
}

object SegmentedMultiplierRecombine {
  def latency(
      registerInput: Boolean,
      registerCarrySaveOutput: Boolean,
      registerFinalAdderMiddle: Boolean,
      registerOutput: Boolean): Int = {
    (if (registerInput) 1 else 0) +
      SegmentedMultiplierRecombineAdder.latency(
        registerCarrySaveOutput = registerCarrySaveOutput,
        registerFinalAdderMiddle = registerFinalAdderMiddle,
        registerOutput = false) +
      (if (registerOutput) 1 else 0)
  }
}
