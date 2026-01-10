package zamlet.lamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams
import zamlet.jamlet.{J2JInstr, EwCode, WordOrder, KInstr, KInstrOpcode, WriteParamInstr,
                       StoreScalarInstr}
import zamlet.utils.{DoubleBuffer, ValidBuffer}

/**
 * IssueUnit decodes RISC-V vector instructions, performs TLB lookup, and generates kinstrs.
 *
 * First draft scope: Only unit-stride vle/vse, no pipeline stages.
 *
 * State machine: IDLE -> TLB_REQ -> TLB_WAIT -> DISPATCH -> IDLE
 *
 * Interfaces:
 * - ex: Instruction input from scalar core (valid/ready handshake)
 * - tlb: TLB request/response interface
 * - toIdentTracker: Kinstr output (without ident - IdentTracker fills it)
 * - com: Completion/retire signals back to scalar core
 */

/** Instruction data from scalar core */
class IssueUnitExData extends Bundle {
  val inst = UInt(32.W)
  val rs1Data = UInt(64.W)
  val vl = UInt(16.W)
  val vstart = UInt(16.W)
  val vsew = UInt(3.W)
}

/** TLB request data */
class IssueUnitTlbReq extends Bundle {
  val vaddr = UInt(64.W)
  val cmd = UInt(5.W)
}

/** TLB response (active when request fires, active next cycle) */
class IssueUnitTlbResp extends Bundle {
  val paddr = UInt(64.W)
  val miss = Bool()
  val pfLd = Bool()
  val pfSt = Bool()
  val aeLd = Bool()
  val aeSt = Bool()
}

/** Completion signals to scalar core */
class IssueUnitCom extends Bundle {
  val retireLate = Bool()
  val inst = UInt(32.W)
  val xcpt = Bool()
  val cause = UInt(64.W)
  val tval = UInt(64.W)
  val internalReplay = Bool()
}

class IssueUnit(params: LamletParams) extends Module {
  val bufParams = params.issueUnitParams
  val io = IO(new Bundle {
    /** Instruction input from scalar core */
    val ex = Flipped(Decoupled(new IssueUnitExData))

    /** TLB request interface */
    val tlbReq = Decoupled(new IssueUnitTlbReq)

    /** TLB response (active after request fires) */
    val tlbResp = Input(new IssueUnitTlbResp)

    /** Kinstr output to IdentTracker (ident field empty, filled by IdentTracker) */
    val toIdentTracker = Decoupled(new KinstrWithTarget(params))

    /** Scalar memory load request to ScalarLoadQueue */
    val scalarLoadReq = Decoupled(new ScalarLoadReq(params))

    /** Scalar load completion from ScalarLoadQueue */
    val scalarLoadComplete = Flipped(Valid(UInt(params.identWidth.W)))

    /** Scalar store completion from VpuToScalarMem */
    val scalarStoreComplete = Flipped(Valid(UInt(params.identWidth.W)))

    /** Store word count to VpuToScalarMem (how many words to expect) */
    val storeWordCount = Valid(new Bundle {
      val ident = UInt(params.identWidth.W)
      val nWords = UInt(16.W)
    })

    /** Completion signals to scalar core */
    val com = Output(new IssueUnitCom)

    /** Kill signal from scalar core */
    val kill = Input(Bool())
  })

  // Buffered interfaces
  val exBuffered = Wire(Flipped(Decoupled(new IssueUnitExData)))
  val tlbReqInternal = Wire(Decoupled(new IssueUnitTlbReq))
  val tlbRespBuffered = Wire(new IssueUnitTlbResp)
  val toIdentTrackerInternal = Wire(Decoupled(new KinstrWithTarget(params)))
  val comInternal = Wire(new IssueUnitCom)
  val killBuffered = Wire(Bool())

  // Apply input buffers
  if (bufParams.exForwardBuffer || bufParams.exBackwardBuffer) {
    val exBuf = Module(new DoubleBuffer(new IssueUnitExData,
      bufParams.exForwardBuffer, bufParams.exBackwardBuffer))
    exBuf.io.i <> io.ex
    exBuffered <> exBuf.io.o
  } else {
    exBuffered <> io.ex
  }

  if (bufParams.tlbRespInputReg) {
    tlbRespBuffered := RegNext(io.tlbResp)
  } else {
    tlbRespBuffered := io.tlbResp
  }

  if (bufParams.killInputReg) {
    killBuffered := RegNext(io.kill)
  } else {
    killBuffered := io.kill
  }

  // Apply output buffers
  if (bufParams.tlbReqForwardBuffer || bufParams.tlbReqBackwardBuffer) {
    io.tlbReq <> DoubleBuffer(tlbReqInternal,
      bufParams.tlbReqForwardBuffer, bufParams.tlbReqBackwardBuffer)
  } else {
    io.tlbReq <> tlbReqInternal
  }

  if (bufParams.toIdentTrackerForwardBuffer || bufParams.toIdentTrackerBackwardBuffer) {
    io.toIdentTracker <> DoubleBuffer(toIdentTrackerInternal,
      bufParams.toIdentTrackerForwardBuffer, bufParams.toIdentTrackerBackwardBuffer)
  } else {
    io.toIdentTracker <> toIdentTrackerInternal
  }

  if (bufParams.comOutputReg) {
    io.com := RegNext(comInternal)
  } else {
    io.com := comInternal
  }

  // State machine
  object State extends ChiselEnum {
    val Idle, TlbReq, TlbWait, DispatchLoad, WaitLoadComplete = Value
    val DispatchStoreWriteParam, DispatchStoreScalar, WaitStoreComplete = Value
  }
  import State._

  val state = RegInit(Idle)

  // Captured instruction fields
  val inst = Reg(UInt(32.W))
  val rs1Data = Reg(UInt(64.W))
  val vl = Reg(UInt(16.W))
  val vstart = Reg(UInt(16.W))
  val vsew = Reg(UInt(3.W))

  // TLB result
  val tlbPaddr = Reg(UInt(64.W))

  // Decode logic
  val opcode = inst(6, 0)
  val isVectorLoad = opcode === "b0000111".U
  val isVectorStore = opcode === "b0100111".U
  val mop = inst(27, 26)
  val isUnitStride = mop === 0.U
  val vm = inst(25)
  val isUnmasked = vm
  val vd = inst(11, 7)

  // Element width from instruction (for memory ops): bits [14:12]
  // 000=8, 101=16, 110=32, 111=64
  val widthField = inst(14, 12)
  val eewBits = MuxLookup(widthField, 8.U)(Seq(
    0.U -> 8.U,
    5.U -> 16.U,
    6.U -> 32.U,
    7.U -> 64.U
  ))

  // Convert SEW to EwCode
  def sewToEwCode(sew: UInt): EwCode.Type = {
    MuxLookup(sew, EwCode.Ew8)(Seq(
      0.U -> EwCode.Ew8,
      1.U -> EwCode.Ew16,
      2.U -> EwCode.Ew32,
      3.U -> EwCode.Ew64
    ))
  }

  // Convert bits to EwCode
  def bitsToEwCode(bits: UInt): EwCode.Type = {
    MuxLookup(bits, EwCode.Ew8)(Seq(
      8.U -> EwCode.Ew8,
      16.U -> EwCode.Ew16,
      32.U -> EwCode.Ew32,
      64.U -> EwCode.Ew64
    ))
  }

  // Generate kinstr (J2JInstr format)
  // Layout: opcode(6), cacheSlot, memWordOrder, rfWordOrder, memEw, rfEw, baseBitAddr,
  //         startIndex, nElementsIdx, reg
  val kinstr = Wire(new J2JInstr(params))
  kinstr.opcode := Mux(isVectorLoad, KInstrOpcode.LoadJ2J, KInstrOpcode.StoreJ2J)
  kinstr.cacheSlot := (tlbPaddr >> log2Ceil(params.cacheSlotWords * params.wordBytes).U)(
    params.cacheSlotWidth - 1, 0)
  kinstr.memWordOrder := WordOrder.Standard
  kinstr.rfWordOrder := WordOrder.Standard
  kinstr.memEw := bitsToEwCode(eewBits)
  kinstr.rfEw := sewToEwCode(vsew)
  // baseBitAddr: byte address within lamlet (page-aligned portion)
  kinstr.baseBitAddr := (tlbPaddr << 3.U)(log2Ceil(params.wordWidth * params.jInL) - 1, 0)
  kinstr.startIndex := vstart.pad(params.elementIndexWidth)
  kinstr.nElementsIdx := 0.U
  kinstr.reg := vd.pad(params.rfAddrWidth)

  // Default outputs
  exBuffered.ready := false.B
  tlbReqInternal.valid := false.B
  tlbReqInternal.bits.vaddr := rs1Data
  tlbReqInternal.bits.cmd := Mux(isVectorStore, 1.U, 0.U)
  toIdentTrackerInternal.valid := false.B
  toIdentTrackerInternal.bits.kinstr := 0.U
  toIdentTrackerInternal.bits.kIndex := 0.U
  toIdentTrackerInternal.bits.isBroadcast := true.B
  io.scalarLoadReq.valid := false.B
  io.scalarLoadReq.bits.paddr := tlbPaddr
  io.scalarLoadReq.bits.vd := vd.pad(params.rfAddrWidth)
  io.scalarLoadReq.bits.startIndex := vstart.pad(params.elementIndexWidth)
  io.scalarLoadReq.bits.nElements := vl
  io.scalarLoadReq.bits.instrIdent := 0.U
  io.storeWordCount.valid := false.B
  io.storeWordCount.bits.ident := 0.U
  io.storeWordCount.bits.nWords := vl
  comInternal.retireLate := false.B
  comInternal.inst := inst
  comInternal.xcpt := false.B
  comInternal.cause := 0.U
  comInternal.tval := 0.U
  comInternal.internalReplay := false.B

  // State machine
  switch(state) {
    is(Idle) {
      exBuffered.ready := true.B
      when(exBuffered.valid) {
        inst := exBuffered.bits.inst
        rs1Data := exBuffered.bits.rs1Data
        vl := exBuffered.bits.vl
        vstart := exBuffered.bits.vstart
        vsew := exBuffered.bits.vsew
        state := TlbReq
      }
    }

    is(TlbReq) {
      val canHandle = (isVectorLoad || isVectorStore) && isUnitStride && isUnmasked
      when(canHandle) {
        tlbReqInternal.valid := true.B
        tlbReqInternal.bits.vaddr := rs1Data
        when(tlbReqInternal.ready) {
          state := TlbWait
        }
      }.otherwise {
        comInternal.retireLate := true.B
        state := Idle
      }
    }

    is(TlbWait) {
      val hasXcpt = tlbRespBuffered.pfLd || tlbRespBuffered.pfSt ||
                    tlbRespBuffered.aeLd || tlbRespBuffered.aeSt

      when(tlbRespBuffered.miss) {
        comInternal.internalReplay := true.B
        state := Idle
      }.elsewhen(hasXcpt) {
        comInternal.retireLate := true.B
        comInternal.xcpt := true.B
        comInternal.cause := MuxCase(0.U, Seq(
          tlbRespBuffered.pfLd -> 13.U,
          tlbRespBuffered.pfSt -> 15.U,
          tlbRespBuffered.aeLd -> 5.U,
          tlbRespBuffered.aeSt -> 7.U
        ))
        comInternal.tval := rs1Data
        state := Idle
      }.otherwise {
        tlbPaddr := tlbRespBuffered.paddr
        when(isVectorLoad) {
          state := DispatchLoad
        }.elsewhen(isVectorStore) {
          state := DispatchStoreWriteParam
        }.otherwise {
          // Unknown instruction - just retire
          comInternal.retireLate := true.B
          state := Idle
        }
      }
    }

    is(DispatchLoad) {
      io.scalarLoadReq.valid := true.B
      when(io.scalarLoadReq.ready) {
        state := WaitLoadComplete
      }
    }

    is(WaitLoadComplete) {
      when(io.scalarLoadComplete.valid) {
        comInternal.retireLate := true.B
        state := Idle
      }
    }

    is(DispatchStoreWriteParam) {
      // Send WriteParam kinstr with paddr to param entry 0
      val writeParamKinstr = Wire(new WriteParamInstr)
      writeParamKinstr.opcode := KInstrOpcode.WriteParam
      writeParamKinstr.paramIdx := 0.U
      writeParamKinstr.data := tlbPaddr(params.memAddrWidth - 1, 0)
      writeParamKinstr.reserved := 0.U

      toIdentTrackerInternal.valid := true.B
      toIdentTrackerInternal.bits.kinstr := writeParamKinstr.asUInt
      toIdentTrackerInternal.bits.kIndex := 0.U
      toIdentTrackerInternal.bits.isBroadcast := true.B
      when(toIdentTrackerInternal.ready) {
        state := DispatchStoreScalar
      }
    }

    is(DispatchStoreScalar) {
      // Send StoreScalar kinstr referencing param entry 0
      val storeScalarKinstr = Wire(new StoreScalarInstr(params))
      storeScalarKinstr.opcode := KInstrOpcode.StoreScalar
      storeScalarKinstr.dataReg := vd.pad(params.rfAddrWidth)
      storeScalarKinstr.baseAddrIdx := 0.U
      storeScalarKinstr.startIndex := vstart
      storeScalarKinstr.nElements := vl
      storeScalarKinstr.reserved := 0.U

      toIdentTrackerInternal.valid := true.B
      toIdentTrackerInternal.bits.kinstr := storeScalarKinstr.asUInt
      toIdentTrackerInternal.bits.kIndex := 0.U
      toIdentTrackerInternal.bits.isBroadcast := true.B
      // Signal expected word count to VpuToScalarMem
      io.storeWordCount.valid := true.B
      io.storeWordCount.bits.nWords := vl
      when(toIdentTrackerInternal.ready) {
        state := WaitStoreComplete
      }
    }

    is(WaitStoreComplete) {
      when(io.scalarStoreComplete.valid) {
        comInternal.retireLate := true.B
        state := Idle
      }
    }
  }

  // Kill handling
  when(killBuffered && state =/= Idle) {
    state := Idle
  }
}

object IssueUnitGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = LamletParams.fromFile(args(0))
    new IssueUnit(params)
  }
}

object IssueUnitMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  IssueUnitGenerator.generate(outputDir, Seq(configFile))
}
