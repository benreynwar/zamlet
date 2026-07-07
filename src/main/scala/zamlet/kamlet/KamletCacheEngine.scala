package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{CacheLineRequest, CacheLineResponse, JteHandlerReplay, SendCacheLineCmd}
import zamlet.network.NetworkWord

object KceCacheSlotState extends ChiselEnum {
  val Empty, EmptyInQueue, Fetching, FetchingWillWrite, PresentClean, PresentDirty, Evicting = Value
}

object KceTagTableClient extends ChiselEnum {
  val Pending, Kte, Rs = Value
}

class KceClaimSlotReq(params: ZamletParams) extends Bundle {
  val cacheLineAddr = params.cacheLineAddr()
  val willWrite = Bool()
  val claimIfFetching = Bool()
}

class KceClaimSlotResp(params: ZamletParams) extends Bundle {
  val hasSlot = Bool()
  val slot = params.cacheSlot()
  val state = KceCacheSlotState()
  val didClaim = Bool()
}

class KceAllocSlotReq(params: ZamletParams) extends Bundle {
  val cacheLineAddr = params.cacheLineAddr()
  val willWrite = Bool()
}

class KceAllocSlotResp(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val state = KceCacheSlotState()
}

class KceSlotRelease(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
}

class KceFetchSlotReq(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val addr = params.cacheLineAddr()
}

class KceWritebackSlotReq(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val addr = params.cacheLineAddr()
}

class KceCacheEngineErrors extends Bundle {
  val memletInterface = new KceMemletInterfaceErrors
  val pendingTable = new KcePendingTableErrors
  val tagTable = new TagTableErrors
  val rsClaimRespQueueOverflow = Bool()
  val pendingClaimRespQueueOverflow = Bool()
  val kteClaimRespQueueOverflow = Bool()
}

class KamletCacheEngineIO(params: ZamletParams) extends Bundle {
  val knetX = Input(params.xPos())
  val knetY = Input(params.yPos())
  val memletKnetX = Input(params.xPos())
  val memletKnetY = Input(params.yPos())

  // JTE cache-line request path. These requests are mediated by KcePendingTable.
  val jteCacheLineReq = Vec(params.jInK, Flipped(Decoupled(new CacheLineRequest(params))))
  val jteCacheLineResp = Vec(params.jInK, Decoupled(new CacheLineResponse(params)))
  val jteReplay = Vec(params.jInK, Decoupled(new JteHandlerReplay(params)))
  val jteCacheLineRelease = Vec(params.jInK, Flipped(Valid(new KceSlotRelease(params))))

  // JCE cache-line path. Fetch fills report done; dirty writebacks are triggered here.
  val jceFetchDone = Vec(params.jInK, Flipped(Valid(params.cacheSlot())))
  val jceWritebackReq = Vec(params.jInK, Valid(new SendCacheLineCmd(params)))

  // KamletTransferEngine cache-line path.
  val kteReleaseSlot = Flipped(Valid(new KceSlotRelease(params)))
  val kteSlotIsAvailable = Valid(params.cacheSlot())
  // Status responses are guaranteed to arrive exactly one cycle after the
  // corresponding request, with no buffering on this path.
  val kteSlotStatusReq = Flipped(Valid(params.cacheSlot()))
  val kteSlotStatusResp = Valid(Bool())
  // Instr-start status is a fixed-latency Valid path. KCE must consume the
  // response without backpressure. If a query response says an ident has not
  // started, the corresponding start notification is guaranteed not to arrive
  // at KCE until after KCE has had a cycle to store the request as
  // WaitingForInstrIdent.
  val kteInstrStartedReq = Valid(params.ident())
  val kteInstrStartedResp = Flipped(Valid(Bool()))
  val kteInstrStartedNotify = Flipped(Valid(params.ident()))

  // ReservationStation cache-line path.
  val rsAllocSlotReq = Flipped(Decoupled(new KceAllocSlotReq(params)))
  val rsAllocSlotResp = Decoupled(new KceAllocSlotResp(params))

  // Kamlet-network Memlet control path.
  val packetIn = Flipped(Decoupled(new NetworkWord(params)))
  val packetOut = Decoupled(new NetworkWord(params))

  val errors = Output(new KceCacheEngineErrors)
}

class KamletCacheEngine(params: ZamletParams) extends Module {
  val io = IO(new KamletCacheEngineIO(params))

  def tagStateToKce(state: TagState.Type): KceCacheSlotState.Type = {
    MuxCase(KceCacheSlotState.Empty, Seq(
      (state === TagState.Empty) -> KceCacheSlotState.Empty,
      (state === TagState.EmptyInQueue) -> KceCacheSlotState.EmptyInQueue,
      (state === TagState.ReservedClean) -> KceCacheSlotState.Fetching,
      (state === TagState.ReservedDirty) -> KceCacheSlotState.FetchingWillWrite,
      (state === TagState.FillingClean) -> KceCacheSlotState.Fetching,
      (state === TagState.FillingDirty) -> KceCacheSlotState.FetchingWillWrite,
      (state === TagState.PresentClean) -> KceCacheSlotState.PresentClean,
      (state === TagState.PresentDirty) -> KceCacheSlotState.PresentDirty,
      (state === TagState.PresentDirtyCancelledEviction) -> KceCacheSlotState.PresentDirty,
      (state === TagState.Evicting) -> KceCacheSlotState.Evicting))
  }

  // ============================================================
  // Submodules
  // ============================================================

  val memletInterface = Module(new KceMemletInterface(params))
  val pendingTable = Module(new KcePendingTable(params))
  val ttp = params.kceTagTableParams
  val tagTable = Module(new TagTable(
    tagWidth = params.cacheLineAddrWidth,
    slotWidth = params.cacheSlotWidth,
    params = ttp,
    respMetaType = KceTagTableClient(),
    fillMetaType = UInt(0.W),
    payloadType = UInt(0.W),
  ))


  // ============================================================
  // Position / network configuration
  // ============================================================

  memletInterface.io.knetX := io.knetX
  memletInterface.io.knetY := io.knetY
  memletInterface.io.memletKnetX := io.memletKnetX
  memletInterface.io.memletKnetY := io.memletKnetY

  // ============================================================
  // JTE cache-line path
  // ============================================================

  for (jInK <- 0 until params.jInK) {
    pendingTable.io.cacheLineReq(jInK) <> io.jteCacheLineReq(jInK)
    io.jteCacheLineResp(jInK) <> pendingTable.io.cacheLineResp(jInK)
    io.jteReplay(jInK) <> pendingTable.io.replay(jInK)

    pendingTable.io.cacheLineRelease(jInK) := io.jteCacheLineRelease(jInK)
    memletInterface.io.jceFetchDone(jInK) := io.jceFetchDone(jInK)
    io.jceWritebackReq(jInK) := memletInterface.io.jceWritebackReq(jInK)
  }
  io.kteInstrStartedReq := pendingTable.io.instrStartedReq
  pendingTable.io.instrStartedResp := io.kteInstrStartedResp
  pendingTable.io.instrStartedNotify := io.kteInstrStartedNotify

  // ============================================================
  // PendingTable / RS <-> TagTable
  // ============================================================

  val claimRespQueueDepth = 4
  val claimRespQueueAlmostFullThreshold = (claimRespQueueDepth - 2).U
  val pendingClaimRespQueue = Module(new Queue(new KceClaimSlotResp(params), claimRespQueueDepth))
  val pendingClaimRespBelowThreshold =
    pendingClaimRespQueue.io.count < claimRespQueueAlmostFullThreshold

  val pendingClaimSelected =
    pendingTable.io.claimSlotReq.valid && pendingClaimRespBelowThreshold
  val selectedClaimReq = Wire(new KceClaimSlotReq(params))
  selectedClaimReq := pendingTable.io.claimSlotReq.bits
  tagTable.io.claimReq.valid := pendingClaimSelected
  tagTable.io.claimReq.bits.tag := selectedClaimReq.cacheLineAddr
  tagTable.io.claimReq.bits.willWrite := selectedClaimReq.willWrite
  tagTable.io.claimReq.bits.doClaim := true.B
  tagTable.io.claimReq.bits.claimIfPendingFill := selectedClaimReq.claimIfFetching
  tagTable.io.claimReq.bits.meta := KceTagTableClient.Pending
  pendingTable.io.claimSlotReq.ready := pendingClaimSelected

  val tagClaimRespAsKce = Wire(new KceClaimSlotResp(params))
  tagClaimRespAsKce.hasSlot := tagTable.io.claimResp.bits.hasSlot
  tagClaimRespAsKce.slot := tagTable.io.claimResp.bits.slot
  tagClaimRespAsKce.state := tagStateToKce(tagTable.io.claimResp.bits.state)
  tagClaimRespAsKce.didClaim := tagTable.io.claimResp.bits.didClaim

  pendingClaimRespQueue.io.enq.valid :=
    tagTable.io.claimResp.valid && tagTable.io.claimResp.bits.meta === KceTagTableClient.Pending
  pendingClaimRespQueue.io.enq.bits := tagClaimRespAsKce
  pendingTable.io.claimSlotResp <> pendingClaimRespQueue.io.deq
  val pendingClaimRespQueueOverflow =
    pendingClaimRespQueue.io.enq.valid && !pendingClaimRespQueue.io.enq.ready

  val rsClaimRespQueueOverflow = false.B
  val kteClaimRespQueueOverflow = false.B

  val rsAllocSelected = io.rsAllocSlotReq.valid
  val pendingAllocSelected = !rsAllocSelected && pendingTable.io.allocSlotReq.valid
  tagTable.io.allocReq.valid := rsAllocSelected || pendingAllocSelected
  tagTable.io.allocReq.bits.tag := Mux(
    rsAllocSelected,
    io.rsAllocSlotReq.bits.cacheLineAddr,
    pendingTable.io.allocSlotReq.bits.cacheLineAddr)
  tagTable.io.allocReq.bits.willWrite := Mux(
    rsAllocSelected,
    io.rsAllocSlotReq.bits.willWrite,
    pendingTable.io.allocSlotReq.bits.willWrite)
  tagTable.io.allocReq.bits.meta := Mux(
    rsAllocSelected,
    KceTagTableClient.Rs,
    KceTagTableClient.Pending)
  tagTable.io.allocReq.bits.fillMeta := 0.U(0.W)
  io.rsAllocSlotReq.ready := rsAllocSelected && tagTable.io.allocReq.ready
  pendingTable.io.allocSlotReq.ready := pendingAllocSelected && tagTable.io.allocReq.ready

  val tagAllocRespAsKce = Wire(new KceAllocSlotResp(params))
  tagAllocRespAsKce.slot := tagTable.io.allocResp.bits.slot
  tagAllocRespAsKce.state := tagStateToKce(tagTable.io.allocResp.bits.state)

  pendingTable.io.allocSlotResp.valid :=
    tagTable.io.allocResp.valid && tagTable.io.allocResp.bits.meta === KceTagTableClient.Pending
  pendingTable.io.allocSlotResp.bits := tagAllocRespAsKce
  io.rsAllocSlotResp.valid :=
    tagTable.io.allocResp.valid && tagTable.io.allocResp.bits.meta === KceTagTableClient.Rs
  io.rsAllocSlotResp.bits := tagAllocRespAsKce
  tagTable.io.allocResp.ready := Mux(
    tagTable.io.allocResp.bits.meta === KceTagTableClient.Rs,
    io.rsAllocSlotResp.ready,
    pendingTable.io.allocSlotResp.ready)

  tagTable.io.release.valid := pendingTable.io.releaseSlot.valid || io.kteReleaseSlot.valid
  tagTable.io.release.bits := Mux(
    pendingTable.io.releaseSlot.valid,
    pendingTable.io.releaseSlot.bits.slot,
    io.kteReleaseSlot.bits.slot)

  pendingTable.io.slotIsAvailable.valid := tagTable.io.fillCompleteForAllocResp.valid
  pendingTable.io.slotIsAvailable.bits := tagTable.io.fillCompleteForAllocResp.bits.slot

  tagTable.io.slotStatusReq := io.kteSlotStatusReq
  io.kteSlotStatusResp.valid := tagTable.io.slotStatusResp.valid
  io.kteSlotStatusResp.bits :=
    tagTable.io.slotStatusResp.bits === TagState.PresentClean ||
      tagTable.io.slotStatusResp.bits === TagState.PresentDirty ||
      tagTable.io.slotStatusResp.bits === TagState.PresentDirtyCancelledEviction

  // ============================================================
  // TagTable <-> MemletInterface
  // ============================================================

  memletInterface.io.fetchSlotReq.valid := tagTable.io.fillReq.valid
  memletInterface.io.fetchSlotReq.bits.slot := tagTable.io.fillReq.bits.slot
  memletInterface.io.fetchSlotReq.bits.addr := tagTable.io.fillReq.bits.tag
  tagTable.io.fillReq.ready := memletInterface.io.fetchSlotReq.ready

  tagTable.io.fillComplete.valid := memletInterface.io.fetchSlotComplete.valid
  tagTable.io.fillComplete.bits.slot := memletInterface.io.fetchSlotComplete.bits
  tagTable.io.fillComplete.bits.payload := 0.U(0.W)

  memletInterface.io.writebackSlotReq.valid := tagTable.io.writebackReq.valid
  memletInterface.io.writebackSlotReq.bits.slot := tagTable.io.writebackReq.bits.slot
  memletInterface.io.writebackSlotReq.bits.addr := tagTable.io.writebackReq.bits.tag
  tagTable.io.writebackReq.ready := memletInterface.io.writebackSlotReq.ready

  tagTable.io.writebackComplete.valid := memletInterface.io.writebackSlotComplete.valid
  tagTable.io.writebackComplete.bits := memletInterface.io.writebackSlotComplete.bits

  io.kteSlotIsAvailable.valid := tagTable.io.fillCompleteForSlotStatusResp.valid
  io.kteSlotIsAvailable.bits := tagTable.io.fillCompleteForSlotStatusResp.bits.slot

  // ============================================================
  // Memlet control network
  // ============================================================

  memletInterface.io.packetIn <> io.packetIn
  io.packetOut <> memletInterface.io.packetOut

  // ============================================================
  // Errors
  // ============================================================

  io.errors.memletInterface := memletInterface.io.errors
  io.errors.pendingTable := pendingTable.io.errors
  io.errors.tagTable := tagTable.io.errors
  io.errors.rsClaimRespQueueOverflow := RegNext(rsClaimRespQueueOverflow)
  io.errors.pendingClaimRespQueueOverflow := RegNext(pendingClaimRespQueueOverflow)
  io.errors.kteClaimRespQueueOverflow := RegNext(kteClaimRespQueueOverflow)
}

object KamletCacheEngineGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    new KamletCacheEngine(params)
  }
}

object KamletCacheEngineMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  KamletCacheEngineGenerator.generate(outputDir, Seq(configFile))
}
