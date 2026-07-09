package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.TagTableParams
import zamlet.utils.{BroadcastUpdateBuffer, DoubleBuffer, ValidBuffer}

object TagState extends ChiselEnum {
  val Empty = Value
  val EmptyInQueue = Value
  val ReservedClean = Value
  val ReservedDirty = Value
  val FillingClean = Value
  val FillingDirty = Value
  val PresentClean = Value
  val PresentDirty = Value
  val Evicting = Value
  val PresentDirtyCancelledEviction = Value
}

class TagTableErrors extends Bundle {
  val allocBadState = Bool()
  val allocBadUses = Bool()
  val allocUsesOverflow = Bool()
  val allocRecentlyUsed = Bool()
  val fillBadState = Bool()
  val writebackCompleteBadState = Bool()
  val writebackCompleteQueueNotReady = Bool()
  val releaseUnderflow = Bool()
}

class TagAllocReq[R <: Data, F <: Data](tagWidth: Int, respMetaType: R, fillMetaType: F) extends Bundle {
  val tag = UInt(tagWidth.W)
  val willWrite = Bool()
  val meta = respMetaType.cloneType
  val fillMeta = fillMetaType.cloneType
}

class TagAllocResp[R <: Data, P <: Data](slotWidth: Int, respMetaType: R, payloadType: P) extends Bundle {
  val slot = UInt(slotWidth.W)
  val state = TagState()
  val didAlloc = Bool()
  val meta = respMetaType.cloneType
  val payload = payloadType.cloneType
}

class TagClaimReq[R <: Data](tagWidth: Int, respMetaType: R) extends Bundle {
  val tag = UInt(tagWidth.W)
  val willWrite = Bool()
  val doClaim = Bool()
  val claimIfPendingFill = Bool()
  val meta = respMetaType.cloneType
}

class TagClaimResp[R <: Data, P <: Data](slotWidth: Int, respMetaType: R, payloadType: P) extends Bundle {
  val hasSlot = Bool()
  val slot = UInt(slotWidth.W)
  val state = TagState()
  val didClaim = Bool()
  val meta = respMetaType.cloneType
  val payload = payloadType.cloneType
}

class TagFillReq[F <: Data](tagWidth: Int, slotWidth: Int, fillMetaType: F) extends Bundle {
  val slot = UInt(slotWidth.W)
  val tag = UInt(tagWidth.W)
  val meta = fillMetaType.cloneType
}

class TagFillComplete[P <: Data](slotWidth: Int, payloadType: P) extends Bundle {
  val slot = UInt(slotWidth.W)
  val payload = payloadType.cloneType
}

class TagWritebackReq[P <: Data](tagWidth: Int, slotWidth: Int, payloadType: P) extends Bundle {
  val slot = UInt(slotWidth.W)
  val tag = UInt(tagWidth.W)
  val payload = payloadType.cloneType
}

class SlotMeta[F <: Data, P <: Data](
  tagWidth: Int,
  nUsesWidth: Int,
  fillMetaType: F,
  payloadType: P,
) extends Bundle {
  val state = TagState()
  val nUses = UInt(nUsesWidth.W)
  val recentlyUsed = Bool()
  val tag = UInt(tagWidth.W)
  val fillMeta = fillMetaType.cloneType
  val payload = payloadType.cloneType
}

class Alloc0Result[R <: Data, F <: Data](
  tagWidth: Int,
  slotWidth: Int,
  respMetaType: R,
  fillMetaType: F,
) extends Bundle {
  val tag = UInt(tagWidth.W)
  val willWrite = Bool()
  val meta = respMetaType.cloneType
  val fillMeta = fillMetaType.cloneType
  val hit = Bool()
  val hitSlot = UInt(slotWidth.W)
  val hitState = TagState()
}

class Scan0Result(slotWidth: Int, nUsesWidth: Int) extends Bundle {
  val slot = UInt(slotWidth.W)
  val state = TagState()
  val nUses = UInt(nUsesWidth.W)
  val recentlyUsed = Bool()
}

class TagTableIO[R <: Data, F <: Data, P <: Data](
  tagWidth: Int,
  slotWidth: Int,
  params: TagTableParams,
  respMetaType: R,
  fillMetaType: F,
  payloadType: P,
) extends Bundle {
  // Lookup an existing tag and claim the slot if it is currently claimable.
  val claimReq = Flipped(Valid(new TagClaimReq(tagWidth, respMetaType)))
  val claimResp = Valid(new TagClaimResp(slotWidth, respMetaType, payloadType))

  // Allocate a slot for a tag, or return an existing live matching slot.
  val allocReq = Flipped(Decoupled(new TagAllocReq(tagWidth, respMetaType, fillMetaType)))
  val allocResp = Decoupled(new TagAllocResp(slotWidth, respMetaType, payloadType))

  // Request payload/tag data installation for a reserved slot.
  val fillReq = Decoupled(new TagFillReq(tagWidth, slotWidth, fillMetaType))
  // Mark a Filling slot Present after its payload/tag data has been installed.
  val fillComplete = Flipped(Valid(new TagFillComplete(slotWidth, payloadType)))
  // If this arrives in the same cycle as a matching slotStatusResp, the
  // response already includes this fill-complete update.
  val fillCompleteForSlotStatusResp = Valid(new TagFillComplete(slotWidth, payloadType))
  // If this arrives in the same cycle as a matching allocResp, the response
  // already includes this fill-complete update.
  val fillCompleteForAllocResp = Valid(new TagFillComplete(slotWidth, payloadType))
  // Record completion of one consumer use; decrements nUses.
  val release = Flipped(Valid(UInt(slotWidth.W)))

  // Dirty-slot writeback handoff before a reusable slot can become free.
  val writebackReq = Decoupled(new TagWritebackReq(tagWidth, slotWidth, payloadType))
  val writebackComplete = Flipped(Valid(UInt(slotWidth.W)))

  // Registered read of current lifecycle state by slot.
  val slotStatusReq = Flipped(Valid(UInt(slotWidth.W)))
  val slotStatusResp = Valid(TagState())

  // Registered transition errors from the table.
  val errors = Output(new TagTableErrors)
}

class TagTable[R <: Data, F <: Data, P <: Data](
  tagWidth: Int,
  slotWidth: Int,
  nUsesWidth: Int,
  params: TagTableParams,
  respMetaType: R,
  fillMetaType: F,
  payloadType: P,
) extends Module {
  require(tagWidth > 0)
  require(slotWidth > 0)
  require(nUsesWidth > 0)
  require(params.freeQueueDepth > 1)
  require(params.fillReqQueueDepth > 1)
  require(params.scanBackpressureDepth > 0)
  require(params.scanBackpressureDepth <= params.freeQueueDepth)

  private val nSlots = 1 << slotWidth
  private val freePtrWidth = log2Ceil(params.freeQueueDepth)
  private val freeCountWidth = log2Ceil(params.freeQueueDepth + 1)
  private def slotMetaType = new SlotMeta(tagWidth, nUsesWidth, fillMetaType, payloadType)

  val io = IO(new TagTableIO(tagWidth, slotWidth, params, respMetaType, fillMetaType, payloadType))

  // ============================================================
  // Helpers
  // ============================================================

  def incrSlot(slot: UInt): UInt = {
    Mux(slot === (nSlots - 1).U, 0.U, slot + 1.U)
  }

  def incrFreePtr(ptr: UInt): UInt = {
    Mux(ptr === (params.freeQueueDepth - 1).U, 0.U, ptr + 1.U)
  }

  def isLive(state: TagState.Type): Bool = {
    state === TagState.ReservedClean ||
      state === TagState.ReservedDirty ||
      state === TagState.FillingClean ||
      state === TagState.FillingDirty ||
      state === TagState.PresentClean ||
      state === TagState.PresentDirty ||
      state === TagState.Evicting ||
      state === TagState.PresentDirtyCancelledEviction
  }

  def isReserved(state: TagState.Type): Bool = {
    state === TagState.ReservedClean || state === TagState.ReservedDirty
  }

  def isPresent(state: TagState.Type): Bool = {
    state === TagState.PresentClean ||
      state === TagState.PresentDirty ||
      state === TagState.PresentDirtyCancelledEviction
  }

  def isFilling(state: TagState.Type): Bool = {
    state === TagState.FillingClean || state === TagState.FillingDirty
  }

  def isClaimable(req: TagClaimReq[R], state: TagState.Type): Bool = {
    isPresent(state) || (req.claimIfPendingFill && (isReserved(state) || isFilling(state)))
  }

  def markDirty(state: TagState.Type): TagState.Type = {
    MuxCase(state, Seq(
      (state === TagState.ReservedClean) -> TagState.ReservedDirty,
      (state === TagState.FillingClean) -> TagState.FillingDirty,
      (state === TagState.PresentClean) -> TagState.PresentDirty))
  }

  val maxUses = ((BigInt(1) << nUsesWidth) - 1).U(nUsesWidth.W)

  // ============================================================
  // Slot Lifecycle State
  // ============================================================

  val slotMetaInitial = Wire(Vec(nSlots, slotMetaType))
  slotMetaInitial := 0.U.asTypeOf(Vec(nSlots, slotMetaType))
  for (slot <- 0 until nSlots) {
    slotMetaInitial(slot).state := TagState.Empty
  }
  val slotMetaNext = Wire(Vec(nSlots, slotMetaType))
  val slotMeta = RegNext(slotMetaNext, slotMetaInitial)

  val state = Wire(Vec(nSlots, TagState()))
  val nUses = Wire(Vec(nSlots, UInt(nUsesWidth.W)))
  val recentlyUsed = Wire(Vec(nSlots, Bool()))
  val tag = Wire(Vec(nSlots, UInt(tagWidth.W)))
  val fillMeta = Wire(Vec(nSlots, fillMetaType.cloneType))
  val payload = Wire(Vec(nSlots, payloadType.cloneType))
  for (slot <- 0 until nSlots) {
    state(slot) := slotMeta(slot).state
    nUses(slot) := slotMeta(slot).nUses
    recentlyUsed(slot) := slotMeta(slot).recentlyUsed
    tag(slot) := slotMeta(slot).tag
    fillMeta(slot) := slotMeta(slot).fillMeta
    payload(slot) := slotMeta(slot).payload
  }

  io.slotStatusResp.valid := RegNext(io.slotStatusReq.valid, false.B)
  io.slotStatusResp.bits := RegNext(state(io.slotStatusReq.bits))

  // ============================================================
  // Free Slot FIFO
  // ============================================================

  val freeSlotsNext = Wire(Vec(params.freeQueueDepth, UInt(slotWidth.W)))
  val freeSlots = RegNext(freeSlotsNext)
  freeSlotsNext := freeSlots

  val freeDeqPtrNext = Wire(UInt(freePtrWidth.W))
  val freeDeqPtr = RegNext(freeDeqPtrNext, 0.U)
  freeDeqPtrNext := freeDeqPtr

  val freeEnqPtrNext = Wire(UInt(freePtrWidth.W))
  val freeEnqPtr = RegNext(freeEnqPtrNext, 0.U)
  freeEnqPtrNext := freeEnqPtr

  val freeCountNext = Wire(UInt(freeCountWidth.W))
  val freeCount = RegNext(freeCountNext, 0.U)
  freeCountNext := freeCount

  val freeSlotDeq = Wire(Decoupled(UInt(slotWidth.W)))
  val cleanFreeSlotEnq = Wire(Decoupled(UInt(slotWidth.W)))
  val writebackFreeSlotEnq = Wire(Decoupled(UInt(slotWidth.W)))

  freeSlotDeq.valid := freeCount =/= 0.U
  freeSlotDeq.bits := freeSlots(freeDeqPtr)

  val cleanFreeSlotEnqBelowThreshold =
    freeCount < params.scanBackpressureDepth.U
  writebackFreeSlotEnq.ready := freeCount =/= params.freeQueueDepth.U
  cleanFreeSlotEnq.ready :=
    !writebackFreeSlotEnq.valid && cleanFreeSlotEnqBelowThreshold

  val writebackFreeSlotEnqFire =
    writebackFreeSlotEnq.valid && writebackFreeSlotEnq.ready
  val cleanFreeSlotEnqFire =
    cleanFreeSlotEnq.valid && cleanFreeSlotEnq.ready

  when (freeSlotDeq.fire) {
    freeDeqPtrNext := incrFreePtr(freeDeqPtr)
  }
  when (writebackFreeSlotEnqFire || cleanFreeSlotEnqFire) {
    freeSlotsNext(freeEnqPtr) := Mux(
      writebackFreeSlotEnqFire,
      writebackFreeSlotEnq.bits,
      cleanFreeSlotEnq.bits)
    freeEnqPtrNext := incrFreePtr(freeEnqPtr)
  }
  freeCountNext :=
    freeCount +
      (writebackFreeSlotEnqFire || cleanFreeSlotEnqFire).asUInt -
      freeSlotDeq.fire.asUInt

  val errors = Wire(new TagTableErrors)
  errors := 0.U.asTypeOf(new TagTableErrors)

  // ============================================================
  // Fill Request FIFO
  // ============================================================

  val allocFillReqEnq = Wire(Decoupled(new TagFillReq(tagWidth, slotWidth, fillMetaType)))
  val scanFillReqEnq = Wire(Decoupled(new TagFillReq(tagWidth, slotWidth, fillMetaType)))
  val fillReqQueue = Module(new Queue(
    new TagFillReq(tagWidth, slotWidth, fillMetaType),
    params.fillReqQueueDepth))

  fillReqQueue.io.enq.valid := allocFillReqEnq.valid || scanFillReqEnq.valid
  fillReqQueue.io.enq.bits := Mux(allocFillReqEnq.valid, allocFillReqEnq.bits, scanFillReqEnq.bits)
  allocFillReqEnq.ready := fillReqQueue.io.enq.ready
  scanFillReqEnq.ready := !allocFillReqEnq.valid && fillReqQueue.io.enq.ready
  io.fillReq <> fillReqQueue.io.deq

  // ============================================================
  // alloc0: lookup an existing live tag
  // ============================================================

  val alloc0In = DoubleBuffer(io.allocReq, params.allocReqFB, params.allocReqBB)

  val alloc0Matches = Wire(Vec(nSlots, Bool()))
  for (slot <- 0 until nSlots) {
    alloc0Matches(slot) :=
      tag(slot) === alloc0In.bits.tag && isLive(state(slot))
  }
  val alloc0Hit = alloc0Matches.asUInt.orR
  val alloc0HitSlot = PriorityEncoder(alloc0Matches)

  val alloc0Out = Wire(Decoupled(new Alloc0Result(
    tagWidth,
    slotWidth,
    respMetaType,
    fillMetaType)))
  alloc0Out.bits.tag := alloc0In.bits.tag
  alloc0Out.bits.willWrite := alloc0In.bits.willWrite
  alloc0Out.bits.meta := alloc0In.bits.meta
  alloc0Out.bits.fillMeta := alloc0In.bits.fillMeta
  alloc0Out.bits.hit := alloc0Hit
  alloc0Out.bits.hitSlot := alloc0HitSlot
  alloc0Out.bits.hitState := Mux(alloc0Hit, state(alloc0HitSlot), TagState.Empty)

  // ============================================================
  // alloc1: respond to hits or merge misses with the free FIFO
  // ============================================================
  // Misses wait for a queued free slot. A miss allocation pops one slot from
  // the free FIFO, writes the tag, and changes the lifecycle state to Reserved.

  def updateAlloc0Result(
    result: Alloc0Result[R, F],
    fillComplete: TagFillComplete[P],
  ): Alloc0Result[R, F] = {
    val updated = Wire(new Alloc0Result(tagWidth, slotWidth, respMetaType, fillMetaType))
    updated := result
    when (result.hit && result.hitSlot === fillComplete.slot) {
      when (result.hitState === TagState.FillingClean) {
        updated.hitState := TagState.PresentClean
      } .elsewhen (result.hitState === TagState.FillingDirty) {
        updated.hitState := TagState.PresentDirty
      }
    }
    updated
  }

  // Raw fillComplete updates table state this cycle. The registered copy is
  // grouped with the next cycle's state-derived responses.
  val fillCompleteForStateResp = RegNext(io.fillComplete, 0.U.asTypeOf(io.fillComplete))

  val alloc01Buffer = Module(new BroadcastUpdateBuffer(
    alloc0Out.bits.cloneType,
    new TagFillComplete(slotWidth, payloadType),
    updateAlloc0Result,
    params.alloc01FB,
    params.alloc01BB))
  alloc01Buffer.io.i <> alloc0Out
  alloc01Buffer.io.broadcastIn := fillCompleteForStateResp
  val alloc1In = alloc01Buffer.io.o
  val alloc1Out = Wire(Decoupled(new TagAllocResp(slotWidth, respMetaType, payloadType)))

  // Same-tag misses already buffered between alloc0 and alloc1 are older than
  // alloc0In, but are not visible in the registered tag table yet.
  val alloc01OutSameTagMiss =
    alloc1In.valid && alloc01Buffer.io.fromState && !alloc1In.bits.hit &&
      alloc1In.bits.tag === alloc0In.bits.tag
  val alloc01HiddenSameTagMiss =
    alloc01Buffer.io.hidden.valid && !alloc01Buffer.io.hidden.bits.hit &&
      alloc01Buffer.io.hidden.bits.tag === alloc0In.bits.tag
  val alloc0WaitForSameTagMiss =
    alloc01OutSameTagMiss || alloc01HiddenSameTagMiss

  alloc0In.ready := alloc0Out.ready && !alloc0WaitForSameTagMiss
  alloc0Out.valid := alloc0In.valid && !alloc0WaitForSameTagMiss

  val alloc1HitUsesAvailable = nUses(alloc1In.bits.hitSlot) =/= maxUses
  val alloc1CanRespond = Mux(alloc1In.bits.hit, true.B, freeSlotDeq.valid)
  val alloc1ReclaimsEviction =
    alloc1In.bits.hit && alloc1In.bits.hitState === TagState.Evicting
  val alloc1HitRespState = Mux(
    alloc1ReclaimsEviction,
    TagState.PresentDirty,
    alloc1In.bits.hitState)
  alloc1In.ready := alloc1Out.ready && alloc1CanRespond
  alloc1Out.valid := alloc1In.valid && alloc1CanRespond
  alloc1Out.bits.slot := Mux(alloc1In.bits.hit, alloc1In.bits.hitSlot, freeSlotDeq.bits)
  alloc1Out.bits.didAlloc := !alloc1In.bits.hit
  alloc1Out.bits.meta := alloc1In.bits.meta
  alloc1Out.bits.payload := payload(alloc1Out.bits.slot)
  val alloc1MissState = Mux(
    allocFillReqEnq.ready,
    Mux(alloc1In.bits.willWrite, TagState.FillingDirty, TagState.FillingClean),
    Mux(alloc1In.bits.willWrite, TagState.ReservedDirty, TagState.ReservedClean))
  alloc1Out.bits.state := Mux(alloc1In.bits.hit, alloc1HitRespState, alloc1MissState)
  freeSlotDeq.ready := alloc1In.valid && !alloc1In.bits.hit && alloc1Out.ready

  def updateAllocResp(
    resp: TagAllocResp[R, P],
    fillComplete: TagFillComplete[P],
  ): TagAllocResp[R, P] = {
    val updated = Wire(new TagAllocResp(slotWidth, respMetaType, payloadType))
    updated := resp
    when (resp.slot === fillComplete.slot) {
      when (resp.state === TagState.FillingClean) {
        updated.state := TagState.PresentClean
        updated.payload := fillComplete.payload
      } .elsewhen (resp.state === TagState.FillingDirty) {
        updated.state := TagState.PresentDirty
        updated.payload := fillComplete.payload
      }
    }
    updated
  }

  // This is the timing buffer for allocResp. If a response waits here while a
  // matching fillComplete passes it, update the delayed response so it remains
  // consistent with the table state.
  val allocRespBuffer = Module(new BroadcastUpdateBuffer(
    new TagAllocResp(slotWidth, respMetaType, payloadType),
    new TagFillComplete(slotWidth, payloadType),
    updateAllocResp,
    params.allocRespFB,
    params.allocRespBB))
  allocRespBuffer.io.i <> alloc1Out
  allocRespBuffer.io.broadcastIn := alloc01Buffer.io.broadcastOut
  io.allocResp <> allocRespBuffer.io.o
  io.fillCompleteForSlotStatusResp := fillCompleteForStateResp
  io.fillCompleteForAllocResp := allocRespBuffer.io.broadcastOut

  val alloc1Fire = alloc1In.fire && alloc1Out.fire
  val allocFire = alloc1Fire && !alloc1In.bits.hit
  allocFillReqEnq.valid := allocFire
  allocFillReqEnq.bits.slot := freeSlotDeq.bits
  allocFillReqEnq.bits.tag := alloc1In.bits.tag
  allocFillReqEnq.bits.meta := alloc1In.bits.fillMeta
  errors.allocBadState :=
    allocFire && state(freeSlotDeq.bits) =/= TagState.EmptyInQueue
  errors.allocBadUses :=
    allocFire && nUses(freeSlotDeq.bits) =/= 0.U
  errors.allocRecentlyUsed :=
    allocFire && recentlyUsed(freeSlotDeq.bits)

  val slotMetaAfterAlloc = Wire(Vec(nSlots, slotMetaType))
  slotMetaAfterAlloc := slotMeta
  when (allocFire) {
    slotMetaAfterAlloc(freeSlotDeq.bits).tag := alloc1In.bits.tag
    slotMetaAfterAlloc(freeSlotDeq.bits).fillMeta := alloc1In.bits.fillMeta
    slotMetaAfterAlloc(freeSlotDeq.bits).state := alloc1MissState
    slotMetaAfterAlloc(freeSlotDeq.bits).nUses := 1.U
    slotMetaAfterAlloc(freeSlotDeq.bits).recentlyUsed := false.B
  }
  errors.allocUsesOverflow :=
    alloc1Fire && alloc1In.bits.hit && !alloc1HitUsesAvailable
  when (alloc1Fire && alloc1In.bits.hit && alloc1HitUsesAvailable) {
    slotMetaAfterAlloc(alloc1In.bits.hitSlot).nUses := nUses(alloc1In.bits.hitSlot) + 1.U
    slotMetaAfterAlloc(alloc1In.bits.hitSlot).recentlyUsed := true.B
    // Reclaiming an evicting same-tag slot cancels the eviction logically. The
    // stale writeback is allowed to finish, but its completion must not free
    // this slot.
    when (alloc1ReclaimsEviction) {
      slotMetaAfterAlloc(alloc1In.bits.hitSlot).state :=
        TagState.PresentDirtyCancelledEviction
    } .elsewhen (alloc1In.bits.willWrite) {
      slotMetaAfterAlloc(alloc1In.bits.hitSlot).state :=
        markDirty(state(alloc1In.bits.hitSlot))
    }
  }

  // ============================================================
  // writeback0: completed dirty writeback frees an evicting slot
  // ============================================================

  val writebackComplete0 = ValidBuffer(io.writebackComplete, true)
  val writebackComplete0Evicting =
    state(writebackComplete0.bits) === TagState.Evicting
  val writebackComplete0Cancelled =
    state(writebackComplete0.bits) === TagState.PresentDirtyCancelledEviction
  writebackFreeSlotEnq.valid := writebackComplete0.valid && writebackComplete0Evicting
  writebackFreeSlotEnq.bits := writebackComplete0.bits
  errors.writebackCompleteBadState :=
    writebackComplete0.valid &&
      !writebackComplete0Evicting &&
      !writebackComplete0Cancelled
  errors.writebackCompleteQueueNotReady :=
    writebackComplete0.valid && writebackComplete0Evicting && !writebackFreeSlotEnq.ready

  val slotMetaAfterWriteback = Wire(Vec(nSlots, slotMetaType))
  slotMetaAfterWriteback := slotMetaAfterAlloc
  when (writebackComplete0.valid && writebackComplete0Evicting) {
    slotMetaAfterWriteback(writebackComplete0.bits).state := TagState.EmptyInQueue
    slotMetaAfterWriteback(writebackComplete0.bits).nUses := 0.U
    slotMetaAfterWriteback(writebackComplete0.bits).recentlyUsed := false.B
  } .elsewhen (writebackComplete0.valid && writebackComplete0Cancelled) {
    slotMetaAfterWriteback(writebackComplete0.bits).state := TagState.PresentDirty
  }

  // ============================================================
  // fill0: publish a filling slot as present
  // ============================================================
  // Fill completion installs the payload and makes the slot usable by lookup paths.

  val fill0 = io.fillComplete
  errors.fillBadState := fill0.valid && !isFilling(state(fill0.bits.slot))

  val slotMetaAfterFill = Wire(Vec(nSlots, slotMetaType))
  slotMetaAfterFill := slotMetaAfterWriteback
  when (fill0.valid) {
    slotMetaAfterFill(fill0.bits.slot).state := Mux(
      slotMetaAfterWriteback(fill0.bits.slot).state === TagState.FillingDirty,
      TagState.PresentDirty,
      TagState.PresentClean)
    slotMetaAfterFill(fill0.bits.slot).payload := fill0.bits.payload
    slotMetaAfterFill(fill0.bits.slot).recentlyUsed := true.B
  }

  // ============================================================
  // release0: retire an active consumer
  // ============================================================

  val release0 = ValidBuffer(io.release, params.releaseBuffer)
  errors.releaseUnderflow := release0.valid && nUses(release0.bits) === 0.U

  val slotMetaAfterRelease = Wire(Vec(nSlots, slotMetaType))
  slotMetaAfterRelease := slotMetaAfterFill
  when (release0.valid) {
    slotMetaAfterRelease(release0.bits).nUses := slotMetaAfterFill(release0.bits).nUses - 1.U
  }

  // ============================================================
  // scan0: read lifecycle metadata for the selected slot
  // ============================================================

  val scan0SlotNext = Wire(UInt(slotWidth.W))
  val scan0Slot = RegNext(scan0SlotNext, 0.U)
  scan0SlotNext := scan0Slot

  val scan0ShouldRun = freeCount < params.scanBackpressureDepth.U || freeSlotDeq.fire
  val scan0Out = Wire(Decoupled(new Scan0Result(slotWidth, nUsesWidth)))
  scan0Out.valid := scan0ShouldRun
  scan0Out.bits.slot := scan0Slot
  scan0Out.bits.state := state(scan0Slot)
  scan0Out.bits.nUses := nUses(scan0Slot)
  scan0Out.bits.recentlyUsed := recentlyUsed(scan0Slot)

  when (scan0Out.fire) {
    scan0SlotNext := incrSlot(scan0Slot)
  }

  // ============================================================
  // scan1: choose second-chance or enqueue action
  // ============================================================
  // Empty slots can be queued immediately. Clean present slots must have no
  // active uses; if recentlyUsed is set, scan1 clears it instead of enqueueing.

  val scan1In = DoubleBuffer(scan0Out, params.scan01FB, params.scan01BB)
  val scan1Empty = scan1In.bits.state === TagState.Empty
  val scan1FillNeeded = isReserved(scan1In.bits.state)
  val scan1PresentCleanReusable =
    scan1In.bits.state === TagState.PresentClean && scan1In.bits.nUses === 0.U
  val scan1PresentDirtyReusable =
    scan1In.bits.state === TagState.PresentDirty && scan1In.bits.nUses === 0.U
  val scan1ClearRecentlyUsed =
    (scan1PresentCleanReusable || scan1PresentDirtyReusable) && scan1In.bits.recentlyUsed
  val scan1EnqueueFreeSlot =
    scan1Empty || (scan1PresentCleanReusable && !scan1In.bits.recentlyUsed)
  val scan1Writeback =
    scan1PresentDirtyReusable && !scan1In.bits.recentlyUsed
  scan1In.ready :=
    !scan1EnqueueFreeSlot || cleanFreeSlotEnq.ready

  cleanFreeSlotEnq.valid := scan1In.valid && scan1EnqueueFreeSlot
  cleanFreeSlotEnq.bits := scan1In.bits.slot
  scanFillReqEnq.valid := scan1In.valid && scan1FillNeeded
  scanFillReqEnq.bits.slot := scan1In.bits.slot
  scanFillReqEnq.bits.tag := tag(scan1In.bits.slot)
  scanFillReqEnq.bits.meta := fillMeta(scan1In.bits.slot)
  io.writebackReq.valid := scan1In.valid && scan1Writeback
  io.writebackReq.bits.slot := scan1In.bits.slot
  io.writebackReq.bits.tag := tag(scan1In.bits.slot)
  io.writebackReq.bits.payload := payload(scan1In.bits.slot)

  val slotMetaAfterScan = Wire(Vec(nSlots, slotMetaType))
  slotMetaAfterScan := slotMetaAfterRelease
  when (scan1In.fire) {
    // Fill retries from scan are opportunistic. If the fill request FIFO is
    // full, leave the slot Reserved so a later scan can try again.
    when (scan1FillNeeded && scanFillReqEnq.ready) {
      slotMetaAfterScan(scan1In.bits.slot).state := Mux(
        scan1In.bits.state === TagState.ReservedDirty,
        TagState.FillingDirty,
        TagState.FillingClean)
    }

    when (scan1ClearRecentlyUsed) {
      slotMetaAfterScan(scan1In.bits.slot).recentlyUsed := false.B
    }

    when (scan1EnqueueFreeSlot) {
      slotMetaAfterScan(scan1In.bits.slot).state := TagState.EmptyInQueue
      slotMetaAfterScan(scan1In.bits.slot).nUses := 0.U
      slotMetaAfterScan(scan1In.bits.slot).recentlyUsed := false.B
    }

    // Dirty evictions from scan are opportunistic. If the writeback queue is
    // full, leave the slot PresentDirty so a later scan can try again.
    when (scan1Writeback && io.writebackReq.ready) {
      slotMetaAfterScan(scan1In.bits.slot).state := TagState.Evicting
    }
  }

  // ============================================================
  // claim0: lookup metadata for an existing live tag
  // ============================================================

  val claim0In = ValidBuffer(io.claimReq, params.claimReqFB)

  val claim0Matches = Wire(Vec(nSlots, Bool()))
  for (slot <- 0 until nSlots) {
    claim0Matches(slot) :=
      tag(slot) === claim0In.bits.tag && isLive(state(slot))
  }
  val claim0Hit = claim0Matches.asUInt.orR
  val claim0Slot = PriorityEncoder(claim0Matches)
  val claim0State = Mux(claim0Hit, state(claim0Slot), TagState.Empty)
  // Claim is the final table update stage in this module. Its capacity check
  // must use the same post-scan metadata that the claim increment writes.
  val claim0UsesAvailable = slotMetaAfterScan(claim0Slot).nUses =/= maxUses
  val claim0DidClaim =
    claim0Hit &&
      claim0In.bits.doClaim &&
      isClaimable(claim0In.bits, claim0State) &&
      claim0UsesAvailable

  val claim0Out = Wire(Valid(new TagClaimResp(slotWidth, respMetaType, payloadType)))
  claim0Out.valid := claim0In.valid
  claim0Out.bits.hasSlot := claim0Hit
  claim0Out.bits.slot := claim0Slot
  claim0Out.bits.state := claim0State
  claim0Out.bits.didClaim := claim0DidClaim
  claim0Out.bits.meta := claim0In.bits.meta
  claim0Out.bits.payload := payload(claim0Slot)

  io.claimResp := ValidBuffer(claim0Out, params.claimRespFB)

  val slotMetaAfterClaim = Wire(Vec(nSlots, slotMetaType))
  slotMetaAfterClaim := slotMetaAfterScan
  when (claim0In.valid && claim0DidClaim) {
    slotMetaAfterClaim(claim0Slot).nUses := slotMetaAfterScan(claim0Slot).nUses + 1.U
    slotMetaAfterClaim(claim0Slot).recentlyUsed := true.B
    when (claim0In.bits.willWrite) {
      slotMetaAfterClaim(claim0Slot).state := markDirty(slotMetaAfterScan(claim0Slot).state)
    }
  }
  slotMetaNext := slotMetaAfterClaim

  // ============================================================
  // Outputs
  // ============================================================

  io.errors := RegNext(errors)
}

object TagTableGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val tagWidth = if (args.length > 0) args(0).toInt else 16
    val slotWidth = if (args.length > 1) args(1).toInt else 3
    val nUsesWidth = if (args.length > 2) args(2).toInt else 4
    val freeQueueDepth = if (args.length > 3) args(3).toInt else 8
    val fillReqQueueDepth = if (args.length > 4) args(4).toInt else 8
    val scanBackpressureDepth = if (args.length > 5) args(5).toInt else 2
    new TagTable(
      tagWidth = tagWidth,
      slotWidth = slotWidth,
      nUsesWidth = nUsesWidth,
      params = TagTableParams(
        freeQueueDepth = freeQueueDepth,
        fillReqQueueDepth = fillReqQueueDepth,
        scanBackpressureDepth = scanBackpressureDepth,
      ),
      respMetaType = Bool(),
      fillMetaType = UInt(0.W),
      payloadType = UInt(0.W),
    )
  }
}

object TagTableMain extends App {
  val outputDir = args(0)
  TagTableGenerator.generate(outputDir, args.drop(1))
}
