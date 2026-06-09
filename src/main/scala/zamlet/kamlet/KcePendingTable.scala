package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{CacheLineRequest, CacheLineResponse, CacheLineState, JteHandlerReplay}
import zamlet.network.MessageType
import zamlet.utils.{DoubleBuffer, ValidBuffer}

class KcePendingTableIO(params: ZamletParams) extends Bundle {
  // JTE request/response path. Full pending/replay behavior will be implemented
  // later; this stub only defines the contract.
  val cacheLineReq = Vec(params.jInK, Flipped(Decoupled(new CacheLineRequest(params))))
  val cacheLineResp = Vec(params.jInK, Decoupled(new CacheLineResponse(params)))
  val replay = Vec(params.jInK, Decoupled(new JteHandlerReplay(params)))
  val cacheLineRelease = Vec(params.jInK, Flipped(Valid(new KceSlotRelease(params))))

  // Metadata table access. JTE-originated releases are aggregated into the
  // single releaseSlot event.
  val claimSlotReq = Decoupled(new KceClaimSlotReq(params))
  val claimSlotResp = Flipped(Decoupled(new KceClaimSlotResp(params)))
  val allocSlotReq = Decoupled(new KceAllocSlotReq(params))
  val allocSlotResp = Flipped(Decoupled(new KceAllocSlotResp(params)))
  val releaseSlot = Valid(new KceSlotRelease(params))
  val slotIsAvailable = Flipped(Valid(params.cacheSlot()))
  val errors = Output(new KcePendingTableErrors)
}

class KcePendingReq(params: ZamletParams) extends Bundle {
  val jInK = UInt((params.log2JCols + params.log2JRows).W)
  val req = new CacheLineRequest(params)
  // True once req1 has reserved capacity for this request to wait in the
  // pending-entry table if the cache table reports a fetching slot.
  val reservedPendingSlot = Bool()
}

class KcePendingEntry(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val pendingReq = new KcePendingReq(params)
  val slotAvailable = Bool()
  val needsAlloc = Bool()
}

class KcePendingTableErrors extends Bundle {
  val slotAvailableNeedsAlloc = Bool()
  val pendingSlotsInUseOverflow = Bool()
  val pendingSlotsInUseUnderflow = Bool()
  val freeEntryOverwrite = Bool()
  val allocRespReplayConflict = Bool()
  val wakeReplayConflict = Bool()
}

class KcePendingTable(params: ZamletParams) extends Module {
  val io = IO(new KcePendingTableIO(params))
  val ptp = params.kcePendingTableParams
  private val jInKWidth = params.log2JCols + params.log2JRows

  // ============================================================
  // IO buffering
  // ============================================================

  val cacheLineReq = (0 until params.jInK).map { jInK =>
    DoubleBuffer(io.cacheLineReq(jInK), ptp.cacheLineReqFB, ptp.cacheLineReqBB)
  }

  val cacheLineResp = (0 until params.jInK).map { jInK =>
    val resp = Wire(Decoupled(new CacheLineResponse(params)))
    io.cacheLineResp(jInK) <> DoubleBuffer(resp, ptp.cacheLineRespFB, ptp.cacheLineRespBB)
    resp
  }

  val replay = (0 until params.jInK).map { jInK =>
    val replayOut = Wire(Decoupled(new JteHandlerReplay(params)))
    io.replay(jInK) <> DoubleBuffer(replayOut, ptp.replayFB, ptp.replayBB)
    replayOut
  }

  val cacheLineRelease = (0 until params.jInK).map { jInK =>
    ValidBuffer(io.cacheLineRelease(jInK), ptp.cacheLineReleaseBuffer)
  }

  val claimSlotReq = Wire(Decoupled(new KceClaimSlotReq(params)))
  io.claimSlotReq <> DoubleBuffer(claimSlotReq, ptp.claimSlotReqFB, ptp.claimSlotReqBB)
  val claimSlotResp = DoubleBuffer(io.claimSlotResp, ptp.claimSlotRespFB, ptp.claimSlotRespBB)

  val allocSlotReq = Wire(Decoupled(new KceAllocSlotReq(params)))
  io.allocSlotReq <> DoubleBuffer(allocSlotReq, ptp.allocSlotReqFB, ptp.allocSlotReqBB)
  val allocSlotResp = DoubleBuffer(io.allocSlotResp, ptp.allocSlotRespFB, ptp.allocSlotRespBB)

  val releaseSlot = Wire(Valid(new KceSlotRelease(params)))
  io.releaseSlot := ValidBuffer(releaseSlot, ptp.releaseSlotBuffer)
  val slotIsAvailable = ValidBuffer(io.slotIsAvailable, ptp.slotIsAvailableBuffer)

  for (jInK <- 0 until params.jInK) {
    cacheLineReq(jInK).ready := false.B
    cacheLineResp(jInK).valid := false.B
    cacheLineResp(jInK).bits := DontCare
    replay(jInK).valid := false.B
    replay(jInK).bits := DontCare
  }

  claimSlotReq.valid := false.B
  claimSlotReq.bits := DontCare
  claimSlotResp.ready := false.B
  allocSlotReq.valid := false.B
  allocSlotReq.bits := DontCare
  allocSlotResp.ready := false.B

  val errors = Wire(new KcePendingTableErrors)
  errors := 0.U.asTypeOf(errors)
  io.errors := RegNext(errors)

  // ============================================================
  // Pending-entry table
  // ============================================================

  val entriesInitial = Wire(Vec(params.kcePendingTableDepth, Valid(new KcePendingEntry(params))))
  entriesInitial := 0.U.asTypeOf(entriesInitial)

  val entriesNext = Wire(Vec(params.kcePendingTableDepth, Valid(new KcePendingEntry(params))))
  val entries = RegEnable(entriesNext, entriesInitial, true.B)
  entriesNext := entries

  private val entryIndexWidth = log2Ceil(params.kcePendingTableDepth)
  val freeEntryUpdate = Wire(Bool())
  val freeEntryNext = Wire(UInt(entryIndexWidth.W))
  val freeEntry = RegEnable(freeEntryNext, 0.U, freeEntryUpdate)
  freeEntryUpdate := false.B
  freeEntryNext := freeEntry

  val pendingSlotsInUseWidth = log2Ceil(params.kcePendingTableDepth + 1)
  val pendingSlotsInUseNext = Wire(UInt(pendingSlotsInUseWidth.W))
  val pendingSlotsInUse = RegEnable(pendingSlotsInUseNext, 0.U, true.B)
  pendingSlotsInUseNext := pendingSlotsInUse
  val hasFreePendingSlot = pendingSlotsInUse < params.kcePendingTableDepth.U
  val pendingSlotsInUseIncr = Wire(Bool())
  val pendingSlotsInUseDecr = Wire(Bool())
  val replayRespFire = Wire(Bool())
  pendingSlotsInUseIncr := false.B
  pendingSlotsInUseDecr := false.B
  replayRespFire := false.B

  // ============================================================
  // req0 -> req1 request arbitration
  // ============================================================

  val req0Out = Wire(Decoupled(new KcePendingReq(params)))
  val req1In = DoubleBuffer(req0Out, ptp.req01FB, ptp.req01BB)

  val req0BaseNext = Wire(UInt(jInKWidth.W))
  val req0Base = RegEnable(req0BaseNext, 0.U, req0Out.fire)
  req0BaseNext := req0Base

  val req0Valid = VecInit((0 until params.jInK).map { jInK =>
    cacheLineReq(jInK).valid
  })
  val req0HighValid = VecInit((0 until params.jInK).map { jInK =>
    req0Valid(jInK) && jInK.U >= req0Base
  })
  val req0HighHasValid = req0HighValid.asUInt.orR

  // Round-robin select. First choose the lowest valid lane at or after
  // req0Base; if none exist, wrap and choose the lowest valid lane overall.
  val req0Selected = Mux(
    req0HighHasValid,
    PriorityEncoder(req0HighValid),
    PriorityEncoder(req0Valid))
  val req0SelectedBits = VecInit((0 until params.jInK).map { jInK =>
    cacheLineReq(jInK).bits
  })(req0Selected)

  when (req0Selected === (params.jInK - 1).U) {
    req0BaseNext := 0.U
  } .otherwise {
    req0BaseNext := req0Selected + 1.U
  }

  req0Out.valid := req0Valid.asUInt.orR
  req0Out.bits.jInK := req0Selected
  req0Out.bits.req := req0SelectedBits
  req0Out.bits.reservedPendingSlot := false.B

  for (jInK <- 0 until params.jInK) {
    cacheLineReq(jInK).ready := req0Out.ready && req0Selected === jInK.U
  }

  // req1 sends the cache-table claim. req1Out carries the original request
  // forward only when that claim request is accepted.
  val req1Out = Wire(Decoupled(new KcePendingReq(params)))
  val req2In = DoubleBuffer(req1Out, ptp.req12FB, ptp.req12BB)

  claimSlotReq.valid := req1In.valid && req1Out.ready
  claimSlotReq.bits.cacheLineAddr := req1In.bits.req.address
  claimSlotReq.bits.willWrite := req1In.bits.req.payload.msgType === MessageType.StoreWordReq.asUInt
  claimSlotReq.bits.claimIfFetching := hasFreePendingSlot
  req1Out.valid := req1In.valid && claimSlotReq.ready
  req1Out.bits := req1In.bits
  req1Out.bits.reservedPendingSlot := hasFreePendingSlot
  req1In.ready := claimSlotReq.ready && req1Out.ready

  // req2 joins the original request with the cache-table claim response and
  // returns the immediate response to the originating JTE lane.
  val req2RespReady = VecInit((0 until params.jInK).map { jInK =>
    cacheLineResp(jInK).ready
  })(req2In.bits.jInK)
  val req2Present =
    claimSlotResp.bits.didClaim &&
    (claimSlotResp.bits.state === KceCacheSlotState.PresentClean ||
      claimSlotResp.bits.state === KceCacheSlotState.PresentDirty)
  val req2Fetching =
    claimSlotResp.bits.didClaim &&
    (claimSlotResp.bits.state === KceCacheSlotState.Fetching ||
      claimSlotResp.bits.state === KceCacheSlotState.FetchingWillWrite)
  val req2NeedsAlloc =
    !claimSlotResp.bits.hasSlot && req2In.bits.reservedPendingSlot
  val req2StoredInPendingTable =
    (req2Fetching || req2NeedsAlloc) && req2In.bits.reservedPendingSlot
  val req2StoreEntry = req2StoredInPendingTable

  for (jInK <- 0 until params.jInK) {
    cacheLineResp(jInK).valid :=
      req2In.valid && claimSlotResp.valid && req2In.bits.jInK === jInK.U
    cacheLineResp(jInK).bits.slot := claimSlotResp.bits.slot
    cacheLineResp(jInK).bits.state := MuxCase(CacheLineState.Dropped, Seq(
      req2Present -> CacheLineState.Ready,
      req2StoredInPendingTable -> CacheLineState.StoredInPendingTable))
  }
  req2In.ready := claimSlotResp.valid && req2RespReady
  claimSlotResp.ready := req2In.valid && req2RespReady

  val req2RespFire = req2In.valid && claimSlotResp.valid && req2RespReady
  errors.freeEntryOverwrite := req2RespFire && req2StoreEntry && entries(freeEntry).valid
  when (req2RespFire && req2StoreEntry) {
    entriesNext(freeEntry).valid := true.B
    entriesNext(freeEntry).bits.slot := claimSlotResp.bits.slot
    entriesNext(freeEntry).bits.pendingReq := req2In.bits
    entriesNext(freeEntry).bits.slotAvailable := false.B
    entriesNext(freeEntry).bits.needsAlloc := req2NeedsAlloc
  }

  val freeEntryCandidates = Wire(Vec(params.kcePendingTableDepth, Bool()))
  for (entry <- 0 until params.kcePendingTableDepth) {
    freeEntryCandidates(entry) := !entries(entry).valid && freeEntry =/= entry.U
  }
  when (req2RespFire && req2StoreEntry && freeEntryCandidates.asUInt.orR) {
    freeEntryUpdate := true.B
    freeEntryNext := PriorityEncoder(freeEntryCandidates)
  }

  pendingSlotsInUseIncr := req1Out.fire
  pendingSlotsInUseDecr := (req2RespFire && !req2StoredInPendingTable) || replayRespFire
  errors.pendingSlotsInUseOverflow :=
    pendingSlotsInUseIncr && !pendingSlotsInUseDecr &&
      pendingSlotsInUse === params.kcePendingTableDepth.U
  errors.pendingSlotsInUseUnderflow :=
    !pendingSlotsInUseIncr && pendingSlotsInUseDecr &&
      pendingSlotsInUse === 0.U

  when (pendingSlotsInUseIncr && !pendingSlotsInUseDecr) {
    pendingSlotsInUseNext := pendingSlotsInUse + 1.U
  } .elsewhen (!pendingSlotsInUseIncr && pendingSlotsInUseDecr) {
    pendingSlotsInUseNext := pendingSlotsInUse - 1.U
  }

  // ============================================================
  // alloc pending entries
  // ============================================================

  val alloc0Matches = VecInit((0 until params.kcePendingTableDepth).map { entry =>
    entries(entry).valid &&
      entries(entry).bits.needsAlloc
  })
  val alloc0HasMatch = alloc0Matches.asUInt.orR
  val alloc0Entry = PriorityEncoder(alloc0Matches)
  val alloc0Out = Wire(Decoupled(UInt(entryIndexWidth.W)))
  val alloc1In = DoubleBuffer(alloc0Out, ptp.alloc01FB, ptp.alloc01BB)

  alloc0Out.valid := alloc0HasMatch
  alloc0Out.bits := alloc0Entry
  when (alloc0Out.fire) {
    entriesNext(alloc0Entry).bits.needsAlloc := false.B
  }

  val alloc1Out = Wire(Decoupled(UInt(entryIndexWidth.W)))
  val alloc2In = DoubleBuffer(alloc1Out, ptp.alloc12FB, ptp.alloc12BB)

  allocSlotReq.valid := alloc1In.valid && alloc1Out.ready
  allocSlotReq.bits.cacheLineAddr := entries(alloc1In.bits).bits.pendingReq.req.address
  allocSlotReq.bits.willWrite :=
    entries(alloc1In.bits).bits.pendingReq.req.payload.msgType === MessageType.StoreWordReq.asUInt
  alloc1Out.valid := alloc1In.valid && allocSlotReq.ready
  alloc1Out.bits := alloc1In.bits
  alloc1In.ready := allocSlotReq.ready && alloc1Out.ready

  allocSlotResp.ready := alloc2In.valid
  when (allocSlotResp.fire) {
    entriesNext(alloc2In.bits).bits.slot := allocSlotResp.bits.slot
  }
  alloc2In.ready := allocSlotResp.valid

  // ============================================================
  // wake pending entries
  // ============================================================

  for (entry <- 0 until params.kcePendingTableDepth) {
    when (
      slotIsAvailable.valid &&
        entries(entry).valid &&
        entries(entry).bits.slot === slotIsAvailable.bits
    ) {
      entriesNext(entry).bits.slotAvailable := true.B
    }
  }

  // ============================================================
  // replay ready pending entries
  // ============================================================

  val replayMatches = VecInit((0 until params.kcePendingTableDepth).map { entry =>
    entries(entry).valid && entries(entry).bits.slotAvailable
  })
  // FIXME: This is fixed priority for the first pass. Consider round-robin if
  // ready low-index entries can starve higher-index entries.
  errors.slotAvailableNeedsAlloc := VecInit((0 until params.kcePendingTableDepth).map { entry =>
    entries(entry).valid && entries(entry).bits.slotAvailable && entries(entry).bits.needsAlloc
  }).asUInt.orR
  val replayHasMatch = replayMatches.asUInt.orR
  val replayEntry = PriorityEncoder(replayMatches)
  val replayJInK = entries(replayEntry).bits.pendingReq.jInK
  val replayReady = VecInit((0 until params.jInK).map { jInK =>
    replay(jInK).ready
  })(replayJInK)
  val replayFire = replayHasMatch && replayReady
  errors.allocRespReplayConflict :=
    allocSlotResp.fire && replayFire && alloc2In.bits === replayEntry
  errors.wakeReplayConflict :=
    slotIsAvailable.valid &&
      replayFire &&
      entries(replayEntry).valid &&
      entries(replayEntry).bits.slot === slotIsAvailable.bits

  for (jInK <- 0 until params.jInK) {
    replay(jInK).valid := replayHasMatch && replayJInK === jInK.U
    replay(jInK).bits.payload := entries(replayEntry).bits.pendingReq.req.payload
    replay(jInK).bits.slot := entries(replayEntry).bits.slot
  }

  when (replayFire) {
    entriesNext(replayEntry).valid := false.B
  }
  replayRespFire := replayFire

  // rel*: merge JTE-originated slot-release events into the cache table's
  // single release port. Multiple same-cycle releases are serialized by
  // priority; the input side is Valid, so callers must tolerate that policy.
  val relValid = VecInit((0 until params.jInK).map { jInK =>
    cacheLineRelease(jInK).valid
  })
  val relIndex = PriorityEncoder(relValid)
  val relSelectedBits = VecInit((0 until params.jInK).map { jInK =>
    cacheLineRelease(jInK).bits
  })(relIndex)
  releaseSlot.valid := relValid.asUInt.orR
  releaseSlot.bits := relSelectedBits
}
