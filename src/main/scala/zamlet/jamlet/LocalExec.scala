package zamlet.jamlet

import chisel3._
import chisel3.experimental.ExtModule
import chisel3.util._
import zamlet.{ElementWidth, WidthFormat, WidthHelpers, ZamletParams}
import zamlet.utils.ValidBuffer

class LocalExecErrors extends Bundle {
  val unsupportedOpcode = Bool()
  val alu = new JamletAluErrors()
}

class LocalExecIO(params: ZamletParams) extends Bundle {
  val laneIndex = Input(UInt(params.log2JInL.W))

  val kinstrIn = Flipped(Valid(new KinstrWithParams(params)))

  val rfReadAReq = Valid(new RfReq(params))
  val rfReadAResp = Flipped(Valid(new RfResp(params)))
  val rfReadBReq = Valid(new RfReq(params))
  val rfReadBResp = Flipped(Valid(new RfResp(params)))
  val rfReadMaskReq = Valid(new RfReq(params))
  val rfReadMaskResp = Flipped(Valid(new RfResp(params)))
  val rfWriteReq = Valid(new RfReq(params))

  val sramReq = Valid(new SramRequest(params))
  val sramResp = Flipped(Valid(params.word()))

  val errors = Output(new LocalExecErrors())
}

class LocalExecStage(params: ZamletParams) extends Bundle {
  val isAlu = Bool()
  val isLoadImm = Bool()
  val isLoadSimple = Bool()
  val isStoreSimple = Bool()
  val opcode = KInstrOpcode()
  val startIndex = params.elementIndex()
  val endIndex = UInt(params.endElementIndexWidth.W)
  val cacheSlot = params.cacheSlot()
  val laneIndex = UInt(params.log2JInL.W)
  val wf = WidthFormat()

  val dstReg = params.rfAddr()
  val loadImmRfAddr = params.rfAddr()
  val loadImmSection = UInt(log2Ceil(params.wordBytes / 4).W)
  val loadImmByteMask = UInt(4.W)
  val loadImmData = UInt(32.W)

  val simpleRfAddr = params.rfAddr()
  val simpleSramWordOffset = UInt(params.log2CacheSlotWordsPerJamlet.W)
  val simpleEw = ElementWidth()
  val simpleMaskEnabled = Bool()

  val aluEw = ElementWidth()
  val aluSignedA = Bool()
  val aluSignedB = Bool()
  val aluUseUpper = Bool()
  val aluMaskEnabled = Bool()

  val rfA = params.word()
  val rfB = params.word()
  val rfMask = params.word()
}

class LocalExec(params: ZamletParams) extends Module {
  val io = IO(new LocalExecIO(params))

  val alu = Module(new JamletAlu(params))

  val s0Base = io.kinstrIn.bits.kinstr.asTypeOf(new KInstrBase(params))
  val s0BinaryInstr = io.kinstrIn.bits.kinstr.asTypeOf(new BinaryOpInstr(params))
  val s0LoadImmInstr = io.kinstrIn.bits.kinstr.asTypeOf(new LoadImmInstr(params))
  val s0LoadSimpleInstr = io.kinstrIn.bits.kinstr.asTypeOf(new LoadSimpleInstr(params))
  val s0StoreSimpleInstr = io.kinstrIn.bits.kinstr.asTypeOf(new StoreSimpleInstr(params))

  val s0Valid = io.kinstrIn.valid
  val s0IsAdd = s0Base.opcode === KInstrOpcode.Add
  val s0IsSub = s0Base.opcode === KInstrOpcode.Sub
  val s0IsMul = s0Base.opcode === KInstrOpcode.Mul
  val s0IsMulHigh = s0Base.opcode === KInstrOpcode.MulHigh
  val s0IsAlu = s0IsAdd || s0IsSub || s0IsMul || s0IsMulHigh
  val s0IsLoadImm = s0Base.opcode === KInstrOpcode.LoadImm
  val s0IsLoadSimple = s0Base.opcode === KInstrOpcode.LoadSimple
  val s0IsStoreSimple = s0Base.opcode === KInstrOpcode.StoreSimple
  val s0SupportedOpcode = s0IsAlu || s0IsLoadImm || s0IsLoadSimple || s0IsStoreSimple

  def setReadDefaults(req: ValidIO[RfReq]): Unit = {
    req.valid := false.B
    req.bits.addr := 0.U
    req.bits.isWrite := false.B
    req.bits.writeData := DontCare
    req.bits.writeMask := DontCare
  }

  setReadDefaults(io.rfReadAReq)
  setReadDefaults(io.rfReadBReq)
  setReadDefaults(io.rfReadMaskReq)

  io.rfReadAReq.valid := s0Valid && (s0IsAlu || s0IsStoreSimple)
  io.rfReadAReq.bits.addr := Mux(s0IsAlu, s0BinaryInstr.srcAReg,
    s0StoreSimpleInstr.rfAddr)

  io.rfReadBReq.valid := s0Valid && s0IsAlu
  io.rfReadBReq.bits.addr := s0BinaryInstr.srcBReg

  val s0MaskEnabled = Mux(s0IsAlu, s0BinaryInstr.maskEnabled,
    Mux(s0IsLoadSimple, s0LoadSimpleInstr.maskEnabled,
      Mux(s0IsStoreSimple, s0StoreSimpleInstr.maskEnabled, false.B)))
  io.rfReadMaskReq.valid := s0Valid && s0MaskEnabled
  io.rfReadMaskReq.bits.addr := Mux(s0IsAlu, s0BinaryInstr.maskReg,
    Mux(s0IsLoadSimple, s0LoadSimpleInstr.maskReg, s0StoreSimpleInstr.maskReg))

  val s1Valid = RegNext(s0Valid, false.B)
  val s1IsAlu = RegNext(s0IsAlu, false.B)
  val s1IsLoadImm = RegNext(s0IsLoadImm, false.B)
  val s1IsLoadSimple = RegNext(s0IsLoadSimple, false.B)
  val s1IsStoreSimple = RegNext(s0IsStoreSimple, false.B)
  val s1Opcode = RegNext(s0Base.opcode)
  val s1StartIndex = RegNext(io.kinstrIn.bits.param1(params.elementIndexWidth - 1, 0))
  val s1EndIndex = RegNext(io.kinstrIn.bits.param2(params.endElementIndexWidth - 1, 0))
  val s1CacheSlot = RegNext(io.kinstrIn.bits.cacheSlot)
  val s1LaneIndex = RegNext(io.laneIndex)
  val s1Wf = RegNext(io.kinstrIn.bits.ordering.wf)

  val s1DstReg = RegNext(s0BinaryInstr.dstReg)
  val s1LoadImmRfAddr = RegNext(s0LoadImmInstr.rfAddr)
  val s1LoadImmSection = RegNext(s0LoadImmInstr.section)
  val s1LoadImmByteMask = RegNext(s0LoadImmInstr.byteMask)
  val s1LoadImmData = RegNext(s0LoadImmInstr.data)

  val s1SimpleRfAddr = RegNext(Mux(s0IsLoadSimple, s0LoadSimpleInstr.rfAddr, s0StoreSimpleInstr.rfAddr))
  val s1SimpleSramWordOffset = RegNext(io.kinstrIn.bits.sramWordOffset)
  val s1SimpleEw = RegNext(Mux(s0IsLoadSimple, s0LoadSimpleInstr.ew, s0StoreSimpleInstr.ew))
  val s1SimpleMaskEnabled = RegNext(Mux(s0IsLoadSimple, s0LoadSimpleInstr.maskEnabled, s0StoreSimpleInstr.maskEnabled))

  val s1AluEw = RegNext(s0BinaryInstr.ew)
  val s1AluSignedA = RegNext(s0BinaryInstr.isSignedA)
  val s1AluSignedB = RegNext(s0BinaryInstr.isSignedB)
  val s1AluUseUpper = RegNext(s0BinaryInstr.useUpper)
  val s1AluMaskEnabled = RegNext(s0BinaryInstr.maskEnabled)

  val s1Out = Wire(Valid(new LocalExecStage(params)))
  s1Out.valid := s1Valid
  s1Out.bits.isAlu := s1IsAlu
  s1Out.bits.isLoadImm := s1IsLoadImm
  s1Out.bits.isLoadSimple := s1IsLoadSimple
  s1Out.bits.isStoreSimple := s1IsStoreSimple
  s1Out.bits.opcode := s1Opcode
  s1Out.bits.startIndex := s1StartIndex
  s1Out.bits.endIndex := s1EndIndex
  s1Out.bits.cacheSlot := s1CacheSlot
  s1Out.bits.laneIndex := s1LaneIndex
  s1Out.bits.wf := s1Wf
  s1Out.bits.dstReg := s1DstReg
  s1Out.bits.loadImmRfAddr := s1LoadImmRfAddr
  s1Out.bits.loadImmSection := s1LoadImmSection
  s1Out.bits.loadImmByteMask := s1LoadImmByteMask
  s1Out.bits.loadImmData := s1LoadImmData
  s1Out.bits.simpleRfAddr := s1SimpleRfAddr
  s1Out.bits.simpleSramWordOffset := s1SimpleSramWordOffset
  s1Out.bits.simpleEw := s1SimpleEw
  s1Out.bits.simpleMaskEnabled := s1SimpleMaskEnabled
  s1Out.bits.aluEw := s1AluEw
  s1Out.bits.aluSignedA := s1AluSignedA
  s1Out.bits.aluSignedB := s1AluSignedB
  s1Out.bits.aluUseUpper := s1AluUseUpper
  s1Out.bits.aluMaskEnabled := s1AluMaskEnabled
  s1Out.bits.rfA := io.rfReadAResp.bits.readData
  s1Out.bits.rfB := io.rfReadBResp.bits.readData
  s1Out.bits.rfMask := io.rfReadMaskResp.bits.readData

  val s2In = ValidBuffer(s1Out, params.localExecParams.s12Buffer)

  val s2MaskWord = Mux(
    (s2In.bits.isAlu && s2In.bits.aluMaskEnabled) ||
      ((s2In.bits.isLoadSimple || s2In.bits.isStoreSimple) && s2In.bits.simpleMaskEnabled),
    s2In.bits.rfMask,
    Fill(params.wordWidth, true.B))

  def expandByteMask(byteMask: UInt): UInt = {
    VecInit((0 until params.wordBytes).map { i => Fill(8, byteMask(i)) }).asUInt
  }

  val s2LoadImmByteMaskExpanded =
    (s2In.bits.loadImmByteMask << (s2In.bits.loadImmSection << 2.U))(
    params.wordBytes - 1, 0)
  val s2LoadImmWriteData =
    s2In.bits.loadImmData.asTypeOf(UInt(params.wordWidth.W)) << (s2In.bits.loadImmSection << 5.U)
  val s2LoadImmBitMask = expandByteMask(s2LoadImmByteMaskExpanded)

  def elementBitMask(
    ew: ElementWidth.Type,
    wf: WidthFormat.Type,
    startIndex: UInt,
    endIndex: UInt,
    maskWord: UInt,
    laneIndex: UInt
  ): UInt = {
    val ewLogBits = WidthHelpers.ewLog2Bits(ew)
    val wfLogBits = WidthHelpers.wfLog2Bits(wf)
    val ewLogBytes = ewLogBits - 3.U
    val indexWidth = params.log2JInL + params.log2WordBytes + 1
    val elementsPerWfLog2 = Mux(wfLogBits >= ewLogBits, wfLogBits - ewLogBits, 0.U)
    val elementsPerWf = (1.U(indexWidth.W) << elementsPerWfLog2)(indexWidth - 1, 0)
    val wfElementStride = elementsPerWf * params.jInL.U(indexWidth.W)
    val byteMask = Wire(Vec(params.wordBytes, Bool()))
    for (byte <- 0 until params.wordBytes) {
      val localElementSlot = (byte.U(params.log2WordBytes.W) >> ewLogBytes)(params.log2WordBytes - 1, 0)
      val wfGroup = localElementSlot >> elementsPerWfLog2
      val elementInWf = localElementSlot - (wfGroup << elementsPerWfLog2)
      val maskIndex = localElementSlot.asTypeOf(UInt(log2Ceil(params.wordWidth).W))
      val elementIndex = laneIndex.asTypeOf(UInt(indexWidth.W)) +
        wfGroup.asTypeOf(UInt(indexWidth.W)) * wfElementStride +
        elementInWf.asTypeOf(UInt(indexWidth.W))
      byteMask(byte) := elementIndex >= startIndex && elementIndex < endIndex && maskWord(maskIndex)
    }
    VecInit(byteMask.map(Fill(8, _))).asUInt
  }

  val s2SimpleMask = elementBitMask(
    s2In.bits.simpleEw,
    s2In.bits.wf,
    s2In.bits.startIndex,
    s2In.bits.endIndex,
    s2MaskWord,
    s2In.bits.laneIndex)
  val s2SramAddress =
    (s2In.bits.cacheSlot * params.cacheSlotWordsPerJamlet.U) + s2In.bits.simpleSramWordOffset

  val sramReq0 = Wire(Valid(new SramRequest(params)))
  sramReq0.valid := s2In.valid && (s2In.bits.isLoadSimple || s2In.bits.isStoreSimple)
  sramReq0.bits.address := s2SramAddress
  sramReq0.bits.isWrite := s2In.bits.isStoreSimple
  sramReq0.bits.data := s2In.bits.rfA
  sramReq0.bits.writeMask := Mux(s2In.bits.isStoreSimple, s2SimpleMask, DontCare)
  io.sramReq := ValidBuffer(sramReq0, params.localExecParams.sramReqBuffer)

  val s2AluOp = Wire(JamletAluOp())
  s2AluOp := JamletAluOp.MulLow
  when(s2In.bits.opcode === KInstrOpcode.Add) {
    s2AluOp := JamletAluOp.Add
  }.elsewhen(s2In.bits.opcode === KInstrOpcode.Sub) {
    s2AluOp := JamletAluOp.Sub
  }.elsewhen(s2In.bits.opcode === KInstrOpcode.MulHigh) {
    s2AluOp := JamletAluOp.MulHigh
  }

  alu.io.input.valid := s2In.valid && s2In.bits.isAlu
  alu.io.input.bits.inA := s2In.bits.rfA
  alu.io.input.bits.inB := s2In.bits.rfB
  alu.io.input.bits.inM := s2MaskWord
  alu.io.input.bits.ew := s2In.bits.aluEw
  alu.io.input.bits.wf := s2In.bits.wf
  alu.io.input.bits.startIndex := s2In.bits.startIndex(alu.io.input.bits.startIndex.getWidth - 1, 0)
  alu.io.input.bits.endIndex := s2In.bits.endIndex
  alu.io.input.bits.laneIndex := s2In.bits.laneIndex
  alu.io.input.bits.isSignedA := s2In.bits.aluSignedA
  alu.io.input.bits.isSignedB := s2In.bits.aluSignedB
  alu.io.input.bits.op := s2AluOp
  alu.io.input.bits.useUpper := s2In.bits.aluUseUpper

  val latency = alu.outputLatency
  val loadImmWbValid = ShiftRegister(s2In.valid && s2In.bits.isLoadImm, latency)
  val loadImmWbAddr = ShiftRegister(s2In.bits.loadImmRfAddr, latency)
  val loadImmWbData = ShiftRegister(s2LoadImmWriteData, latency)
  val loadImmWbMask = ShiftRegister(s2LoadImmBitMask, latency)

  val loadSimpleWbValid = ShiftRegister(s2In.valid && s2In.bits.isLoadSimple, latency)
  val loadSimpleWbAddr = ShiftRegister(s2In.bits.simpleRfAddr, latency)
  val sramResponseLatency = params.sramParams.localResponseLatency +
    (if (params.localExecParams.sramReqBuffer) 1 else 0)
  require(latency >= sramResponseLatency,
    s"LocalExec load-simple writeback latency $latency is shorter than SRAM local response latency $sramResponseLatency")
  val loadSimpleWbData = if (latency == sramResponseLatency) {
    io.sramResp.bits
  } else {
    ShiftRegister(io.sramResp.bits, latency - sramResponseLatency)
  }
  val loadSimpleWbMask = ShiftRegister(s2SimpleMask, latency)

  val aluWbAddr = ShiftRegister(s2In.bits.dstReg, latency)

  io.rfWriteReq.valid := alu.io.output.valid || loadImmWbValid || loadSimpleWbValid
  io.rfWriteReq.bits.addr := Mux(alu.io.output.valid, aluWbAddr,
    Mux(loadSimpleWbValid, loadSimpleWbAddr, loadImmWbAddr))
  io.rfWriteReq.bits.isWrite := true.B
  io.rfWriteReq.bits.writeData := Mux(alu.io.output.valid, alu.io.output.bits.data,
    Mux(loadSimpleWbValid, loadSimpleWbData, loadImmWbData))
  io.rfWriteReq.bits.writeMask := Mux(alu.io.output.valid, alu.io.output.bits.mask,
    Mux(loadSimpleWbValid, loadSimpleWbMask, loadImmWbMask))

  io.errors.unsupportedOpcode := RegNext(s0Valid && !s0SupportedOpcode, false.B)
  io.errors.alu := alu.io.errors
}

class LocalExecHardMacro(params: ZamletParams) extends ExtModule {
  override val desiredName = "LocalExec"

  val clock = IO(Input(Clock()))
  val reset = IO(Input(Bool()))
  val io = IO(new LocalExecIO(params))
}

object LocalExec {
  // Cycles from kinstrIn.valid to the LocalExec RF read request ports.
  // Reads are currently driven directly from the input/s0 stage.
  def inputToReadPortLatency(params: ZamletParams): Int = {
    0
  }

  // Cycles from kinstrIn.valid to rfWriteReq.valid for LocalExec operations
  // that write the register file.
  def inputToWritePortLatency(params: ZamletParams): Int = {
    // kinstrIn is the s0 stage; RF/SRAM responses are consumed in s1.
    val s0ToS1Latency = 1
    val s1ToS2Latency = if (params.localExecParams.s12Buffer) 1 else 0
    s0ToS1Latency + s1ToS2Latency + JamletAlu.outputLatency(params)
  }

  // Minimum cycle separation from a producer kinstrIn.valid to a dependent
  // consumer kinstrIn.valid so the consumer RF read observes the producer write.
  def inputToDependentInputMinSeparation(params: ZamletParams): Int = {
    inputToWritePortLatency(params) +
      RfSlice.writeToReadSameAddressMinSeparation(params) -
      inputToReadPortLatency(params)
  }
}

/** Generator for LocalExec module */
object LocalExecGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> LocalExec <zamletParamsFileName>")
      null
    } else {
      val params = ZamletParams.fromFile(args(0))
      new LocalExec(params)
    }
  }
}

object LocalExecMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  LocalExecGenerator.generate(args(0), Seq(args(1)))
}
