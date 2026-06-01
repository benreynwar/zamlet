package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.{ElementWidth, WidthFormat, WidthHelpers, ZamletParams}

class LocalExecErrors extends Bundle {
  val unsupportedOpcode = Bool()
  val alu = new JamletAluErrors()
}

class LocalExec(params: ZamletParams) extends Module {
  val io = IO(new Bundle {
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
  })

  val alu = Module(new JamletAlu(params))

  val s0Base = io.kinstrIn.bits.kinstr.asTypeOf(new LocalKInstrBase(params))
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
  val s1Param0 = RegNext(io.kinstrIn.bits.param0)
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
  val s1SimpleEndIndex = RegNext(Mux(s0IsLoadSimple, s0LoadSimpleInstr.endIndex, s0StoreSimpleInstr.endIndex))
  val s1SimpleMaskEnabled = RegNext(Mux(s0IsLoadSimple, s0LoadSimpleInstr.maskEnabled, s0StoreSimpleInstr.maskEnabled))

  val s1AluEw = RegNext(s0BinaryInstr.ew)
  val s1AluEndIndex = RegNext(s0BinaryInstr.endIndex)
  val s1AluSignedA = RegNext(s0BinaryInstr.isSignedA)
  val s1AluSignedB = RegNext(s0BinaryInstr.isSignedB)
  val s1AluUseUpper = RegNext(s0BinaryInstr.useUpper)
  val s1AluMaskEnabled = RegNext(s0BinaryInstr.maskEnabled)

  val s1RfA = io.rfReadAResp.bits.readData
  val s1RfB = io.rfReadBResp.bits.readData
  val s1RfMask = io.rfReadMaskResp.bits.readData

  val s1MaskWord = Mux(
    (s1IsAlu && s1AluMaskEnabled) || ((s1IsLoadSimple || s1IsStoreSimple) && s1SimpleMaskEnabled),
    s1RfMask,
    Fill(params.wordWidth, true.B))

  def expandByteMask(byteMask: UInt): UInt = {
    VecInit((0 until params.wordBytes).map { i => Fill(8, byteMask(i)) }).asUInt
  }

  val s1LoadImmByteMaskExpanded = (s1LoadImmByteMask << (s1LoadImmSection << 2.U))(
    params.wordBytes - 1, 0)
  val s1LoadImmWriteData = (s1LoadImmData.asTypeOf(UInt(params.wordWidth.W)) << (s1LoadImmSection << 5.U))
  val s1LoadImmBitMask = expandByteMask(s1LoadImmByteMaskExpanded)

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

  val s1SimpleMask = elementBitMask(s1SimpleEw, s1Wf, s1Param0, s1SimpleEndIndex, s1MaskWord, s1LaneIndex)
  val s1SramAddress = (s1CacheSlot * params.cacheSlotWords.U) + s1SimpleSramWordOffset

  io.sramReq.valid := s1Valid && (s1IsLoadSimple || s1IsStoreSimple)
  io.sramReq.bits.address := s1SramAddress
  io.sramReq.bits.isWrite := s1IsStoreSimple
  io.sramReq.bits.data := s1RfA
  io.sramReq.bits.writeMask := Mux(s1IsStoreSimple, s1SimpleMask, DontCare)

  val s1AluOp = Wire(JamletAluOp())
  s1AluOp := JamletAluOp.MulLow
  when(s1Opcode === KInstrOpcode.Add) {
    s1AluOp := JamletAluOp.Add
  }.elsewhen(s1Opcode === KInstrOpcode.Sub) {
    s1AluOp := JamletAluOp.Sub
  }.elsewhen(s1Opcode === KInstrOpcode.MulHigh) {
    s1AluOp := JamletAluOp.MulHigh
  }

  alu.io.input.valid := s1Valid && s1IsAlu
  alu.io.input.bits.inA := s1RfA
  alu.io.input.bits.inB := s1RfB
  alu.io.input.bits.inM := s1MaskWord
  alu.io.input.bits.ew := s1AluEw
  alu.io.input.bits.wf := s1Wf
  alu.io.input.bits.startIndex := s1Param0(alu.io.input.bits.startIndex.getWidth - 1, 0)
  alu.io.input.bits.endIndex := s1AluEndIndex
  alu.io.input.bits.laneIndex := s1LaneIndex
  alu.io.input.bits.isSignedA := s1AluSignedA
  alu.io.input.bits.isSignedB := s1AluSignedB
  alu.io.input.bits.op := s1AluOp
  alu.io.input.bits.useUpper := s1AluUseUpper

  val latency = alu.outputLatency
  val loadImmWbValid = ShiftRegister(s1Valid && s1IsLoadImm, latency)
  val loadImmWbAddr = ShiftRegister(s1LoadImmRfAddr, latency)
  val loadImmWbData = ShiftRegister(s1LoadImmWriteData, latency)
  val loadImmWbMask = ShiftRegister(s1LoadImmBitMask, latency)

  val loadSimpleWbValid = ShiftRegister(s1Valid && s1IsLoadSimple, latency)
  val loadSimpleWbAddr = ShiftRegister(s1SimpleRfAddr, latency)
  val sramResponseLatency = params.sramParams.localResponseLatency
  require(latency >= sramResponseLatency,
    s"LocalExec load-simple writeback latency $latency is shorter than SRAM local response latency $sramResponseLatency")
  val loadSimpleWbData = if (latency == sramResponseLatency) {
    io.sramResp.bits
  } else {
    ShiftRegister(io.sramResp.bits, latency - sramResponseLatency)
  }
  val loadSimpleWbMask = ShiftRegister(s1SimpleMask, latency)

  val aluWbAddr = ShiftRegister(s1DstReg, latency)

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
