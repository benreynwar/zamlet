package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.maths.{SegmentedMultiplier, SegmentedPrefixAdder}
import zamlet.{ElementWidth, WidthFormat, WidthHelpers, ZamletParams}

object JamletAluOp extends ChiselEnum {
  val MulLow = Value(0.U)
  val MulHigh = Value(1.U)
  val Add = Value(2.U)
  val Sub = Value(3.U)
}

class JamletALUInput(params: ZamletParams) extends Bundle {
  val inA = params.word()
  val inB = params.word()
  val inM = params.word()
  val ew = ElementWidth()
  val wf = WidthFormat()
  val startIndex = UInt((params.log2JInL + params.log2WordBytes).W)
  val endIndex = UInt((params.log2JInL + params.log2WordBytes + 1).W)
  val laneIndex = UInt(params.log2JInL.W)
  val isSignedA = Bool()
  val isSignedB = Bool()
  val op = JamletAluOp()
  // Whether to use the lower half or upper half of inputs.
  // Will only be used if we are widening and can only
  // process half the input words.
  val useUpper = Bool()
}

class JamletAluErrors extends Bundle {
  val unsupportedEw = Bool()
  val unsupportedWf = Bool()
  val unsupportedEwWfRatio = Bool()
}

class JamletAluOutput(params: ZamletParams) extends Bundle {
  // One enable bit per result bit.
  val mask = params.word()
  val data = params.word()
}

class JamletAluIO(params: ZamletParams) extends Bundle {
  val input = Flipped(Valid(new JamletALUInput(params)))
  val output = Output(Valid(new JamletAluOutput(params)))
  val errors = Output(new JamletAluErrors())
}

class JamletAlu(params: ZamletParams) extends Module {
  require(params.wordWidth == 64, "JamletAlu currently uses 64-bit word units")

  val io = IO(new JamletAluIO(params))

  // For each element we need to work out whether it's masked and whether the element is
  // within bounds.


  // Add errors bundle with an error wire for unsupported ew.
  // error wire for wf < ew
  val input = io.input.bits

  val ewLogBits = WidthHelpers.ewLog2Bits(input.ew)
  val wfLogBits = WidthHelpers.wfLog2Bits(input.wf)
  val ewSupported = input.ew >= ElementWidth.ew8 && input.ew <= ElementWidth.ew64
  val wfSupported = input.wf >= WidthFormat.wf8
  val layoutSupported = wfLogBits >= ewLogBits
  val ewLogBytes = ewLogBits - 3.U
  val indexWidth = input.endIndex.getWidth
  val elementsPerWfLog2 = Mux(wfLogBits >= ewLogBits, wfLogBits - ewLogBits, 0.U)
  val elementsPerWf = (1.U(indexWidth.W) << elementsPerWfLog2)(indexWidth - 1, 0)
  val wfElementStride = elementsPerWf * params.jInL.U(indexWidth.W)

  val elementWidthLog2 = ewLogBits

  val mul = Module(new SegmentedMultiplier(params.wordWidth))
  val add = Module(new SegmentedPrefixAdder(
    params.wordWidth,
    registerInput = false,
    registerOutput = true))
  val outputLatency = JamletAlu.outputLatency(params)
  require(outputLatency >= add.latency, "JamletAlu assumes multiplier latency is at least adder latency")

  mul.io.input.valid := io.input.valid
  mul.io.input.bits.a := input.inA
  mul.io.input.bits.b := input.inB
  mul.io.input.bits.signedA := input.isSignedA
  mul.io.input.bits.signedB := input.isSignedB
  mul.io.input.bits.elementWidthLog2 := elementWidthLog2

  add.io.input.valid := io.input.valid
  add.io.input.bits.a := input.inA
  add.io.input.bits.b := input.inB
  add.io.input.bits.subtract := input.op === JamletAluOp.Sub
  add.io.input.bits.elementWidthLog2 := elementWidthLog2


  val elementByteMask = Wire(Vec(params.wordBytes, Bool()))
  for (byte <- 0 until params.wordBytes) {
    val localElementSlot = (byte.U(params.log2WordBytes.W) >> ewLogBytes)(params.log2WordBytes - 1, 0)
    val wfGroup = localElementSlot >> elementsPerWfLog2
    val elementInWf = localElementSlot - (wfGroup << elementsPerWfLog2)
    val elementIndex =
      input.laneIndex.asTypeOf(UInt(indexWidth.W)) +
      (wfGroup.asTypeOf(UInt(indexWidth.W)) * wfElementStride) +
      elementInWf.asTypeOf(UInt(indexWidth.W))
    val inBounds = elementIndex >= input.startIndex && elementIndex < input.endIndex
    val maskIndex = localElementSlot.asTypeOf(UInt(log2Ceil(params.wordWidth).W))
    val maskBit = input.inM(maskIndex)
    elementByteMask(byte) := inBounds && maskBit
  }

  val outputEw = ShiftRegister(input.ew, outputLatency)
  val products = mul.io.output.bits.product
  val mulLow = MuxLookup(outputEw.asUInt, products(63, 0))(Seq(
    ElementWidth.ew8.asUInt -> VecInit(products.asTypeOf(Vec(8, UInt(16.W))).map(_(7, 0))).asUInt,
    ElementWidth.ew16.asUInt -> VecInit(products.asTypeOf(Vec(4, UInt(32.W))).map(_(15, 0))).asUInt,
    ElementWidth.ew32.asUInt -> VecInit(products.asTypeOf(Vec(2, UInt(64.W))).map(_(31, 0))).asUInt,
    ElementWidth.ew64.asUInt -> products(63, 0),
  ))
  val mulHigh = MuxLookup(outputEw.asUInt, products(127, 64))(Seq(
    ElementWidth.ew8.asUInt -> VecInit(products.asTypeOf(Vec(8, UInt(16.W))).map(_(15, 8))).asUInt,
    ElementWidth.ew16.asUInt -> VecInit(products.asTypeOf(Vec(4, UInt(32.W))).map(_(31, 16))).asUInt,
    ElementWidth.ew32.asUInt -> VecInit(products.asTypeOf(Vec(2, UInt(64.W))).map(_(63, 32))).asUInt,
    ElementWidth.ew64.asUInt -> products(127, 64),
  ))
  val op = ShiftRegister(input.op, outputLatency)
  val mulData = Mux(op === JamletAluOp.MulHigh, mulHigh, mulLow)
  val addData = ShiftRegister(add.io.output.bits.sum, outputLatency - add.latency)

  io.output.bits.data := Mux(op === JamletAluOp.Add || op === JamletAluOp.Sub, addData, mulData)

  val bitMask = VecInit(elementByteMask.map(Fill(8, _))).asUInt
  val activeByteMask = Mux(io.input.valid && ewSupported && wfSupported && layoutSupported,
    bitMask, 0.U)

  io.output.valid := ShiftRegister(io.input.valid, outputLatency)
  io.output.bits.mask := ShiftRegister(activeByteMask, outputLatency)
  val errors = Wire(new JamletAluErrors())
  errors.unsupportedEw := io.input.valid && !ewSupported
  errors.unsupportedWf := io.input.valid && !wfSupported
  errors.unsupportedEwWfRatio := io.input.valid && !layoutSupported
  io.errors := RegNext(errors)
}

object JamletAlu {
  def outputLatency(params: ZamletParams): Int = {
    SegmentedMultiplier.latency(
      params.wordWidth,
      minWidth = 8,
      registerInput = true,
      registerLeafInput = true,
      recombineBufferMinWidth = 32,
      registerOutput = true)
  }
}

object JamletAluGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> JamletAlu <zamletParamsFileName>")
      null
    } else {
      val params = ZamletParams.fromFile(args(0))
      new JamletAlu(params)
    }
  }
}

object JamletAluMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  JamletAluGenerator.generate(args(0), Seq(args(1)))
}
