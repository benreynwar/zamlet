package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.{LaneOrder, Ordering, WidthFormat, ZamletParams}
import zamlet.jamlet.{BinaryOpInstr, IndexedInstr, KInstr, KInstrBase,
                       KInstrOpcode, KinstrWithParams, LoadImmInstr, MemoryKInstrBase,
                       LoadSimpleInstr, StoreScalarInstr, StoreSimpleInstr,
                       WriteParamInstr}
import zamlet.utils.{DoubleBuffer, ValidBuffer}

object RsIssueKind extends ChiselEnum {
  val SideEffect, LocalOne, LocalBroadcast, CacheLocal, KteTransfer, KteSync, Unsupported = Value
}

class RsIssuePayload(params: ZamletParams) extends Bundle {
  val kind = RsIssueKind()
  val kinstr = new KinstrWithParams(params)
  val targetValid = Bool()
  val targetJInK = UInt(log2Ceil(params.jInK).W)
  val cacheLineAddr = params.cacheLineAddr()
  val cacheSlot = params.cacheSlot()
  val cacheSlotPresent = Bool()
  val willWrite = Bool()
  val rfUses = Vec(4, new RfUse(params))
}

class RsLocalInFlight(params: ZamletParams) extends Bundle {
  val valid = Bool()
  val rfRelease = new RfRelease(params)
  val mem = Valid(new KteMemFootprint(params))
}

class ReservationStationErrors extends Bundle {
  val binarySrcLaneOrderMismatch = Bool()
}

class ReservationStationIO(params: ZamletParams) extends Bundle {
  val renamedIn = Flipped(Decoupled(UInt(KInstr.width.W)))

  val immediateKinstr = Vec(params.jInK, Valid(new KinstrWithParams(params)))

  val kteIssue = Decoupled(new KteIssueReq(params))

  val kteConflictMem = Output(Valid(new KteMemFootprint(params)))
  val kteConflict = Input(Bool())

  val kceAllocSlotReq = Decoupled(new KceAllocSlotReq(params))
  val kceAllocSlotResp = Flipped(Decoupled(new KceAllocSlotResp(params)))

  val kteRfRelease = Flipped(Decoupled(new RfRelease(params)))

  val errors = Output(new ReservationStationErrors)
}

class ReservationStation(params: ZamletParams) extends Module {
  val io = IO(new ReservationStationIO(params))
  private val rsp = params.reservationStationParams

  val paramMemNumEntries = 1 << params.log2NParams
  val paramMemNext = Wire(Vec(paramMemNumEntries, UInt(params.memAddrWidth.W)))
  val paramMem = RegEnable(paramMemNext, VecInit(Seq.fill(paramMemNumEntries)(0.U(params.memAddrWidth.W))), true.B)
  paramMemNext := paramMem

  val rfBusyNext = Wire(Vec(params.rfSliceWords, Bool()))
  val rfBusy = RegEnable(rfBusyNext, VecInit(Seq.fill(params.rfSliceWords)(false.B)), true.B)
  rfBusyNext := rfBusy

  val rfOrderingInit = Wire(Vec(params.rfSliceWords, new Ordering))
  for (rfAddr <- 0 until params.rfSliceWords) {
    rfOrderingInit(rfAddr).wf := WidthFormat.wf64
    rfOrderingInit(rfAddr).laneOrder := LaneOrder.ROW_MAJOR
  }
  val rfOrderingNext = Wire(Vec(params.rfSliceWords, new Ordering))
  val rfOrdering = RegEnable(rfOrderingNext, rfOrderingInit, true.B)
  rfOrderingNext := rfOrdering

  def ewAsWf(ew: zamlet.ElementWidth.Type): WidthFormat.Type = {
    ew.asUInt.asTypeOf(WidthFormat())
  }

  val immediateKinstr = Wire(Vec(params.jInK, Valid(new KinstrWithParams(params))))
  for (jInK <- 0 until params.jInK) {
    immediateKinstr(jInK).valid := false.B
    immediateKinstr(jInK).bits := DontCare
    io.immediateKinstr(jInK) := ValidBuffer(immediateKinstr(jInK), rsp.immediateKinstrBuffer)
  }

  val kteIssue = Wire(Decoupled(new KteIssueReq(params)))
  val kteIssueBuffer =
    Module(new DoubleBuffer(new KteIssueReq(params), rsp.kteIssueFB, rsp.kteIssueBB))
  kteIssueBuffer.io.i <> kteIssue
  io.kteIssue <> kteIssueBuffer.io.o
  kteIssue.valid := false.B
  kteIssue.bits := DontCare

  val kceAllocSlotReq = Wire(Decoupled(new KceAllocSlotReq(params)))
  io.kceAllocSlotReq <> DoubleBuffer(kceAllocSlotReq, rsp.kceClaimSlotReqFB, rsp.kceClaimSlotReqBB)
  kceAllocSlotReq.valid := false.B
  kceAllocSlotReq.bits := DontCare
  val kceAllocSlotResp = DoubleBuffer(io.kceAllocSlotResp, rsp.kceClaimSlotRespFB, rsp.kceClaimSlotRespBB)

  val kteRfRelease = DoubleBuffer(io.kteRfRelease, rsp.rfReleaseFB, rsp.rfReleaseBB)
  kteRfRelease.ready := true.B

  val renamedIn = DoubleBuffer(io.renamedIn, rsp.renamedInFB, rsp.renamedInBB)
  val issue1In = Wire(Decoupled(new RsIssuePayload(params)))
  val issue1Out = Wire(Decoupled(new RsIssuePayload(params)))
  val issue2In = Wire(Decoupled(new RsIssuePayload(params)))
  val localInFlight =
    RegInit(VecInit(Seq.fill(params.localExecLatency)(0.U.asTypeOf(new RsLocalInFlight(params)))))

  def memFootprint(valid: Bool, payload: RsIssuePayload): Valid[KteMemFootprint] = {
    val footprint = Wire(Valid(new KteMemFootprint(params)))
    val memory = payload.kinstr.kinstr.asTypeOf(new MemoryKInstrBase(params))
    val isKteTransfer = payload.kind === RsIssueKind.KteTransfer
    val isCacheLocal = payload.kind === RsIssueKind.CacheLocal
    val hasMemoryWriteset = payload.kind === RsIssueKind.CacheLocal || isKteTransfer
    footprint.valid := valid && (isCacheLocal || isKteTransfer)
    footprint.bits.unknown := isKteTransfer
    footprint.bits.willWrite := payload.willWrite
    footprint.bits.cacheSlot := payload.cacheSlot
    footprint.bits.writeset.valid := hasMemoryWriteset && memory.writeset.valid
    footprint.bits.writeset.bits := memory.writeset.bits
    footprint
  }

  // issue0: decode, resolve parameter memory, and form resource metadata for
  // the in-order head instruction.
  val issue0Base = renamedIn.bits.asTypeOf(new KInstrBase(params))
  val issue0Binary = renamedIn.bits.asTypeOf(new BinaryOpInstr(params))
  val issue0Indexed = renamedIn.bits.asTypeOf(new IndexedInstr(params))
  val issue0LoadImm = renamedIn.bits.asTypeOf(new LoadImmInstr(params))
  val issue0LoadSimple = renamedIn.bits.asTypeOf(new LoadSimpleInstr(params))
  val issue0StoreScalar = renamedIn.bits.asTypeOf(new StoreScalarInstr(params))
  val issue0StoreSimple = renamedIn.bits.asTypeOf(new StoreSimpleInstr(params))
  val issue0WriteParam = renamedIn.bits.asTypeOf(new WriteParamInstr(params))

  val issue0IsSyncTrigger = issue0Base.opcode === KInstrOpcode.SyncTrigger
  val issue0IsIdentQuery = issue0Base.opcode === KInstrOpcode.IdentQuery
  val issue0IsLoadSimple = issue0Base.opcode === KInstrOpcode.LoadSimple
  val issue0IsStoreSimple = issue0Base.opcode === KInstrOpcode.StoreSimple
  val issue0IsLoadImm = issue0Base.opcode === KInstrOpcode.LoadImm
  val issue0IsWriteParam = issue0Base.opcode === KInstrOpcode.WriteParam
  val issue0IsStoreScalar = issue0Base.opcode === KInstrOpcode.StoreScalar
  val issue0IsAlu =
    issue0Base.opcode === KInstrOpcode.Add ||
      issue0Base.opcode === KInstrOpcode.Sub ||
      issue0Base.opcode === KInstrOpcode.Mul ||
      issue0Base.opcode === KInstrOpcode.MulHigh
  val issue0IsIndexed =
    issue0Base.opcode === KInstrOpcode.LoadIdxUnord ||
      issue0Base.opcode === KInstrOpcode.StoreIdxUnord
  val issue0SimpleBaseAddr = paramMem(KInstr.baseAddrParamIdx(params,
    Mux(issue0IsLoadSimple, issue0LoadSimple.baseAddrParamIdx, issue0StoreSimple.baseAddrParamIdx)))
  val issue0SimpleCacheLineAddr =
    (issue0SimpleBaseAddr >> (params.log2CacheSlotWordsPerJamlet + params.log2JInL).U)(
      params.cacheLineAddrWidth - 1, 0)
  val issue0SimpleSramWordOffset =
    issue0SimpleBaseAddr(
      params.log2CacheSlotWordsPerJamlet + params.log2JInK - 1,
      params.log2JInK)

  val issue0Out = Wire(Decoupled(new RsIssuePayload(params)))
  val issue0SrcAOrdering = rfOrdering(issue0Binary.srcAReg)
  val issue0SrcBOrdering = rfOrdering(issue0Binary.srcBReg)
  issue0Out.bits.kind := RsIssueKind.Unsupported
  issue0Out.bits.kinstr.kinstr := renamedIn.bits
  issue0Out.bits.kinstr.ordering := rfOrdering(0)
  issue0Out.bits.kinstr.cacheSlot := 0.U
  issue0Out.bits.kinstr.sramWordOffset := 0.U
  issue0Out.bits.kinstr.param0 := 0.U
  issue0Out.bits.kinstr.param1 := 0.U
  issue0Out.bits.kinstr.param2 := 0.U
  issue0Out.bits.targetValid := false.B
  issue0Out.bits.targetJInK := 0.U
  issue0Out.bits.cacheLineAddr := 0.U
  issue0Out.bits.cacheSlot := 0.U
  issue0Out.bits.cacheSlotPresent := false.B
  issue0Out.bits.willWrite := false.B
  for (rfUse <- issue0Out.bits.rfUses) {
    rfUse.valid := false.B
    rfUse.addr := 0.U
  }

  when (issue0IsSyncTrigger || issue0IsIdentQuery) {
    issue0Out.bits.kind := RsIssueKind.KteSync
    issue0Out.bits.kinstr.param0 := Mux(issue0IsIdentQuery, params.maxResponseTags.U, 0.U)
  } .elsewhen (issue0IsLoadImm) {
    issue0Out.bits.kind := RsIssueKind.LocalOne
    issue0Out.bits.targetValid := true.B
    issue0Out.bits.targetJInK := issue0LoadImm.jInKIndex
    issue0Out.bits.rfUses(0).valid := true.B
    issue0Out.bits.rfUses(0).addr := issue0LoadImm.rfAddr
  } .elsewhen (issue0IsWriteParam) {
    issue0Out.bits.kind := RsIssueKind.SideEffect
    issue0Out.bits.kinstr.param0 := issue0WriteParam.paramIdx
    issue0Out.bits.kinstr.param1 := issue0WriteParam.data
  } .elsewhen (issue0IsStoreScalar) {
    issue0Out.bits.kind := RsIssueKind.LocalBroadcast
    issue0Out.bits.kinstr.ordering := rfOrdering(issue0StoreScalar.dataReg)
    issue0Out.bits.kinstr.param0 :=
      paramMem(KInstr.baseAddrParamIdx(params, issue0StoreScalar.scalarAddrParamIdx))
    issue0Out.bits.rfUses(0).valid := true.B
    issue0Out.bits.rfUses(0).addr := issue0StoreScalar.dataReg
  } .elsewhen (issue0IsAlu) {
    issue0Out.bits.kind := RsIssueKind.LocalBroadcast
    issue0Out.bits.kinstr.ordering := issue0SrcAOrdering
    issue0Out.bits.kinstr.param0 :=
      paramMem(KInstr.startIndexParamIdx(params, issue0Binary.startIndexParamIdx))
    issue0Out.bits.kinstr.param1 :=
      paramMem(KInstr.endIndexParamIdx(params, issue0Binary.endIndexParamIdx))
    issue0Out.bits.rfUses(0).valid := true.B
    issue0Out.bits.rfUses(0).addr := issue0Binary.dstReg
    issue0Out.bits.rfUses(1).valid := true.B
    issue0Out.bits.rfUses(1).addr := issue0Binary.srcAReg
    issue0Out.bits.rfUses(2).valid := true.B
    issue0Out.bits.rfUses(2).addr := issue0Binary.srcBReg
    issue0Out.bits.rfUses(3).valid := issue0Binary.maskEnabled
    issue0Out.bits.rfUses(3).addr := issue0Binary.maskReg
  } .elsewhen (issue0IsLoadSimple || issue0IsStoreSimple) {
    issue0Out.bits.kind := RsIssueKind.CacheLocal
    issue0Out.bits.kinstr.ordering := rfOrdering(issue0LoadSimple.rfAddr)
    when (issue0IsLoadSimple) {
      issue0Out.bits.kinstr.ordering.wf := ewAsWf(issue0LoadSimple.ew)
    }
    issue0Out.bits.kinstr.param0 := paramMem(KInstr.startIndexParamIdx(params,
      Mux(issue0IsLoadSimple, issue0LoadSimple.startIndexParamIdx,
        issue0StoreSimple.startIndexParamIdx)))
    issue0Out.bits.kinstr.param1 := paramMem(KInstr.endIndexParamIdx(params,
      Mux(issue0IsLoadSimple, issue0LoadSimple.endIndexParamIdx,
        issue0StoreSimple.endIndexParamIdx)))
    issue0Out.bits.kinstr.sramWordOffset := issue0SimpleSramWordOffset
    issue0Out.bits.cacheLineAddr := issue0SimpleCacheLineAddr
    issue0Out.bits.willWrite := issue0IsStoreSimple
    issue0Out.bits.rfUses(0).valid := true.B
    issue0Out.bits.rfUses(0).addr := Mux(issue0IsLoadSimple, issue0LoadSimple.rfAddr,
      issue0StoreSimple.rfAddr)
    issue0Out.bits.rfUses(1).valid := Mux(issue0IsLoadSimple,
      issue0LoadSimple.maskEnabled, issue0StoreSimple.maskEnabled)
    issue0Out.bits.rfUses(1).addr := Mux(issue0IsLoadSimple, issue0LoadSimple.maskReg,
      issue0StoreSimple.maskReg)
  } .elsewhen (issue0IsIndexed) {
    issue0Out.bits.kind := RsIssueKind.KteTransfer
    issue0Out.bits.kinstr.ordering := rfOrdering(issue0Indexed.reg)
    when (issue0Base.opcode === KInstrOpcode.LoadIdxUnord) {
      issue0Out.bits.kinstr.ordering.wf := ewAsWf(issue0Indexed.rfEw)
      issue0Out.bits.kinstr.ordering.laneOrder := issue0Indexed.rfLaneOrder
    }
    issue0Out.bits.kinstr.param0 :=
      paramMem(KInstr.baseAddrParamIdx(params, issue0Indexed.baseAddrParamIdx))
    issue0Out.bits.kinstr.param1 :=
      paramMem(KInstr.startIndexParamIdx(params, issue0Indexed.startIndexParamIdx))
    issue0Out.bits.kinstr.param2 :=
      paramMem(KInstr.endIndexParamIdx(params, issue0Indexed.endIndexParamIdx))
    issue0Out.bits.willWrite := issue0Base.opcode === KInstrOpcode.StoreIdxUnord
    issue0Out.bits.rfUses(0).valid := true.B
    issue0Out.bits.rfUses(0).addr := issue0Indexed.reg
    issue0Out.bits.rfUses(1).valid := true.B
    issue0Out.bits.rfUses(1).addr := issue0Indexed.indexReg
    issue0Out.bits.rfUses(2).valid := issue0Indexed.maskEnabled
    issue0Out.bits.rfUses(2).addr := issue0Indexed.maskReg
  }
  val issue01Buffer =
    Module(new DoubleBuffer(new RsIssuePayload(params), rsp.issue01FB, rsp.issue01BB))
  issue01Buffer.io.i <> issue0Out
  issue1In <> issue01Buffer.io.o
  val issue12Buffer =
    Module(new DoubleBuffer(new RsIssuePayload(params), rsp.issue12FB, rsp.issue12BB))
  issue12Buffer.io.i <> issue1Out
  issue2In <> issue12Buffer.io.o

  val issue1IsCacheLocal = issue1In.bits.kind === RsIssueKind.CacheLocal
  val issue2IsSideEffect = issue2In.bits.kind === RsIssueKind.SideEffect
  val issue2IsLocalOne = issue2In.bits.kind === RsIssueKind.LocalOne
  val issue2IsLocalBroadcast = issue2In.bits.kind === RsIssueKind.LocalBroadcast
  val issue2IsCacheLocal = issue2In.bits.kind === RsIssueKind.CacheLocal
  val issue2IsKteTransfer = issue2In.bits.kind === RsIssueKind.KteTransfer
  val issue2IsKteSync = issue2In.bits.kind === RsIssueKind.KteSync
  val issue2IsKte = issue2IsKteTransfer || issue2IsKteSync
  issue0Out.valid := renamedIn.valid && (!issue0Out.bits.kind.isOneOf(RsIssueKind.CacheLocal) || kceAllocSlotReq.ready)
  renamedIn.ready := issue0Out.ready && (!issue0Out.bits.kind.isOneOf(RsIssueKind.CacheLocal) || kceAllocSlotReq.ready)
  kceAllocSlotReq.valid := renamedIn.valid && issue0Out.bits.kind === RsIssueKind.CacheLocal && issue0Out.ready
  kceAllocSlotReq.bits.cacheLineAddr := issue0Out.bits.cacheLineAddr
  kceAllocSlotReq.bits.willWrite := issue0Out.bits.willWrite

  when (renamedIn.fire) {
    when (issue0IsAlu) {
      rfOrderingNext(issue0Binary.dstReg) := issue0SrcAOrdering
      // TODO: widening and narrowing ops should adjust wf to preserve the
      // source ew/wf ratio. Same-width ops keep the source wf unchanged.
    } .elsewhen (issue0IsLoadSimple) {
      rfOrderingNext(issue0LoadSimple.rfAddr) := issue0Out.bits.kinstr.ordering
    } .elsewhen (issue0IsIndexed && issue0Base.opcode === KInstrOpcode.LoadIdxUnord) {
      rfOrderingNext(issue0Indexed.reg) := issue0Out.bits.kinstr.ordering
    }
  }

  val errors = Wire(new ReservationStationErrors)
  errors := 0.U.asTypeOf(new ReservationStationErrors)
  errors.binarySrcLaneOrderMismatch :=
    renamedIn.fire && issue0IsAlu &&
      issue0SrcAOrdering.laneOrder =/= issue0SrcBOrdering.laneOrder
  io.errors := RegNext(errors)

  // issue1: join cache-local instructions with their allocation response.
  issue1Out.bits := issue1In.bits
  issue1Out.bits.cacheSlot := kceAllocSlotResp.bits.slot
  issue1Out.bits.cacheSlotPresent :=
    kceAllocSlotResp.bits.state === KceCacheSlotState.PresentClean ||
      kceAllocSlotResp.bits.state === KceCacheSlotState.PresentDirty
  issue1Out.valid := issue1In.valid && (!issue1IsCacheLocal || kceAllocSlotResp.valid)

  issue1In.ready :=
    issue1Out.ready && (!issue1IsCacheLocal || kceAllocSlotResp.valid)
  kceAllocSlotResp.ready := issue1In.valid && issue1IsCacheLocal && issue1Out.ready

  // issue2: commit/output stage. Cache-local instructions now have an
  // allocated slot from issue1, so both RF and memory checks happen here.
  val issue2CacheLocalToKte = issue2IsCacheLocal && !issue2In.bits.cacheSlotPresent
  val issue2CacheLocalToLocal = issue2IsCacheLocal && issue2In.bits.cacheSlotPresent
  val issue2RfBlocked = issue2In.bits.rfUses.map(rfUse =>
    rfUse.valid && rfBusy(rfUse.addr)).reduce(_ || _)
  val issue2MemWithSlot = memFootprint(issue2In.valid, issue2In.bits)
  val issue2LocalMemConflict =
    localInFlight.map(entry => KteMemFootprint.conflicts(issue2MemWithSlot, entry.mem)).reduce(_ || _)
  io.kteConflictMem := issue2MemWithSlot
  val issue2MemConflict = issue2LocalMemConflict || io.kteConflict
  val issue2CanCommit = !issue2RfBlocked && !issue2MemConflict

  kteIssue.valid := issue2In.valid && issue2CanCommit && (issue2IsKte || issue2CacheLocalToKte)
  kteIssue.bits.opType := Mux(
    issue2IsKteSync,
    KteOpType.Sync,
    Mux(issue2CacheLocalToKte, KteOpType.CacheWaitLocal, KteOpType.JteTransfer))
  kteIssue.bits.kinstr := issue2In.bits.kinstr
  kteIssue.bits.cacheSlot := issue2In.bits.cacheSlot

  when (issue2In.valid && issue2CanCommit && issue2CacheLocalToLocal) {
    for (jInK <- 0 until params.jInK) {
      immediateKinstr(jInK).valid := true.B
      immediateKinstr(jInK).bits := issue2In.bits.kinstr
      immediateKinstr(jInK).bits.cacheSlot := issue2In.bits.cacheSlot
    }
  }

  when (issue2In.valid && issue2CanCommit && issue2IsLocalOne) {
    for (jInK <- 0 until params.jInK) {
      when (issue2In.bits.targetJInK === jInK.U) {
        immediateKinstr(jInK).valid := true.B
        immediateKinstr(jInK).bits := issue2In.bits.kinstr
      }
    }
  }

  when (issue2In.valid && issue2CanCommit && issue2IsLocalBroadcast) {
    for (jInK <- 0 until params.jInK) {
      immediateKinstr(jInK).valid := true.B
      immediateKinstr(jInK).bits := issue2In.bits.kinstr
    }
  }

  val issue2GoesLocal =
    issue2IsSideEffect || issue2IsLocalOne || issue2IsLocalBroadcast || issue2CacheLocalToLocal
  val issue2GoesKte = issue2CacheLocalToKte || issue2IsKte
  issue2In.ready :=
    (issue2CanCommit && issue2GoesLocal) ||
      (issue2CanCommit && issue2GoesKte && kteIssue.ready) ||
      issue2In.bits.kind === RsIssueKind.Unsupported

  when (issue2In.fire && issue2IsSideEffect) {
    paramMemNext(issue2In.bits.kinstr.param0(params.log2NParams - 1, 0)) :=
      issue2In.bits.kinstr.param1
  }

  val issue2IsLocalRfOp = issue2IsLocalOne || issue2IsLocalBroadcast || issue2CacheLocalToLocal
  val issue2IsKteRfOp = issue2IsKteTransfer || issue2CacheLocalToKte

  val issue2LocalInFlight = Wire(new RsLocalInFlight(params))
  issue2LocalInFlight.valid := issue2In.fire && issue2IsLocalRfOp
  issue2LocalInFlight.rfRelease.uses := issue2In.bits.rfUses
  issue2LocalInFlight.mem.valid := issue2In.fire && issue2CacheLocalToLocal
  issue2LocalInFlight.mem.bits := issue2MemWithSlot.bits

  localInFlight(0) := issue2LocalInFlight
  for (stage <- 1 until params.localExecLatency) {
    localInFlight(stage) := localInFlight(stage - 1)
  }

  when (localInFlight(params.localExecLatency - 1).valid) {
    for (rfUse <- localInFlight(params.localExecLatency - 1).rfRelease.uses) {
      when (rfUse.valid) {
        rfBusyNext(rfUse.addr) := false.B
      }
    }
  }

  when (kteRfRelease.fire) {
    for (rfUse <- kteRfRelease.bits.uses) {
      when (rfUse.valid) {
        rfBusyNext(rfUse.addr) := false.B
      }
    }
  }

  when (issue2In.fire && (issue2IsLocalRfOp || issue2IsKteRfOp)) {
    for (rfUse <- issue2In.bits.rfUses) {
      when (rfUse.valid) {
        rfBusyNext(rfUse.addr) := true.B
      }
    }
  }
}
