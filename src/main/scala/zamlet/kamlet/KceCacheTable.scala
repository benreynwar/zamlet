package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.{DoubleBuffer, ValidBuffer}

class KceCacheSlot(params: ZamletParams) extends Bundle {
  val addr = params.cacheLineAddr()
  val state = KceCacheSlotState()
  // Number of decoupled users that have claimed this slot and not released it.
  val activeUses = UInt(log2Ceil(params.kceCacheTableParams.maxActiveUsesPerCacheSlot + 1).W)
  // Second-chance bit. Claims set it; the scanner clears it before eviction.
  val recentlyUsed = Bool()
}

// Request from the metadata table to the Memlet interface to fetch a line into
// a newly allocated cache slot.
class KceFetchSlotReq(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val addr = params.cacheLineAddr()
}

// Request from the scanner to write back a dirty line before invalidating it.
class KceWritebackSlotReq(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val addr = params.cacheLineAddr()
}

// Scanner-owned writeback completion after it decides whether the emptied slot
// entered its internal empty-slot queue.
class KceWritebackComplete(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val inEmptyQueue = Bool()
}

object KceScannerSlotUpdateType extends ChiselEnum {
  val InvalidateClean, EvictDirty, QueueEmpty = Value
}

class KceScannerSlotUpdate(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val updateType = KceScannerSlotUpdateType()
}

// Metadata returned to the scanner for one slot. `canEvict` already includes
// active-use and RS-window protection so the scanner does not need to know those details.
class KceCacheSlotScanState(params: ZamletParams) extends Bundle {
  val addr = params.cacheLineAddr()
  val state = KceCacheSlotState()
  val activeUses = UInt(log2Ceil(params.kceCacheTableParams.maxActiveUsesPerCacheSlot + 1).W)
  val recentlyUsed = Bool()
  val canEvict = Bool()
}

class KceCacheTableErrors extends Bundle {
  val activeUseOverflow = Bool()
  val releaseUnderflow = Bool()
  val badFetchCompleteState = Bool()
  val badScannerSlotUpdateState = Bool()
  val badWritebackCompleteState = Bool()
}

class KceCacheTableIO(params: ZamletParams) extends Bundle {
  // Claim/allocation requests from the pending table for JTE-originated cache misses.
  val pendingClaimSlotReq = Flipped(Decoupled(new KceClaimSlotReq(params)))
  val pendingClaimSlotResp = Decoupled(new KceClaimSlotResp(params))
  val pendingAllocSlotReq = Flipped(Decoupled(new KceAllocSlotReq(params)))
  val pendingAllocSlotResp = Decoupled(new KceAllocSlotResp(params))
  val pendingReleaseSlot = Flipped(Valid(new KceSlotRelease(params)))

  // Claim/allocation requests from KTE. KTE uses decoupled claims, so hits
  // increment activeUses and must later release.
  val kteClaimSlotReq = Flipped(Decoupled(new KceClaimSlotReq(params)))
  val kteClaimSlotResp = Decoupled(new KceClaimSlotResp(params))
  val kteReleaseSlot = Flipped(Valid(new KceSlotRelease(params)))
  val kteAllocSlotReq = Flipped(Decoupled(new KceAllocSlotReq(params)))
  val kteAllocSlotResp = Decoupled(new KceAllocSlotResp(params))

  // RS uses a deterministic-latency valid path. Hits are protected with the
  // local RS window instead of activeUses.
  val rsClaimSlotReq = Flipped(Valid(new KceClaimSlotReq(params)))
  val rsClaimSlotResp = Valid(new KceClaimSlotResp(params))

  // Broadcast when a fetching slot has received all Jamlet data and becomes usable.
  val slotIsAvailable = Valid(params.cacheSlot())

  // Empty slot supplied by KceScanner's internal empty-slot queue for a new allocation.
  val emptySlot = Flipped(Decoupled(params.cacheSlot()))

  // Fetch request/completion boundary with KceMemletInterface.
  val memletFetchReq = Decoupled(new KceFetchSlotReq(params))
  val memletFetchComplete = Flipped(Valid(params.cacheSlot()))

  // Scanner query. The scanner chooses one slot index when valid; the table
  // returns the current metadata and whether it can be evicted now.
  val scannerSlotReq = Flipped(Decoupled(params.cacheSlot()))
  val scannerSlotResp = Decoupled(new KceCacheSlotScanState(params))

  // Scanner action. The scanner only emits this after checking scannerSlotResp.
  val scannerSlotUpdate = Flipped(Valid(new KceScannerSlotUpdate(params)))
  // Completion from KceScanner after dirty writeback is done.
  val scannerWritebackComplete = Flipped(Valid(new KceWritebackComplete(params)))

  val errors = Output(new KceCacheTableErrors)
}

class KceCacheTable(params: ZamletParams) extends Module {
  val io = IO(new KceCacheTableIO(params))
  val ctp = params.kceCacheTableParams

  private val activeUseWidth = log2Ceil(params.kceCacheTableParams.maxActiveUsesPerCacheSlot + 1)
  private val activeUseMax =
    params.kceCacheTableParams.maxActiveUsesPerCacheSlot.U(activeUseWidth.W)

  // ============================================================
  // Cache slot metadata
  // ============================================================

  val slotsInitial = Wire(Vec(params.nCacheSlots, new KceCacheSlot(params)))
  slotsInitial := 0.U.asTypeOf(slotsInitial)
  for (slot <- 0 until params.nCacheSlots) {
    slotsInitial(slot).state := KceCacheSlotState.Empty
    slotsInitial(slot).activeUses := 0.U
    slotsInitial(slot).recentlyUsed := false.B
  }

  val slotsNext = Wire(Vec(params.nCacheSlots, new KceCacheSlot(params)))
  val slots = RegEnable(slotsNext, slotsInitial, true.B)
  slotsNext := slots

  // ============================================================
  // Input buffering
  // ============================================================

  val pendingClaimSlotReq =
    DoubleBuffer(io.pendingClaimSlotReq, ctp.hasSlotReqFB, ctp.hasSlotReqBB)
  val pendingClaimSlotResp = Wire(Decoupled(new KceClaimSlotResp(params)))
  io.pendingClaimSlotResp <> DoubleBuffer(
    pendingClaimSlotResp, ctp.hasSlotRespFB, ctp.hasSlotRespBB)

  val kteClaimSlotReq =
    DoubleBuffer(io.kteClaimSlotReq, ctp.hasSlotReqFB, ctp.hasSlotReqBB)
  val kteClaimSlotResp = Wire(Decoupled(new KceClaimSlotResp(params)))
  io.kteClaimSlotResp <> DoubleBuffer(
    kteClaimSlotResp, ctp.hasSlotRespFB, ctp.hasSlotRespBB)

  val rsClaimSlotReq = ValidBuffer(io.rsClaimSlotReq, ctp.rsHasSlotReqBuffer)
  val rsClaimSlotResp = Wire(Valid(new KceClaimSlotResp(params)))
  io.rsClaimSlotResp := ValidBuffer(rsClaimSlotResp, ctp.rsHasSlotRespBuffer)

  val pendingAllocSlotReq =
    DoubleBuffer(io.pendingAllocSlotReq, ctp.allocSlotReqFB, ctp.allocSlotReqBB)
  val pendingAllocSlotResp = Wire(Decoupled(new KceAllocSlotResp(params)))
  io.pendingAllocSlotResp <> DoubleBuffer(
    pendingAllocSlotResp, ctp.allocSlotRespFB, ctp.allocSlotRespBB)

  val kteAllocSlotReq =
    DoubleBuffer(io.kteAllocSlotReq, ctp.allocSlotReqFB, ctp.allocSlotReqBB)
  val kteAllocSlotResp = Wire(Decoupled(new KceAllocSlotResp(params)))
  io.kteAllocSlotResp <> DoubleBuffer(
    kteAllocSlotResp, ctp.allocSlotRespFB, ctp.allocSlotRespBB)

  // ============================================================
  // Lookup helpers
  // ============================================================

  def slotMatches(addr: UInt): Vec[Bool] = {
    VecInit((0 until params.nCacheSlots).map { slot =>
      slots(slot).state =/= KceCacheSlotState.Empty &&
        slots(slot).state =/= KceCacheSlotState.EmptyInQueue &&
        slots(slot).addr === addr
    })
  }

  def claimLookup(req: KceClaimSlotReq): KceClaimSlotResp = {
    val resp = Wire(new KceClaimSlotResp(params))
    val matches = slotMatches(req.cacheLineAddr)
    val hasMatch = matches.asUInt.orR
    val slot = PriorityEncoder(matches)

    resp.hasSlot := hasMatch
    resp.slot := slot
    resp.state := Mux(hasMatch, slots(slot).state, KceCacheSlotState.Empty)
    resp
  }

  def allocExistingSlotLookup(addr: UInt) = {
    val resp = Wire(Valid(params.cacheSlot()))
    val matches = slotMatches(addr)
    resp.valid := matches.asUInt.orR
    resp.bits := PriorityEncoder(matches)
    resp
  }

  def isPresent(state: KceCacheSlotState.Type): Bool = {
    state === KceCacheSlotState.PresentClean || state === KceCacheSlotState.PresentDirty
  }

  def isFetching(state: KceCacheSlotState.Type): Bool = {
    state === KceCacheSlotState.Fetching || state === KceCacheSlotState.FetchingWillWrite
  }

  def canClaim(req: KceClaimSlotReq, state: KceCacheSlotState.Type): Bool = {
    isPresent(state) || (req.claimIfFetching && isFetching(state))
  }

  def markWillWrite(state: KceCacheSlotState.Type): KceCacheSlotState.Type = {
    MuxCase(state, Seq(
      (state === KceCacheSlotState.Fetching) -> KceCacheSlotState.FetchingWillWrite,
      (state === KceCacheSlotState.PresentClean) -> KceCacheSlotState.PresentDirty))
  }

  // ============================================================
  // Claim slot pipeline
  // ============================================================

  val pendingClaimSelected = !rsClaimSlotReq.valid && pendingClaimSlotReq.valid
  val kteClaimSelected =
    !rsClaimSlotReq.valid && !pendingClaimSlotReq.valid && kteClaimSlotReq.valid

  rsClaimSlotResp.valid := rsClaimSlotReq.valid
  rsClaimSlotResp.bits := claimLookup(rsClaimSlotReq.bits)

  pendingClaimSlotResp.valid := pendingClaimSelected
  pendingClaimSlotResp.bits := claimLookup(pendingClaimSlotReq.bits)
  pendingClaimSlotReq.ready := pendingClaimSelected && pendingClaimSlotResp.ready

  kteClaimSlotResp.valid := kteClaimSelected
  kteClaimSlotResp.bits := claimLookup(kteClaimSlotReq.bits)
  kteClaimSlotReq.ready := kteClaimSelected && kteClaimSlotResp.ready

  val pendingClaimFire =
    pendingClaimSlotReq.fire &&
      pendingClaimSlotResp.bits.hasSlot &&
      canClaim(pendingClaimSlotReq.bits, pendingClaimSlotResp.bits.state)
  val kteClaimFire =
    kteClaimSlotReq.fire &&
      kteClaimSlotResp.bits.hasSlot &&
      canClaim(kteClaimSlotReq.bits, kteClaimSlotResp.bits.state)
  val rsClaimFire =
    rsClaimSlotReq.valid &&
      rsClaimSlotResp.bits.hasSlot &&
      canClaim(rsClaimSlotReq.bits, rsClaimSlotResp.bits.state)

  val pendingClaimSlot = pendingClaimSlotResp.bits.slot
  val kteClaimSlot = kteClaimSlotResp.bits.slot
  val rsClaimSlot = rsClaimSlotResp.bits.slot

  val pendingClaimWillDirty =
    pendingClaimFire &&
    pendingClaimSlotReq.bits.willWrite
  val kteClaimWillDirty =
    kteClaimFire &&
    kteClaimSlotReq.bits.willWrite
  val rsClaimWillDirty =
    rsClaimFire &&
    rsClaimSlotReq.bits.willWrite

  // ============================================================
  // RS deterministic-use window
  // ============================================================

  private val rsUseWindowDepth = params.sramParams.localResponseLatency + 2
  val rsUseWindowInitial = Wire(Vec(rsUseWindowDepth, Valid(params.cacheSlot())))
  rsUseWindowInitial := 0.U.asTypeOf(rsUseWindowInitial)
  val rsUseWindowNext = Wire(Vec(rsUseWindowDepth, Valid(params.cacheSlot())))
  val rsUseWindow = RegEnable(rsUseWindowNext, rsUseWindowInitial, true.B)
  rsUseWindowNext(0).valid := rsClaimFire
  rsUseWindowNext(0).bits := rsClaimSlot
  for (idx <- 1 until rsUseWindowDepth) {
    rsUseWindowNext(idx) := rsUseWindow(idx - 1)
  }

  val rsWindowProtected = VecInit((0 until params.nCacheSlots).map { slot =>
    VecInit((0 until rsUseWindowDepth).map { idx =>
      rsUseWindow(idx).valid && rsUseWindow(idx).bits === slot.U
    }).asUInt.orR
  })

  // ============================================================
  // Allocation pipeline
  // ============================================================

  val allocPendingSelected = pendingAllocSlotReq.valid
  val allocKteSelected = !pendingAllocSlotReq.valid && kteAllocSlotReq.valid
  val allocSelected = allocPendingSelected || allocKteSelected
  val allocReq = Wire(new KceAllocSlotReq(params))
  allocReq := Mux(allocPendingSelected, pendingAllocSlotReq.bits, kteAllocSlotReq.bits)

  val allocExistingSlot = allocExistingSlotLookup(allocReq.cacheLineAddr)
  val allocUsesEmptySlot = allocSelected && !allocExistingSlot.valid
  val allocCanUseEmptySlot = allocUsesEmptySlot && io.emptySlot.valid && io.memletFetchReq.ready
  val allocCanRespond = allocExistingSlot.valid || allocCanUseEmptySlot
  val allocRespSlot = Mux(
    allocExistingSlot.valid,
    allocExistingSlot.bits,
    io.emptySlot.bits)

  pendingAllocSlotResp.valid := allocPendingSelected && allocCanRespond
  pendingAllocSlotResp.bits.slot := allocRespSlot
  pendingAllocSlotReq.ready :=
    allocPendingSelected && allocCanRespond && pendingAllocSlotResp.ready

  kteAllocSlotResp.valid := allocKteSelected && allocCanRespond
  kteAllocSlotResp.bits.slot := allocRespSlot
  kteAllocSlotReq.ready := allocKteSelected && allocCanRespond && kteAllocSlotResp.ready

  val allocFire = Mux(
    allocPendingSelected,
    pendingAllocSlotReq.fire,
    allocKteSelected && kteAllocSlotReq.fire)
  val allocEmptySlotFire = allocFire && !allocExistingSlot.valid
  val allocExistingSlotFire = allocFire && allocExistingSlot.valid

  io.emptySlot.ready := allocEmptySlotFire
  io.memletFetchReq.valid := allocEmptySlotFire
  io.memletFetchReq.bits.slot := io.emptySlot.bits
  io.memletFetchReq.bits.addr := allocReq.cacheLineAddr

  when (allocEmptySlotFire) {
    slotsNext(io.emptySlot.bits).addr := allocReq.cacheLineAddr
    slotsNext(io.emptySlot.bits).state := Mux(
      allocReq.willWrite,
      KceCacheSlotState.FetchingWillWrite,
      KceCacheSlotState.Fetching)
    slotsNext(io.emptySlot.bits).activeUses := 0.U
    slotsNext(io.emptySlot.bits).recentlyUsed := true.B
  }

  when (allocExistingSlotFire && allocReq.willWrite) {
    slotsNext(allocExistingSlot.bits).state := markWillWrite(slots(allocExistingSlot.bits).state)
  }

  // ============================================================
  // Release and active-use updates
  // ============================================================

  val releaseBySlot = Wire(Vec(params.nCacheSlots, UInt(activeUseWidth.W)))
  val claimBySlot = Wire(Vec(params.nCacheSlots, UInt(activeUseWidth.W)))
  for (slot <- 0 until params.nCacheSlots) {
    releaseBySlot(slot) :=
      (io.pendingReleaseSlot.valid && io.pendingReleaseSlot.bits.slot === slot.U).asUInt +
        (io.kteReleaseSlot.valid && io.kteReleaseSlot.bits.slot === slot.U).asUInt

    claimBySlot(slot) :=
      (pendingClaimFire && pendingClaimSlot === slot.U).asUInt +
        (kteClaimFire && kteClaimSlot === slot.U).asUInt
  }

  val activeUseOverflowVec = Wire(Vec(params.nCacheSlots, Bool()))
  val releaseUnderflowVec = Wire(Vec(params.nCacheSlots, Bool()))
  for (slot <- 0 until params.nCacheSlots) {
    activeUseOverflowVec(slot) :=
      slots(slot).activeUses + claimBySlot(slot) > activeUseMax
    releaseUnderflowVec(slot) := slots(slot).activeUses + claimBySlot(slot) < releaseBySlot(slot)

    when (claimBySlot(slot) =/= 0.U || releaseBySlot(slot) =/= 0.U) {
      slotsNext(slot).activeUses :=
        slots(slot).activeUses + claimBySlot(slot) - releaseBySlot(slot)
    }
    when (claimBySlot(slot) =/= 0.U) {
      slotsNext(slot).recentlyUsed := true.B
    }
  }

  // ============================================================
  // Dirty marking
  // ============================================================

  when (pendingClaimWillDirty) {
    slotsNext(pendingClaimSlot).state := markWillWrite(slots(pendingClaimSlot).state)
  }
  when (kteClaimWillDirty) {
    slotsNext(kteClaimSlot).state := markWillWrite(slots(kteClaimSlot).state)
  }
  when (rsClaimWillDirty) {
    slotsNext(rsClaimSlot).state := markWillWrite(slots(rsClaimSlot).state)
  }

  // ============================================================
  // Fetch/writeback completion and slot availability
  // ============================================================

  val slotIsAvailable = Wire(Valid(params.cacheSlot()))
  io.slotIsAvailable := ValidBuffer(slotIsAvailable, ctp.slotIsAvailableBuffer)
  slotIsAvailable.valid := false.B
  slotIsAvailable.bits := DontCare

  val fetchCompleteState = slots(io.memletFetchComplete.bits).state
  val fetchCompleteStateWillWrite = fetchCompleteState === KceCacheSlotState.FetchingWillWrite
  val fetchCompleteStateIsValid =
    fetchCompleteState === KceCacheSlotState.Fetching || fetchCompleteStateWillWrite
  when (io.memletFetchComplete.valid) {
    slotsNext(io.memletFetchComplete.bits).state := Mux(
      fetchCompleteStateWillWrite,
      KceCacheSlotState.PresentDirty,
      KceCacheSlotState.PresentClean)
    slotIsAvailable.valid := true.B
    slotIsAvailable.bits := io.memletFetchComplete.bits
  }

  val writebackCompleteSlot = io.scannerWritebackComplete.bits.slot
  val writebackCompleteState = slots(writebackCompleteSlot).state
  val writebackCompleteStateIsValid = writebackCompleteState === KceCacheSlotState.Evicting
  when (io.scannerWritebackComplete.valid) {
    slotsNext(writebackCompleteSlot).state := Mux(
      io.scannerWritebackComplete.bits.inEmptyQueue,
      KceCacheSlotState.EmptyInQueue,
      KceCacheSlotState.Empty)
    slotsNext(writebackCompleteSlot).activeUses := 0.U
    slotsNext(writebackCompleteSlot).recentlyUsed := false.B
  }

  // ============================================================
  // Scanner metadata and state transitions
  // ============================================================

  val scannerSelectedSlot = io.scannerSlotReq.bits
  val scannerSelectedCanEvict =
    slots(scannerSelectedSlot).activeUses === 0.U && !rsWindowProtected(scannerSelectedSlot)
  io.scannerSlotReq.ready := io.scannerSlotResp.ready
  io.scannerSlotResp.valid := io.scannerSlotReq.valid
  io.scannerSlotResp.bits.addr := slots(scannerSelectedSlot).addr
  io.scannerSlotResp.bits.state := slots(scannerSelectedSlot).state
  io.scannerSlotResp.bits.activeUses := slots(scannerSelectedSlot).activeUses
  io.scannerSlotResp.bits.recentlyUsed := slots(scannerSelectedSlot).recentlyUsed
  io.scannerSlotResp.bits.canEvict := scannerSelectedCanEvict

  when (io.scannerSlotReq.fire &&
      scannerSelectedCanEvict &&
      slots(scannerSelectedSlot).recentlyUsed &&
      isPresent(slots(scannerSelectedSlot).state)) {
    slotsNext(scannerSelectedSlot).recentlyUsed := false.B
  }

  val scannerSlotUpdateSlot = io.scannerSlotUpdate.bits.slot
  val scannerSlotUpdateState = slots(scannerSlotUpdateSlot).state
  val scannerSlotUpdateCanChange =
    slots(scannerSlotUpdateSlot).activeUses === 0.U && !rsWindowProtected(scannerSlotUpdateSlot)
  val scannerSlotUpdateStateIsValid =
    scannerSlotUpdateCanChange &&
      MuxLookup(io.scannerSlotUpdate.bits.updateType.asUInt, false.B)(Seq(
        KceScannerSlotUpdateType.InvalidateClean.asUInt ->
          (scannerSlotUpdateState === KceCacheSlotState.PresentClean),
        KceScannerSlotUpdateType.EvictDirty.asUInt ->
          (scannerSlotUpdateState === KceCacheSlotState.PresentDirty),
        KceScannerSlotUpdateType.QueueEmpty.asUInt ->
          (scannerSlotUpdateState === KceCacheSlotState.Empty)))

  when (io.scannerSlotUpdate.valid) {
    switch (io.scannerSlotUpdate.bits.updateType) {
      is (KceScannerSlotUpdateType.InvalidateClean) {
        slotsNext(scannerSlotUpdateSlot).state := KceCacheSlotState.EmptyInQueue
        slotsNext(scannerSlotUpdateSlot).activeUses := 0.U
        slotsNext(scannerSlotUpdateSlot).recentlyUsed := false.B
      }
      is (KceScannerSlotUpdateType.EvictDirty) {
        slotsNext(scannerSlotUpdateSlot).state := KceCacheSlotState.Evicting
      }
      is (KceScannerSlotUpdateType.QueueEmpty) {
        slotsNext(scannerSlotUpdateSlot).state := KceCacheSlotState.EmptyInQueue
        slotsNext(scannerSlotUpdateSlot).activeUses := 0.U
        slotsNext(scannerSlotUpdateSlot).recentlyUsed := false.B
      }
    }
  }

  // ============================================================
  // Errors
  // ============================================================

  val errorsNext = Wire(new KceCacheTableErrors)
  errorsNext.activeUseOverflow := activeUseOverflowVec.asUInt.orR
  errorsNext.releaseUnderflow := releaseUnderflowVec.asUInt.orR
  errorsNext.badFetchCompleteState := io.memletFetchComplete.valid && !fetchCompleteStateIsValid
  errorsNext.badScannerSlotUpdateState :=
    io.scannerSlotUpdate.valid && !scannerSlotUpdateStateIsValid
  errorsNext.badWritebackCompleteState :=
    io.scannerWritebackComplete.valid && !writebackCompleteStateIsValid
  io.errors := RegNext(errorsNext)
}
