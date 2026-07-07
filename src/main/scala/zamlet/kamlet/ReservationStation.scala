package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.{LaneOrder, Ordering, WidthFormat, ZamletParams}
import zamlet.jamlet.{KInstr, KInstrBase, KinstrWithParams, LoadImmInstr, LocalExec,
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
  val rfReadReleaseUnderflow = Bool()
  val rfWriteReleaseUnexpected = Bool()
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
  val localExecDependentInputSeparation = LocalExec.inputToDependentInputMinSeparation(params)
  val maxRfReaders = params.witemTableDepth + localExecDependentInputSeparation
  val rfReadCountWidth = log2Ceil(maxRfReaders + 1)
  val rfReadCountMax = maxRfReaders.U(rfReadCountWidth.W)
  val rfReadCountNext = Wire(Vec(params.rfSliceWords, UInt(rfReadCountWidth.W)))
  val rfReadCount = RegEnable(rfReadCountNext,
    VecInit(Seq.fill(params.rfSliceWords)(0.U(rfReadCountWidth.W))), true.B)
  val rfWriteBusyNext = Wire(Vec(params.rfSliceWords, Bool()))
  val rfWriteBusy =
    RegEnable(rfWriteBusyNext, VecInit(Seq.fill(params.rfSliceWords)(false.B)), true.B)
  val localInFlight =
    RegInit(VecInit(Seq.fill(localExecDependentInputSeparation)(0.U.asTypeOf(new RsLocalInFlight(params)))))

  def memFootprint(valid: Bool, payload: RsIssuePayload): Valid[KteMemFootprint] = {
    val footprint = Wire(Valid(new KteMemFootprint(params)))
    val slotted = payload.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    val isKteTransfer = payload.kind === RsIssueKind.KteTransfer
    val isCacheLocal = payload.kind === RsIssueKind.CacheLocal
    val hasMemoryWriteset = payload.kind === RsIssueKind.CacheLocal || isKteTransfer
    footprint.valid := valid && (isCacheLocal || isKteTransfer)
    footprint.bits.unknown := isKteTransfer
    footprint.bits.willWrite := payload.willWrite
    footprint.bits.cacheSlot := payload.cacheSlot
    footprint.bits.writeset.valid := hasMemoryWriteset && slotted.writeset.valid
    footprint.bits.writeset.bits := slotted.writeset.bits
    footprint
  }

  // issue0: decode, resolve parameter memory, and form resource metadata for
  // the in-order head instruction.
  val issue0Slotted = renamedIn.bits.asTypeOf(new KInstrBase(params))
  val issue0F1Reg = issue0Slotted.rfSlotAddr(0)
  val issue0F3Reg = issue0Slotted.rfSlotAddr(2)
  val issue0F4Reg = issue0Slotted.rfSlotAddr(3)
  val issue0LoadImm = renamedIn.bits.asTypeOf(new LoadImmInstr(params))
  val issue0WriteParam = renamedIn.bits.asTypeOf(new WriteParamInstr(params))

  val issue0BaseAddr =
    paramMem(KInstr.baseAddrParamIdx(params, issue0Slotted.miscParamRef))
  val issue0StartIndex =
    paramMem(KInstr.startIndexParamIdx(params, issue0Slotted.startIndexParamIdx))
  val issue0EndIndex =
    paramMem(KInstr.endIndexParamIdx(params, issue0Slotted.endIndexParamIdx))
  val issue0SimpleCacheLineAddr =
    (issue0BaseAddr >> (params.log2CacheSlotWordsPerJamlet + params.log2JInL).U)(
      params.cacheLineAddrWidth - 1, 0)
  val issue0SimpleSramWordOffset =
    issue0BaseAddr(
      params.log2CacheSlotWordsPerJamlet + params.log2JInK - 1,
      params.log2JInK)

  val issue0Out = Wire(Decoupled(new RsIssuePayload(params)))
  val issue0SrcAOrdering = rfOrdering(issue0F3Reg)
  val issue0SrcBOrdering = rfOrdering(issue0F4Reg)
  issue0Out.bits.kind := MuxCase(RsIssueKind.Unsupported, Seq(
    issue0Slotted.isKteSync -> RsIssueKind.KteSync,
    issue0Slotted.isLoadImm -> RsIssueKind.LocalOne,
    issue0Slotted.isWriteParam -> RsIssueKind.SideEffect,
    issue0Slotted.isLocalBroadcast -> RsIssueKind.LocalBroadcast,
    issue0Slotted.isCacheLocal -> RsIssueKind.CacheLocal,
    issue0Slotted.isKteTransfer -> RsIssueKind.KteTransfer))
  issue0Out.bits.kinstr.kinstr := renamedIn.bits
  issue0Out.bits.kinstr.ordering := MuxCase(rfOrdering(0), Seq(
    issue0Slotted.isStoreScalar -> rfOrdering(issue0F1Reg),
    issue0Slotted.isAlu -> issue0SrcAOrdering,
    issue0Slotted.isCacheLocal -> rfOrdering(issue0F1Reg),
    issue0Slotted.isIndexed -> rfOrdering(issue0F3Reg)))
  when (issue0Slotted.isLoadSimple || issue0Slotted.isIndexedLoad) {
    issue0Out.bits.kinstr.ordering.wf := ewAsWf(issue0Slotted.ew)
  }
  issue0Out.bits.kinstr.cacheSlot := 0.U
  issue0Out.bits.kinstr.sramWordOffset :=
    Mux(issue0Slotted.isCacheLocal, issue0SimpleSramWordOffset, 0.U)
  // IdentQuery only needs an RS-local distance once the RS can issue out of
  // order. For now the RS contributes the sentinel distance, meaning no older
  // instruction is hidden here.
  issue0Out.bits.kinstr.param0 := MuxCase(issue0BaseAddr, Seq(
    issue0Slotted.isIdentQuery -> params.maxResponseTags.U))
  issue0Out.bits.kinstr.param1 := issue0StartIndex
  issue0Out.bits.kinstr.param2 := issue0EndIndex
  issue0Out.bits.targetValid := issue0Slotted.isLoadImm
  issue0Out.bits.targetJInK := Mux(issue0Slotted.isLoadImm, issue0LoadImm.jInKIndex, 0.U)
  issue0Out.bits.cacheLineAddr :=
    Mux(issue0Slotted.isCacheLocal, issue0SimpleCacheLineAddr, 0.U)
  issue0Out.bits.cacheSlot := 0.U
  issue0Out.bits.cacheSlotPresent := false.B
  issue0Out.bits.willWrite := issue0Slotted.isStoreSimple || issue0Slotted.isIndexedStore
  for (slot <- 0 until 4) {
    issue0Out.bits.rfUses(slot).valid :=
      issue0Slotted.rfSlotReads(slot) || issue0Slotted.rfSlotWrites(slot)
    issue0Out.bits.rfUses(slot).addr := issue0Slotted.rfSlotAddr(slot)
    issue0Out.bits.rfUses(slot).isWrite := issue0Slotted.rfSlotWrites(slot)
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

  when (renamedIn.fire && issue0Slotted.isWriteParam) {
    paramMemNext(issue0WriteParam.paramIdx(params.log2NParams - 1, 0)) :=
      issue0WriteParam.data
  }

  when (renamedIn.fire) {
    when (issue0Slotted.isAlu) {
      rfOrderingNext(issue0F1Reg) := issue0SrcAOrdering
      // TODO: widening and narrowing ops should adjust wf to preserve the
      // source ew/wf ratio. Same-width ops keep the source wf unchanged.
    } .elsewhen (issue0Slotted.isLoadSimple) {
      rfOrderingNext(issue0F1Reg) := issue0Out.bits.kinstr.ordering
    } .elsewhen (issue0Slotted.isIndexedLoad) {
      rfOrderingNext(issue0F1Reg) := issue0Out.bits.kinstr.ordering
    }
  }

  val errors = Wire(new ReservationStationErrors)
  errors := 0.U.asTypeOf(new ReservationStationErrors)
  errors.binarySrcLaneOrderMismatch :=
    renamedIn.fire && issue0Slotted.isAlu &&
      issue0SrcAOrdering.laneOrder =/= issue0SrcBOrdering.laneOrder
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
    rfUse.valid &&
      Mux(rfUse.isWrite,
        rfWriteBusy(rfUse.addr) || rfReadCount(rfUse.addr) =/= 0.U,
        rfWriteBusy(rfUse.addr) || rfReadCount(rfUse.addr) === rfReadCountMax)).reduce(_ || _)
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

  val issue2IsLocalRfOp = issue2IsLocalOne || issue2IsLocalBroadcast || issue2CacheLocalToLocal
  val issue2IsKteRfOp = issue2IsKteTransfer || issue2CacheLocalToKte

  val issue2LocalInFlight = Wire(new RsLocalInFlight(params))
  issue2LocalInFlight.valid := issue2In.fire && issue2IsLocalRfOp
  issue2LocalInFlight.rfRelease.uses := issue2In.bits.rfUses
  issue2LocalInFlight.mem.valid := issue2In.fire && issue2CacheLocalToLocal
  issue2LocalInFlight.mem.bits := issue2MemWithSlot.bits

  localInFlight(0) := issue2LocalInFlight
  for (stage <- 1 until localExecDependentInputSeparation) {
    localInFlight(stage) := localInFlight(stage - 1)
  }

  val rfReadCountAfterLocalRelease = Wire(Vec(params.rfSliceWords, UInt(rfReadCountWidth.W)))
  val rfWriteBusyAfterLocalRelease = Wire(Vec(params.rfSliceWords, Bool()))
  rfReadCountAfterLocalRelease := rfReadCount
  rfWriteBusyAfterLocalRelease := rfWriteBusy

  when (localInFlight(localExecDependentInputSeparation - 1).valid) {
    for (rfUse <- localInFlight(localExecDependentInputSeparation - 1).rfRelease.uses) {
      when (rfUse.valid) {
        when (rfUse.isWrite) {
          errors.rfWriteReleaseUnexpected := !rfWriteBusy(rfUse.addr)
          rfWriteBusyAfterLocalRelease(rfUse.addr) := false.B
        } .otherwise {
          errors.rfReadReleaseUnderflow := rfReadCount(rfUse.addr) === 0.U
          rfReadCountAfterLocalRelease(rfUse.addr) := rfReadCount(rfUse.addr) - 1.U
        }
      }
    }
  }

  val rfReadCountAfterKteRelease = Wire(Vec(params.rfSliceWords, UInt(rfReadCountWidth.W)))
  val rfWriteBusyAfterKteRelease = Wire(Vec(params.rfSliceWords, Bool()))
  rfReadCountAfterKteRelease := rfReadCountAfterLocalRelease
  rfWriteBusyAfterKteRelease := rfWriteBusyAfterLocalRelease

  when (kteRfRelease.fire) {
    for (rfUse <- kteRfRelease.bits.uses) {
      when (rfUse.valid) {
        when (rfUse.isWrite) {
          errors.rfWriteReleaseUnexpected := !rfWriteBusyAfterLocalRelease(rfUse.addr)
          rfWriteBusyAfterKteRelease(rfUse.addr) := false.B
        } .otherwise {
          errors.rfReadReleaseUnderflow := rfReadCountAfterLocalRelease(rfUse.addr) === 0.U
          rfReadCountAfterKteRelease(rfUse.addr) := rfReadCountAfterLocalRelease(rfUse.addr) - 1.U
        }
      }
    }
  }

  val rfReadCountAfterAcquire = Wire(Vec(params.rfSliceWords, UInt(rfReadCountWidth.W)))
  val rfWriteBusyAfterAcquire = Wire(Vec(params.rfSliceWords, Bool()))
  rfReadCountAfterAcquire := rfReadCountAfterKteRelease
  rfWriteBusyAfterAcquire := rfWriteBusyAfterKteRelease

  when (issue2In.fire && (issue2IsLocalRfOp || issue2IsKteRfOp)) {
    for (rfUse <- issue2In.bits.rfUses) {
      when (rfUse.valid) {
        when (rfUse.isWrite) {
          rfWriteBusyAfterAcquire(rfUse.addr) := true.B
        } .otherwise {
          rfReadCountAfterAcquire(rfUse.addr) := rfReadCountAfterKteRelease(rfUse.addr) + 1.U
        }
      }
    }
  }

  rfReadCountNext := rfReadCountAfterAcquire
  rfWriteBusyNext := rfWriteBusyAfterAcquire

  io.errors := RegNext(errors)
}
