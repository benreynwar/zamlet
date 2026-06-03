package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams

class KceScannerIO(params: ZamletParams) extends Bundle {
  // One-slot-per-cycle metadata query into KceCacheTable.
  val slotReq = Decoupled(params.cacheSlot())
  val slotResp = Flipped(Decoupled(new KceCacheSlotScanState(params)))

  // Scanner action back to the cache table.
  val slotUpdate = Valid(new KceScannerSlotUpdate(params))
  val emptySlot = Decoupled(params.cacheSlot())

  // Dirty writeback handoff to KceMemletInterface.
  val writebackSlot = Decoupled(new KceWritebackSlotReq(params))
  val writebackSlotComplete = Flipped(Valid(params.cacheSlot()))
  val scannerWritebackComplete = Valid(new KceWritebackComplete(params))
}

class KceScanner(params: ZamletParams) extends Module {
  val io = IO(new KceScannerIO(params))
  val sp = params.kceScannerParams

  require(sp.emptyQueueDepth > 1)
  require(sp.emptyQueueScanBackpressureDepth > 0)
  require(sp.emptyQueueScanBackpressureDepth <= sp.emptyQueueDepth)

  private val slotWidth = log2Ceil(params.nCacheSlots)
  private val emptyPtrWidth = log2Ceil(sp.emptyQueueDepth)
  private val emptyCountWidth = log2Ceil(sp.emptyQueueDepth + 1)
  private def incrSlot(slot: UInt): UInt = {
    Mux(slot === (params.nCacheSlots - 1).U, 0.U, slot + 1.U)
  }
  private def incrEmptyPtr(ptr: UInt): UInt = {
    Mux(ptr === (sp.emptyQueueDepth - 1).U, 0.U, ptr + 1.U)
  }

  // Empty-slot queue. It starts empty; the scanner fills it by finding `Empty`
  // slots and by receiving completed dirty writebacks.
  val emptySlotsNext = Wire(Vec(sp.emptyQueueDepth, params.cacheSlot()))
  val emptySlots = RegEnable(emptySlotsNext, true.B)
  emptySlotsNext := emptySlots

  val emptyDeqPtrNext = Wire(UInt(emptyPtrWidth.W))
  val emptyDeqPtr = RegEnable(emptyDeqPtrNext, 0.U, true.B)
  emptyDeqPtrNext := emptyDeqPtr

  val emptyEnqPtrNext = Wire(UInt(emptyPtrWidth.W))
  val emptyEnqPtr = RegEnable(emptyEnqPtrNext, 0.U, true.B)
  emptyEnqPtrNext := emptyEnqPtr

  val emptyCountNext = Wire(UInt(emptyCountWidth.W))
  val emptyCount = RegEnable(emptyCountNext, 0.U(emptyCountWidth.W), true.B)
  emptyCountNext := emptyCount

  io.emptySlot.valid := emptyCount =/= 0.U
  io.emptySlot.bits := emptySlots(emptyDeqPtr)

  // The scanner owns the clock hand. KceCacheTable gives the selected slot a
  // second chance by clearing recentlyUsed when this read sees an otherwise
  // evictable present line.
  val s0SlotNext = Wire(UInt(slotWidth.W))
  val s0Slot = RegEnable(s0SlotNext, 0.U(slotWidth.W), true.B)
  s0SlotNext := s0Slot

  val s0Ready =
    emptyCount < sp.emptyQueueScanBackpressureDepth.U || io.emptySlot.fire

  io.slotReq.valid := true.B
  io.slotReq.bits := s0Slot

  io.slotUpdate.valid := false.B
  io.slotUpdate.bits.slot := s0Slot
  io.slotUpdate.bits.updateType := KceScannerSlotUpdateType.InvalidateClean

  io.writebackSlot.valid := false.B
  io.writebackSlot.bits.slot := s0Slot
  io.writebackSlot.bits.addr := io.slotResp.bits.addr

  val s0CleanCandidate =
    io.slotResp.bits.canEvict &&
      !io.slotResp.bits.recentlyUsed &&
      io.slotResp.bits.state === KceCacheSlotState.PresentClean
  val s0DirtyCandidate =
    io.slotResp.bits.canEvict &&
      !io.slotResp.bits.recentlyUsed &&
      io.slotResp.bits.state === KceCacheSlotState.PresentDirty
  val s0EmptyCandidate =
    io.slotResp.bits.canEvict &&
      io.slotResp.bits.state === KceCacheSlotState.Empty

  val s0EmptyQueueEnqReady =
    emptyCount =/= sp.emptyQueueDepth.U || io.emptySlot.fire
  val s0CleanInvalidates =
    io.slotResp.valid &&
      s0CleanCandidate &&
      !io.writebackSlotComplete.valid &&
      s0Ready
  val s0QueueEmpty =
    io.slotResp.valid &&
      s0EmptyCandidate &&
      !io.writebackSlotComplete.valid &&
      !s0CleanInvalidates &&
      s0Ready

  io.slotUpdate.valid :=
    s0CleanInvalidates ||
      s0QueueEmpty ||
      (io.slotResp.valid && s0Ready && s0DirtyCandidate && io.writebackSlot.ready)
  io.slotUpdate.bits.updateType := MuxCase(
    KceScannerSlotUpdateType.InvalidateClean,
    Seq(
      s0QueueEmpty -> KceScannerSlotUpdateType.QueueEmpty,
      s0DirtyCandidate -> KceScannerSlotUpdateType.EvictDirty))

  io.writebackSlot.valid :=
    io.slotResp.valid && s0Ready && s0DirtyCandidate

  io.scannerWritebackComplete.valid := io.writebackSlotComplete.valid
  io.scannerWritebackComplete.bits.slot := io.writebackSlotComplete.bits
  io.scannerWritebackComplete.bits.inEmptyQueue :=
    io.writebackSlotComplete.valid && s0EmptyQueueEnqReady

  val s0EmptyQueueEnqValid =
    io.writebackSlotComplete.valid || s0CleanInvalidates || s0QueueEmpty
  val s0EmptyQueueEnqFire =
    s0EmptyQueueEnqValid && s0EmptyQueueEnqReady
  val s0EmptyQueueEnqSlot =
    Mux(io.writebackSlotComplete.valid, io.writebackSlotComplete.bits, s0Slot)

  when (s0EmptyQueueEnqFire) {
    emptySlotsNext(emptyEnqPtr) := s0EmptyQueueEnqSlot
    emptyEnqPtrNext := incrEmptyPtr(emptyEnqPtr)
  }

  when (io.emptySlot.fire) {
    emptyDeqPtrNext := incrEmptyPtr(emptyDeqPtr)
  }

  emptyCountNext := emptyCount + s0EmptyQueueEnqFire.asUInt - io.emptySlot.fire.asUInt

  io.slotResp.ready :=
    s0Ready &&
      (!s0CleanCandidate || s0CleanInvalidates) &&
      (!s0EmptyCandidate || s0QueueEmpty) &&
      (!s0DirtyCandidate || io.writebackSlot.ready)

  when (io.slotResp.fire) {
    s0SlotNext := incrSlot(s0Slot)
  }
}
