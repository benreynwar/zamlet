package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{CacheLineRequest, CacheLineResponse, CacheLineState, JteHandlerReplay}
import zamlet.network.MessageType
import zamlet.utils.{BroadcastUpdateBuffer, DoubleBuffer, ValidBuffer}

class KcePendingTableIO(params: ZamletParams) extends Bundle {
  // JTE request/response path. Full pending/replay behavior will be implemented
  // later; this stub only defines the contract.
  val cacheLineReq = Vec(params.jInK, Flipped(Decoupled(new CacheLineRequest(params))))
  val cacheLineResp = Vec(params.jInK, Decoupled(new CacheLineResponse(params)))
  val replay = Vec(params.jInK, Decoupled(new JteHandlerReplay(params)))
  val cacheLineRelease = Vec(params.jInK, Flipped(Valid(new KceSlotRelease(params))))

  // Instr-start status is a fixed-latency Valid path. KCE must consume the
  // response without backpressure. If a query response says an ident has not
  // started, the corresponding start notification is guaranteed not to arrive
  // at KCE until after KCE has had a cycle to store the request as
  // WaitingForInstrIdent.
  val instrStartedReq = Valid(params.ident())
  val instrStartedResp = Flipped(Valid(Bool()))
  val instrStartedNotify = Flipped(Valid(params.ident()))

  // Metadata table access. JTE-originated releases are aggregated into the
  // single releaseSlot event.
  val claimSlotReq = Decoupled(new KceClaimSlotReq(params))
  val claimSlotResp = Flipped(Decoupled(new KceClaimSlotResp(params)))
  val allocSlotReq = Decoupled(new KceAllocSlotReq(params))
  // If slotIsAvailable arrives in the same cycle as a matching allocSlotResp,
  // allocSlotResp already includes that slot-is-available update.
  val allocSlotResp = Flipped(Decoupled(new KceAllocSlotResp(params)))
  val releaseSlot = Valid(new KceSlotRelease(params))
  val slotIsAvailable = Flipped(Valid(params.cacheSlot()))
  val errors = Output(new KcePendingTableErrors)
}

class KcePendingReq(params: ZamletParams) extends Bundle {
  val jInK = UInt((params.log2JCols + params.log2JRows).W)
  val req = new CacheLineRequest(params)
}

object KcePendingEntryState extends ChiselEnum {
  val WaitingForInstrIdent, NeedsAlloc, WaitingForAllocResp, WaitingForSlotAvailable, ReadyToReplay = Value
}

// Work item carried by the req* pipeline after req0. The final req stage uses
// these facts to either emit a direct cacheLineResp or create one new pending
// entry.
class KcePendingReqWork(params: ZamletParams) extends Bundle {
  val jInK = UInt((params.log2JCols + params.log2JRows).W)
  val req = new CacheLineRequest(params)

  // True once KTE has accepted ownership of this instruction ident.
  val instrIdentAvailable = Bool()

  // True once req3 has reserved pending-table capacity by decrementing the
  // free-slot counter. If the final req stage does not create an entry, it
  // releases this reservation by incrementing the counter.
  val reservedPendingSlot = Bool()

  // Cache claim result facts. slotClaimed means slot is meaningful;
  // slotAvailable means replay/SRAM access can use it immediately.
  val slotClaimed = Bool()
  val slotAvailable = Bool()
  val slot = params.cacheSlot()
}

class KcePendingEntry(params: ZamletParams) extends Bundle {
  val state = KcePendingEntryState()
  val slot = params.cacheSlot()
  val pendingReq = new KcePendingReq(params)
}

class KcePendingTableErrors extends Bundle {
  val instrStartedNotifyUnexpectedState = Bool()
  val allocRespUnexpectedState = Bool()
  val slotAvailableUnexpectedState = Bool()
  val pendingSlotsFreeOverflow = Bool()
  val pendingSlotsFreeUnderflow = Bool()
  val freeEntryOverwrite = Bool()
  val allocRespReplayConflict = Bool()
  val wakeReplayConflict = Bool()
  val instrStartedRespOverflow = Bool()
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

  val cacheLineResp = Wire(Vec(params.jInK, Decoupled(new CacheLineResponse(params))))
  for (jInK <- 0 until params.jInK) {
    io.cacheLineResp(jInK) <> DoubleBuffer(cacheLineResp(jInK), ptp.cacheLineRespFB, ptp.cacheLineRespBB)
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

  val releaseSlot = Wire(Valid(new KceSlotRelease(params)))
  io.releaseSlot := ValidBuffer(releaseSlot, ptp.releaseSlotBuffer)

  def updateAllocSlotResp(resp: KceAllocSlotResp, availableSlot: UInt): KceAllocSlotResp = {
    val updated = Wire(new KceAllocSlotResp(params))
    updated := resp
    when (resp.slot === availableSlot) {
      when (resp.state === KceCacheSlotState.Fetching) {
        updated.state := KceCacheSlotState.PresentClean
      } .elsewhen (resp.state === KceCacheSlotState.FetchingWillWrite) {
        updated.state := KceCacheSlotState.PresentDirty
      }
    }
    updated
  }

  // This is the input timing buffer for allocSlotResp. It preserves the IO
  // contract above by updating delayed responses from slotIsAvailable.
  val allocSlotRespBuffer = Module(new BroadcastUpdateBuffer(
    new KceAllocSlotResp(params),
    params.cacheSlot(),
    updateAllocSlotResp,
    ptp.allocSlotRespFB,
    ptp.allocSlotRespBB))
  allocSlotRespBuffer.io.i <> io.allocSlotResp
  allocSlotRespBuffer.io.broadcastIn := io.slotIsAvailable
  val allocSlotResp = allocSlotRespBuffer.io.o
  // The wake path consumes the slot-available broadcast after it has passed
  // through the same timing buffer as allocSlotResp.
  val slotIsAvailable = allocSlotRespBuffer.io.broadcastOut

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
  io.instrStartedReq.valid := false.B
  io.instrStartedReq.bits := DontCare

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
  val freeEntryVec = VecInit((0 until params.kcePendingTableDepth).map { entry =>
    !entries(entry).valid
  })
  val freeEntry = PriorityEncoder(freeEntryVec)

  val pendingSlotsFreeWidth = log2Ceil(params.kcePendingTableDepth + 1)
  val pendingSlotsFreeNext = Wire(UInt(pendingSlotsFreeWidth.W))
  val pendingSlotsFree = RegEnable(pendingSlotsFreeNext, params.kcePendingTableDepth.U, true.B)
  pendingSlotsFreeNext := pendingSlotsFree
  val pendingSlotReserveCount = Wire(UInt(pendingSlotsFreeWidth.W))
  val pendingSlotReleaseReqCount = Wire(UInt(pendingSlotsFreeWidth.W))
  val pendingSlotReleaseReplayCount = Wire(UInt(pendingSlotsFreeWidth.W))
  val replayRespFire = Wire(Bool())
  pendingSlotReserveCount := 0.U
  pendingSlotReleaseReqCount := 0.U
  pendingSlotReleaseReplayCount := 0.U
  replayRespFire := false.B

  // ============================================================
  // req0 -> req1 request arbitration
  // ============================================================

  val req0Out = Wire(Decoupled(new KcePendingReqWork(params)))
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
  req0Out.bits.instrIdentAvailable := false.B
  req0Out.bits.reservedPendingSlot := false.B
  req0Out.bits.slotClaimed := false.B
  req0Out.bits.slotAvailable := false.B
  req0Out.bits.slot := 0.U

  for (jInK <- 0 until params.jInK) {
    cacheLineReq(jInK).ready := req0Out.ready && req0Selected === jInK.U
  }

  // req1 sends the fixed-latency instruction-start query to KTE. The original
  // request advances with the query so req2 can join it with the response.
  val req1Out = Wire(Decoupled(new KcePendingReqWork(params)))
  // Forward-only: req2 metadata must advance in lockstep with the fixed-latency
  // instrStartedResp. A backward/skid entry would decouple metadata from the
  // response cycle.
  val req2In = DoubleBuffer(req1Out, true, false)

  io.instrStartedReq.valid := req1In.valid && req1Out.ready
  io.instrStartedReq.bits := req1In.bits.req.payload.ident
  req1Out.valid := req1In.valid
  req1Out.bits := req1In.bits
  req1In.ready := req1Out.ready

  // req2 joins the original request with the fixed-latency KTE response.
  val req2Out = Wire(Decoupled(new KcePendingReqWork(params)))
  val req3In = DoubleBuffer(req2Out, ptp.req23FB, ptp.req23BB)
  val instrStartedRespToBuffer = Wire(Decoupled(Bool()))
  instrStartedRespToBuffer.valid := io.instrStartedResp.valid
  instrStartedRespToBuffer.bits := io.instrStartedResp.bits
  val instrStartedRespBuffered = DoubleBuffer(instrStartedRespToBuffer, false, true)
  // KTE does not see ready on this fixed-latency Valid response. The local
  // ready only reports whether the backward buffer can absorb this response.
  errors.instrStartedRespOverflow := io.instrStartedResp.valid && !instrStartedRespToBuffer.ready

  req2Out.valid := req2In.valid && instrStartedRespBuffered.valid
  req2Out.bits := req2In.bits
  req2Out.bits.instrIdentAvailable := instrStartedRespBuffered.bits
  req2In.ready := instrStartedRespBuffered.valid && req2Out.ready
  instrStartedRespBuffered.ready := req2In.valid && req2Out.ready

  // ============================================================
  // req3 cache claim request
  // ============================================================

  // req3 reserves pending-table capacity and, when the instruction is ready,
  // sends the cache claim. Requests with a missing instr ident bypass the claim
  // and are committed by req5 as WaitingForInstrIdent.
  val req3Out = Wire(Decoupled(new KcePendingReqWork(params)))
  val req3CanReserve = pendingSlotsFree =/= 0.U
  val req3SendsClaim = req3In.bits.instrIdentAvailable
  val req3CanAdvance = !req3SendsClaim || claimSlotReq.ready

  claimSlotReq.valid := req3In.valid && req3SendsClaim && req3Out.ready
  claimSlotReq.bits.cacheLineAddr := req3In.bits.req.address
  claimSlotReq.bits.willWrite := req3In.bits.req.payload.msgType === MessageType.StoreWordReq.asUInt
  claimSlotReq.bits.claimIfFetching := req3CanReserve

  req3Out.valid := req3In.valid && req3CanAdvance
  req3Out.bits := req3In.bits
  req3Out.bits.reservedPendingSlot := req3CanReserve
  req3In.ready := req3Out.ready && req3CanAdvance
  pendingSlotReserveCount := Mux(req3Out.fire && req3CanReserve, 1.U, 0.U)

  // ============================================================
  // req4 cache claim response
  // ============================================================

  // req3 issues the tag-table claim on a side path. The queue absorbs that
  // response latency so req3 can keep accepting cache-line requests while older
  // metadata waits at req4 for its matching claimSlotResp.
  val req4JoinQueue = Module(new Queue(
    new KcePendingReqWork(params),
    ptp.claimJoinQueueDepth(params.kceTagTableParams)))
  req4JoinQueue.io.enq <> req3Out
  val req4In = DoubleBuffer(req4JoinQueue.io.deq, ptp.req34FB, ptp.req34BB)
  val req4Out = Wire(Decoupled(new KcePendingReqWork(params)))
  val req4NeedsClaimResp = req4In.bits.instrIdentAvailable
  val req4CanAdvance = !req4NeedsClaimResp || claimSlotResp.valid
  val req4Present =
    claimSlotResp.bits.didClaim &&
      (claimSlotResp.bits.state === KceCacheSlotState.PresentClean ||
        claimSlotResp.bits.state === KceCacheSlotState.PresentDirty)
  val req4Fetching =
    claimSlotResp.bits.didClaim &&
      (claimSlotResp.bits.state === KceCacheSlotState.Fetching ||
        claimSlotResp.bits.state === KceCacheSlotState.FetchingWillWrite)

  req4Out.valid := req4In.valid && req4CanAdvance
  req4Out.bits := req4In.bits
  req4Out.bits.slot := claimSlotResp.bits.slot
  req4Out.bits.slotClaimed := req4NeedsClaimResp && (req4Present || req4Fetching)
  req4Out.bits.slotAvailable := req4NeedsClaimResp && req4Present
  req4In.ready := req4Out.ready && req4CanAdvance
  claimSlotResp.ready := req4In.valid && req4NeedsClaimResp && req4Out.ready

  // ============================================================
  // req5 commit
  // ============================================================

  val req5In = DoubleBuffer(req4Out, ptp.req45FB, ptp.req45BB)
  val req5NeedsInstrWait = !req5In.bits.instrIdentAvailable
  val req5NeedsSlotWait =
    req5In.bits.instrIdentAvailable && !req5In.bits.slotAvailable
  val req5NeedsStore =
    req5In.bits.reservedPendingSlot &&
      (req5NeedsInstrWait || req5NeedsSlotWait)
  val req5ReleasesReservation =
    req5In.fire &&
      req5In.bits.reservedPendingSlot &&
      !(req5NeedsInstrWait || req5NeedsSlotWait)
  val req5RespState = MuxCase(CacheLineState.Dropped, Seq(
    (req5In.bits.instrIdentAvailable && req5In.bits.slotAvailable) -> CacheLineState.Ready,
    (req5In.bits.reservedPendingSlot && (req5NeedsInstrWait || req5NeedsSlotWait)) ->
      CacheLineState.StoredInPendingTable))

  for (jInK <- 0 until params.jInK) {
    cacheLineResp(jInK).valid := req5In.valid && req5In.bits.jInK === jInK.U
    cacheLineResp(jInK).bits.slot := req5In.bits.slot
    cacheLineResp(jInK).bits.state := req5RespState
  }
  req5In.ready := cacheLineResp(req5In.bits.jInK).ready

  errors.freeEntryOverwrite := req5In.fire && req5NeedsStore && entries(freeEntry).valid
  when (req5In.fire && req5NeedsStore) {
    entriesNext(freeEntry).valid := true.B
    entriesNext(freeEntry).bits.state := MuxCase(KcePendingEntryState.WaitingForInstrIdent, Seq(
      req5NeedsInstrWait -> KcePendingEntryState.WaitingForInstrIdent,
      (req5NeedsSlotWait && !req5In.bits.slotClaimed) -> KcePendingEntryState.NeedsAlloc,
      (req5NeedsSlotWait && req5In.bits.slotClaimed) -> KcePendingEntryState.WaitingForSlotAvailable))
    entriesNext(freeEntry).bits.slot := req5In.bits.slot
    entriesNext(freeEntry).bits.pendingReq.jInK := req5In.bits.jInK
    entriesNext(freeEntry).bits.pendingReq.req := req5In.bits.req
  }

  pendingSlotReleaseReqCount := Mux(req5ReleasesReservation, 1.U, 0.U)
  pendingSlotReleaseReplayCount := Mux(replayRespFire, 1.U, 0.U)
  val pendingSlotReleaseCount = pendingSlotReleaseReqCount + pendingSlotReleaseReplayCount
  errors.pendingSlotsFreeOverflow :=
    pendingSlotsFree +& pendingSlotReleaseCount > params.kcePendingTableDepth.U +& pendingSlotReserveCount
  errors.pendingSlotsFreeUnderflow :=
    pendingSlotsFree +& pendingSlotReleaseCount < pendingSlotReserveCount

  pendingSlotsFreeNext := pendingSlotsFree - pendingSlotReserveCount + pendingSlotReleaseCount

  // ============================================================
  // identWake pending entries
  // ============================================================

  errors.instrStartedNotifyUnexpectedState :=
    VecInit((0 until params.kcePendingTableDepth).map { entry =>
      io.instrStartedNotify.valid &&
        entries(entry).valid &&
        entries(entry).bits.pendingReq.req.payload.ident === io.instrStartedNotify.bits &&
        entries(entry).bits.state =/= KcePendingEntryState.WaitingForInstrIdent
    }).asUInt.orR

  when (io.instrStartedNotify.valid) {
    for (entry <- 0 until params.kcePendingTableDepth) {
      val identNotifyMatchesEntry =
        entries(entry).valid &&
          entries(entry).bits.pendingReq.req.payload.ident === io.instrStartedNotify.bits
      val identNotifyExpectedState =
        entries(entry).bits.state === KcePendingEntryState.WaitingForInstrIdent

      when (
        identNotifyMatchesEntry && identNotifyExpectedState
      ) {
        entriesNext(entry).bits.state := KcePendingEntryState.NeedsAlloc
      }
    }
  }

  // ============================================================
  // alloc pending entries
  // ============================================================

  // Entry state carries the alloc pipeline phase. These stage boundaries must
  // be registered so a row observes NeedsAlloc -> WaitingForAllocResp before an
  // alloc response can update it again.
  require(ptp.alloc01FB, "KcePendingTable alloc0->alloc1 requires a forward buffer")
  require(ptp.alloc12FB, "KcePendingTable alloc1->alloc2 requires a forward buffer")

  val alloc0Matches = VecInit((0 until params.kcePendingTableDepth).map { entry =>
    entries(entry).valid &&
      entries(entry).bits.state === KcePendingEntryState.NeedsAlloc
  })
  val alloc0HasMatch = alloc0Matches.asUInt.orR
  val alloc0Entry = PriorityEncoder(alloc0Matches)
  val alloc0Out = Wire(Decoupled(UInt(entryIndexWidth.W)))
  val alloc1In = DoubleBuffer(alloc0Out, ptp.alloc01FB, ptp.alloc01BB)

  alloc0Out.valid := alloc0HasMatch
  alloc0Out.bits := alloc0Entry
  when (alloc0Out.fire) {
    entriesNext(alloc0Entry).bits.state := KcePendingEntryState.WaitingForAllocResp
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

  val allocRespSlotAvailable =
    allocSlotResp.bits.state === KceCacheSlotState.PresentClean ||
      allocSlotResp.bits.state === KceCacheSlotState.PresentDirty

  allocSlotResp.ready := alloc2In.valid
  errors.allocRespUnexpectedState :=
    allocSlotResp.fire &&
      (!entries(alloc2In.bits).valid ||
        entries(alloc2In.bits).bits.state =/= KcePendingEntryState.WaitingForAllocResp)
  when (allocSlotResp.fire) {
    entriesNext(alloc2In.bits).bits.state := Mux(
      allocRespSlotAvailable,
      KcePendingEntryState.ReadyToReplay,
      KcePendingEntryState.WaitingForSlotAvailable)
    entriesNext(alloc2In.bits).bits.slot := allocSlotResp.bits.slot
  }
  alloc2In.ready := allocSlotResp.valid

  // ============================================================
  // wake pending entries
  // ============================================================

  errors.slotAvailableUnexpectedState :=
    VecInit((0 until params.kcePendingTableDepth).map { entry =>
      slotIsAvailable.valid &&
        entries(entry).valid &&
        entries(entry).bits.slot === slotIsAvailable.bits &&
        entries(entry).bits.state === KcePendingEntryState.ReadyToReplay
    }).asUInt.orR

  for (entry <- 0 until params.kcePendingTableDepth) {
    val slotAvailableMatchesEntry =
      slotIsAvailable.valid &&
        entries(entry).valid &&
        entries(entry).bits.slot === slotIsAvailable.bits
    val slotAvailableExpectedState =
      entries(entry).bits.state === KcePendingEntryState.WaitingForSlotAvailable

    when (
        slotAvailableMatchesEntry && slotAvailableExpectedState
    ) {
      entriesNext(entry).bits.state := KcePendingEntryState.ReadyToReplay
    }
  }

  // ============================================================
  // replay ready pending entries
  // ============================================================

  val replayMatches = VecInit((0 until params.kcePendingTableDepth).map { entry =>
    entries(entry).valid &&
      entries(entry).bits.state === KcePendingEntryState.ReadyToReplay
  })
  // FIXME: This is fixed priority for the first pass. Consider round-robin if
  // ready low-index entries can starve higher-index entries.
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
