package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{IdentQueryInstr, IndexedInstr, JteCreate, JteInitiatorInput,
                       KInstr, KInstrBase, KInstrOpcode, KinstrWithParams,
                       SyncTriggerInstr, TransferMode}
import zamlet.utils.{DoubleBuffer, ValidBuffer}

object KteOpType extends ChiselEnum {
  val CacheWaitLocal, JteTransfer, Sync = Value
}

object KteState extends ChiselEnum {
  val Free, WaitingForJamlets, NeedsSync, WaitingForSync, Cleanup = Value
}

class KteIssueReq(params: ZamletParams) extends Bundle {
  val opType = KteOpType()

  // Original local-exec payload. CacheWaitLocal entries replay this when the
  // cache line becomes available. JteTransfer entries keep it for instruction
  // identity and register lifetime metadata until the final KTE bundle settles.
  val kinstr = new KinstrWithParams(params)

  // Cache metadata for entries that need a Kamlet cache line before replay.
  val cacheLineAddr = params.cacheLineAddr()
  val willWrite = Bool()
}

class KteCacheWaitEntry(params: ZamletParams) extends Bundle {
  val kinstr = new KinstrWithParams(params)
  val cacheLineAddr = params.cacheLineAddr()
  val willWrite = Bool()
  val slot = params.cacheSlot()
  val gettingSlot = Bool()
  val hasSlot = Bool()
  val slotAvailable = Bool()
}

class KteEntry(params: ZamletParams) extends Bundle {
  val state = KteState()
  val kinstr = new KinstrWithParams(params)
  val complete = Vec(params.jInK, Bool())
}

class KteGetSlot01(params: ZamletParams) extends Bundle {
  val entry = UInt(log2Ceil(params.kteCacheWaitTableDepth).W)
  val cacheLineAddr = params.cacheLineAddr()
  val willWrite = Bool()
}

class KteGetSlot12(params: ZamletParams) extends Bundle {
  val entry = UInt(log2Ceil(params.kteCacheWaitTableDepth).W)
  val cacheLineAddr = params.cacheLineAddr()
  val willWrite = Bool()
}

class KteGetSlot23(params: ZamletParams) extends Bundle {
  val entry = UInt(log2Ceil(params.kteCacheWaitTableDepth).W)
  val cacheLineAddr = params.cacheLineAddr()
  val willWrite = Bool()
}

class KteErrors extends Bundle {
  val wakeAlreadyAvailable = Bool()
  val releaseFifoOverflow = Bool()
  val unsupportedIssueOpcode = Bool()
  val invalidJteInputReq = Bool()
  val unsupportedJteInputOpcode = Bool()
  val syncResultWithoutEntry = Bool()
}

class KteReleaseEntry(params: ZamletParams) extends Bundle {
  val releaseRf = Bool()
  val rfAddr = params.rfAddr()
  val releaseCacheSlot = Bool()
  val cacheSlot = params.cacheSlot()
}

class KamletTransferEngineIO(params: ZamletParams) extends Bundle {
  // Ready long-latency operations handed off by the future reservation station.
  val rsIssue = Flipped(Decoupled(new KteIssueReq(params)))

  // Combinational conflict check used by RS issue selection.
  val conflictCacheLineAddr = Input(params.cacheLineAddr())
  val conflict = Output(Bool())

  // Cache-ready aligned operation replayed into the Jamlet local-exec issue mux.
  // Kamlet top-level broadcasts this single stream to all Jamlets.
  val localReplay = Decoupled(new KinstrWithParams(params))

  // Physical registers whose KTE-owned lifetimes have ended.
  val rfRelease = Decoupled(params.rfAddr())

  // KTE owns use of the Kamlet synchronizer. Sync instructions enter KTE from
  // RS, and transfer cleanup starts sync after all local Jamlet work completes.
  val syncLocalEvent = Valid(new SyncEvent(params))
  val syncResult = Flipped(Valid(new SyncEvent(params)))

  // Jamlet transfer-engine control path.
  val jteCreate = Vec(params.jInK, Valid(new JteCreate(params)))
  val jteClear = Vec(params.jInK, Valid(UInt(log2Ceil(params.witemTableDepth).W)))
  val jteInputReq = Vec(params.jInK, Flipped(Decoupled(UInt(log2Ceil(params.witemTableDepth).W))))
  val jteInputResp = Vec(params.jInK, Decoupled(new JteInitiatorInput(params)))
  val transferComplete = Input(Vec(params.jInK, Vec(params.witemTableDepth, Bool())))

  // KTE owns Decoupled cache claims/allocation for long-latency operations.
  val kceClaimSlotReq = Decoupled(new KceClaimSlotReq(params))
  val kceClaimSlotResp = Flipped(Decoupled(new KceClaimSlotResp(params)))
  val kceReleaseSlot = Valid(new KceSlotRelease(params))
  val kceAllocSlotReq = Decoupled(new KceAllocSlotReq(params))
  val kceAllocSlotResp = Flipped(Decoupled(new KceAllocSlotResp(params)))
  val kceSlotIsAvailable = Flipped(Valid(params.cacheSlot()))

  val errors = Output(new KteErrors)
}

class KamletTransferEngine(params: ZamletParams) extends Module {
  val io = IO(new KamletTransferEngineIO(params))
  private val cacheWaitDepth = params.kteCacheWaitTableDepth
  private val jteDepth = params.witemTableDepth
  private val syncMaskWidth = params.maxConcurrentSyncs
  private val syncIdentDistanceWidth = params.syncValueWidth - syncMaskWidth
  require(syncIdentDistanceWidth >= params.identWidth,
    s"syncValueWidth (${params.syncValueWidth}) must hold sync mask ($syncMaskWidth) plus ident distance (${params.identWidth})")

  // ============================================================
  // Operation tables
  // ============================================================

  val cacheWaitEntriesInitial =
    VecInit(Seq.fill(cacheWaitDepth)(0.U.asTypeOf(Valid(new KteCacheWaitEntry(params)))))
  val cacheWaitEntriesNext = Wire(Vec(cacheWaitDepth, Valid(new KteCacheWaitEntry(params))))
  val cacheWaitEntries = RegEnable(cacheWaitEntriesNext, cacheWaitEntriesInitial, true.B)
  cacheWaitEntriesNext := cacheWaitEntries

  val kteEntriesInitial =
    VecInit(Seq.fill(jteDepth)(0.U.asTypeOf(new KteEntry(params))))
  val kteEntriesNext = Wire(Vec(jteDepth, new KteEntry(params)))
  val kteEntries = RegEnable(kteEntriesNext, kteEntriesInitial, true.B)
  kteEntriesNext := kteEntries

  val errorsNext = Wire(new KteErrors)
  errorsNext := 0.U.asTypeOf(new KteErrors)
  io.errors := RegNext(errorsNext)

  // ============================================================
  // IO buffering
  // ============================================================

  val rsIssue = DoubleBuffer(io.rsIssue, true, true)

  val jteCreate = Wire(Vec(params.jInK, Valid(new JteCreate(params))))
  val jteClear = Wire(Vec(params.jInK, Valid(UInt(log2Ceil(params.witemTableDepth).W))))
  val jteInputReq = Wire(Vec(params.jInK, Decoupled(UInt(log2Ceil(params.witemTableDepth).W))))
  val jteInputResp = Wire(Vec(params.jInK, Decoupled(new JteInitiatorInput(params))))

  for (jInK <- 0 until params.jInK) {
    io.jteCreate(jInK) := ValidBuffer(jteCreate(jInK), true)
    io.jteClear(jInK) := ValidBuffer(jteClear(jInK), true)
    jteInputReq(jInK) <> DoubleBuffer(io.jteInputReq(jInK), true, true)
    io.jteInputResp(jInK) <> DoubleBuffer(jteInputResp(jInK), true, true)
  }

  val rfRelease = Wire(Decoupled(params.rfAddr()))
  io.rfRelease <> DoubleBuffer(rfRelease, true, true)

  val kceClaimSlotReq = Wire(Decoupled(new KceClaimSlotReq(params)))
  io.kceClaimSlotReq <> DoubleBuffer(kceClaimSlotReq, true, true)
  val kceClaimSlotResp = DoubleBuffer(io.kceClaimSlotResp, true, true)

  val kceReleaseSlot = Wire(Valid(new KceSlotRelease(params)))
  io.kceReleaseSlot := ValidBuffer(kceReleaseSlot, true)

  val kceAllocSlotReq = Wire(Decoupled(new KceAllocSlotReq(params)))
  io.kceAllocSlotReq <> DoubleBuffer(kceAllocSlotReq, true, true)
  val kceAllocSlotResp = DoubleBuffer(io.kceAllocSlotResp, true, true)
  val kceSlotIsAvailable = ValidBuffer(io.kceSlotIsAvailable, true)

  val releaseFifo = Module(new Queue(new KteReleaseEntry(params), params.kteCacheWaitTableDepth))
  val releaseFifoDepth = params.kteCacheWaitTableDepth
  val releaseFifoCountWidth = log2Ceil(releaseFifoDepth + 1)
  val releaseFifoCountNext = Wire(UInt(releaseFifoCountWidth.W))
  val releaseFifoCount = RegNext(releaseFifoCountNext, 0.U)
  releaseFifoCountNext := releaseFifoCount

  for (jInK <- 0 until params.jInK) {
    jteCreate(jInK).valid := false.B
    jteCreate(jInK).bits := DontCare
    jteClear(jInK).valid := false.B
    jteClear(jInK).bits := DontCare

    jteInputReq(jInK).ready := false.B
    jteInputResp(jInK).valid := false.B
    jteInputResp(jInK).bits := DontCare
  }

  io.syncLocalEvent.valid := false.B
  io.syncLocalEvent.bits.syncIdent := 0.U
  io.syncLocalEvent.bits.value := 0.U
  io.syncLocalEvent.bits.includeActiveMask := false.B
  io.syncLocalEvent.bits.mustDrainValid := false.B
  io.syncLocalEvent.bits.mustDrainSyncIdent := 0.U

  // ============================================================
  // Issue admission
  // ============================================================

  val issue0IsCacheWait = rsIssue.bits.opType === KteOpType.CacheWaitLocal
  val issue0IsJteTransfer = rsIssue.bits.opType === KteOpType.JteTransfer
  val issue0IsSync = rsIssue.bits.opType === KteOpType.Sync
  val issue0CacheWaitFreeVec = cacheWaitEntries.map(entry => !entry.valid)
  val issue0CacheWaitHasFree = VecInit(issue0CacheWaitFreeVec).asUInt.orR
  val issue0CacheWaitFreeIndex = PriorityEncoder(issue0CacheWaitFreeVec)
  val issue0KteFreeVec = kteEntries.map(entry => entry.state === KteState.Free)
  val issue0KteHasFree = VecInit(issue0KteFreeVec).asUInt.orR
  val issue0KteFreeIndex = PriorityEncoder(issue0KteFreeVec)

  val issue0Base = rsIssue.bits.kinstr.kinstr.asTypeOf(new KInstrBase(params))
  val issue0SyncTrigger = rsIssue.bits.kinstr.kinstr.asTypeOf(new SyncTriggerInstr(params))
  val issue0IdentQuery = rsIssue.bits.kinstr.kinstr.asTypeOf(new IdentQueryInstr(params))
  val issue0Indexed = rsIssue.bits.kinstr.kinstr.asTypeOf(new IndexedInstr(params))
  val issue0IsIndexedLoad = issue0Base.opcode === KInstrOpcode.LoadIdxUnord
  val issue0IsIndexedStore = issue0Base.opcode === KInstrOpcode.StoreIdxUnord
  val issue0IsSupportedJteTransfer = issue0IsIndexedLoad || issue0IsIndexedStore
  val issue0IsSyncTrigger = issue0Base.opcode === KInstrOpcode.SyncTrigger
  val issue0IsIdentQuery = issue0Base.opcode === KInstrOpcode.IdentQuery
  val issue0IsSupportedSync = issue0IsSyncTrigger || issue0IsIdentQuery
  val issue0IsSupported =
    issue0IsCacheWait ||
      (issue0IsJteTransfer && issue0IsSupportedJteTransfer) ||
      (issue0IsSync && issue0IsSupportedSync)
  val issue0JteDataReg = Wire(params.rfAddr())
  issue0JteDataReg := 0.U
  when (issue0IsSupportedJteTransfer) {
    issue0JteDataReg := issue0Indexed.reg
  }

  rsIssue.ready :=
    (issue0IsCacheWait && issue0CacheWaitHasFree) ||
      (issue0IsJteTransfer && issue0IsSupportedJteTransfer && issue0KteHasFree) ||
      (issue0IsSync && issue0IsSupportedSync && issue0KteHasFree) ||
      !issue0IsSupported
  when (rsIssue.fire && issue0IsCacheWait) {
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).valid := true.B
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).bits.kinstr := rsIssue.bits.kinstr
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).bits.cacheLineAddr := rsIssue.bits.cacheLineAddr
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).bits.willWrite := rsIssue.bits.willWrite
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).bits.slot := 0.U
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).bits.gettingSlot := false.B
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).bits.hasSlot := false.B
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).bits.slotAvailable := false.B
  }
  errorsNext.unsupportedIssueOpcode :=
    rsIssue.fire && !issue0IsSupported

  when (rsIssue.fire && issue0IsJteTransfer && issue0IsSupportedJteTransfer) {
    kteEntriesNext(issue0KteFreeIndex).state := KteState.WaitingForJamlets
    kteEntriesNext(issue0KteFreeIndex).kinstr := rsIssue.bits.kinstr
    for (jInK <- 0 until params.jInK) {
      kteEntriesNext(issue0KteFreeIndex).complete(jInK) := false.B
      jteCreate(jInK).valid := true.B
      jteCreate(jInK).bits.teIndex := issue0KteFreeIndex
      jteCreate(jInK).bits.instrIdent := issue0Base.instrIdent
      jteCreate(jInK).bits.dataReg := issue0JteDataReg
    }
  }

  when (rsIssue.fire && issue0IsSync && issue0IsSupportedSync) {
    kteEntriesNext(issue0KteFreeIndex).state := KteState.NeedsSync
    kteEntriesNext(issue0KteFreeIndex).kinstr := rsIssue.bits.kinstr
    for (jInK <- 0 until params.jInK) {
      kteEntriesNext(issue0KteFreeIndex).complete(jInK) := false.B
    }
  }

  // ============================================================
  // JTE input response
  // ============================================================

  for (jInK <- 0 until params.jInK) {
    val input0TeIndex = jteInputReq(jInK).bits
    val input0Entry = kteEntries(input0TeIndex)
    val input0Base = input0Entry.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    val input0Indexed = input0Entry.kinstr.kinstr.asTypeOf(new IndexedInstr(params))
    val input0IsIndexedLoad = input0Base.opcode === KInstrOpcode.LoadIdxUnord
    val input0IsIndexedStore = input0Base.opcode === KInstrOpcode.StoreIdxUnord
    val input0IsSupported = input0IsIndexedLoad || input0IsIndexedStore
    val input0CanRespond =
      input0Entry.state === KteState.WaitingForJamlets && input0IsSupported

    val input0Resp = Wire(new JteInitiatorInput(params))
    input0Resp := 0.U.asTypeOf(new JteInitiatorInput(params))
    input0Resp.teIndex := input0TeIndex
    input0Resp.instrIdent := input0Base.instrIdent
    input0Resp.mode := Mux(input0IsIndexedLoad, TransferMode.IndexLoad, TransferMode.IndexStore)
    input0Resp.baseAddr := input0Entry.kinstr.param0
    input0Resp.stride := 0.U
    input0Resp.startIndex := input0Entry.kinstr.param1(params.elementIndexWidth - 1, 0)
    input0Resp.endIndex := input0Entry.kinstr.param2(params.elementIndexWidth - 1, 0)
    input0Resp.dataReg := input0Indexed.reg
    input0Resp.indexReg := input0Indexed.indexReg
    input0Resp.maskReg := input0Indexed.maskReg
    input0Resp.maskEnabled := input0Indexed.maskEnabled
    input0Resp.rfLaneOrder := input0Indexed.rfLaneOrder
    input0Resp.rfDataWF := input0Entry.kinstr.ordering.wf
    input0Resp.rfDataEW := input0Indexed.rfEw
    input0Resp.rfIndexEW := input0Indexed.indexEw

    jteInputResp(jInK).valid := jteInputReq(jInK).valid && input0CanRespond
    jteInputResp(jInK).bits := input0Resp
    jteInputReq(jInK).ready := Mux(input0CanRespond, jteInputResp(jInK).ready, true.B)
  }

  errorsNext.invalidJteInputReq :=
    (0 until params.jInK).map { jInK =>
      jteInputReq(jInK).valid &&
        kteEntries(jteInputReq(jInK).bits).state === KteState.Free
    }.reduce(_ || _)
  errorsNext.unsupportedJteInputOpcode :=
    (0 until params.jInK).map { jInK =>
      val entry = kteEntries(jteInputReq(jInK).bits)
      val base = entry.kinstr.kinstr.asTypeOf(new KInstrBase(params))
      jteInputReq(jInK).valid &&
        entry.state =/= KteState.Free &&
        base.opcode =/= KInstrOpcode.LoadIdxUnord &&
        base.opcode =/= KInstrOpcode.StoreIdxUnord
    }.reduce(_ || _)

  // ============================================================
  // JTE completion
  // ============================================================

  for (teIndex <- 0 until jteDepth) {
    when (kteEntries(teIndex).state === KteState.WaitingForJamlets) {
      for (jInK <- 0 until params.jInK) {
        when (io.transferComplete(jInK)(teIndex)) {
          kteEntriesNext(teIndex).complete(jInK) := true.B
        }
      }

      val completeNextVec = VecInit((0 until params.jInK).map { jInK =>
        kteEntries(teIndex).complete(jInK) || io.transferComplete(jInK)(teIndex)
      })
      when (completeNextVec.asUInt.andR) {
        kteEntriesNext(teIndex).state := KteState.NeedsSync
      }
    }
  }

  // ============================================================
  // Sync start
  // ============================================================

  def entrySyncIdent(entry: KteEntry): UInt = {
    val base = entry.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    val indexed = entry.kinstr.kinstr.asTypeOf(new IndexedInstr(params))
    val syncTrigger = entry.kinstr.kinstr.asTypeOf(new SyncTriggerInstr(params))
    val identQuery = entry.kinstr.kinstr.asTypeOf(new IdentQueryInstr(params))

    MuxCase(0.U(params.syncIdentWidth.W), Seq(
      (base.opcode === KInstrOpcode.LoadIdxUnord) -> indexed.syncIdent,
      (base.opcode === KInstrOpcode.StoreIdxUnord) -> indexed.syncIdent,
      (base.opcode === KInstrOpcode.SyncTrigger) -> syncTrigger.syncIdent,
      (base.opcode === KInstrOpcode.IdentQuery) -> identQuery.syncIdent
    ))
  }

  def identDistanceFromBaseline(ident: UInt, baseline: UInt): UInt = {
    val rawDistance = Wire(UInt((params.identWidth + 1).W))
    rawDistance :=
      Mux(ident >= baseline,
        ident - baseline,
        ident + params.maxResponseTags.U - baseline)
    Mux(rawDistance === 0.U, params.maxResponseTags.U, rawDistance)
      .pad(syncIdentDistanceWidth)(syncIdentDistanceWidth - 1, 0)
  }

  def entryIsNormal(entry: KteEntry): Bool = {
    val base = entry.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    entry.state =/= KteState.Free &&
      base.opcode =/= KInstrOpcode.SyncTrigger &&
      base.opcode =/= KInstrOpcode.IdentQuery
  }

  def identQueryValue(entry: KteEntry): UInt = {
    val identQuery = entry.kinstr.kinstr.asTypeOf(new IdentQueryInstr(params))
    val baseline = identQuery.baseline
    val sentinelDistance = params.maxResponseTags.U(syncIdentDistanceWidth.W)
    val rsDistance = entry.kinstr.param0(syncIdentDistanceWidth - 1, 0)

    val transferDistances = (0 until jteDepth).map { teIndex =>
      val base = kteEntries(teIndex).kinstr.kinstr.asTypeOf(new KInstrBase(params))
      Mux(entryIsNormal(kteEntries(teIndex)),
        identDistanceFromBaseline(base.instrIdent, baseline),
        sentinelDistance)
    }
    val cacheWaitDistances = (0 until cacheWaitDepth).map { cacheWaitIndex =>
      val base = cacheWaitEntries(cacheWaitIndex).bits.kinstr.kinstr.asTypeOf(new KInstrBase(params))
      Mux(cacheWaitEntries(cacheWaitIndex).valid,
        identDistanceFromBaseline(base.instrIdent, baseline),
        sentinelDistance)
    }
    val oldestDistance =
      (Seq(rsDistance) ++ transferDistances ++ cacheWaitDistances).reduce(_ min _)
    Cat(oldestDistance, 0.U(syncMaskWidth.W))
  }

  def entrySyncIncludesActiveMask(entry: KteEntry): Bool = {
    val base = entry.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    base.opcode === KInstrOpcode.IdentQuery
  }

  def entrySyncMustDrainValid(entry: KteEntry): Bool = {
    val base = entry.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    val identQuery = entry.kinstr.kinstr.asTypeOf(new IdentQueryInstr(params))
    base.opcode === KInstrOpcode.IdentQuery && identQuery.mustDrainValid
  }

  def entrySyncMustDrainIdent(entry: KteEntry): UInt = {
    val identQuery = entry.kinstr.kinstr.asTypeOf(new IdentQueryInstr(params))
    identQuery.mustDrainSyncIdent
  }

  def entrySyncValue(entry: KteEntry): UInt = {
    val base = entry.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    val syncTrigger = entry.kinstr.kinstr.asTypeOf(new SyncTriggerInstr(params))

    MuxCase(0.U(params.syncValueWidth.W), Seq(
      (base.opcode === KInstrOpcode.SyncTrigger) -> syncTrigger.value.pad(params.syncValueWidth),
      (base.opcode === KInstrOpcode.IdentQuery) -> identQueryValue(entry)
    ))
  }

  val sync0NeedsSyncVec = kteEntries.map(entry => entry.state === KteState.NeedsSync)
  val sync0Valid = VecInit(sync0NeedsSyncVec).asUInt.orR
  val sync0TeIndex = PriorityEncoder(sync0NeedsSyncVec)

  io.syncLocalEvent.valid := sync0Valid
  io.syncLocalEvent.bits.syncIdent := entrySyncIdent(kteEntries(sync0TeIndex))
  io.syncLocalEvent.bits.value := entrySyncValue(kteEntries(sync0TeIndex))
  io.syncLocalEvent.bits.includeActiveMask := entrySyncIncludesActiveMask(kteEntries(sync0TeIndex))
  io.syncLocalEvent.bits.mustDrainValid := entrySyncMustDrainValid(kteEntries(sync0TeIndex))
  io.syncLocalEvent.bits.mustDrainSyncIdent := entrySyncMustDrainIdent(kteEntries(sync0TeIndex))

  when (sync0Valid) {
    kteEntriesNext(sync0TeIndex).state := KteState.WaitingForSync
  }

  // ============================================================
  // Sync result
  // ============================================================

  val syncResult0MatchVec = VecInit((0 until jteDepth).map { teIndex =>
    kteEntries(teIndex).state === KteState.WaitingForSync &&
      entrySyncIdent(kteEntries(teIndex)) === io.syncResult.bits.syncIdent
  })
  val syncResult0MatchValid = syncResult0MatchVec.asUInt.orR
  val syncResult0TeIndex = PriorityEncoder(syncResult0MatchVec)

  errorsNext.syncResultWithoutEntry := io.syncResult.valid && !syncResult0MatchValid

  when (io.syncResult.valid && syncResult0MatchValid) {
    kteEntriesNext(syncResult0TeIndex).state := KteState.Cleanup
  }

  // ============================================================
  // Conflict query
  // ============================================================

  io.conflict := cacheWaitEntries.map(entry =>
    entry.valid && entry.bits.cacheLineAddr === io.conflictCacheLineAddr).reduce(_ || _)

  // ============================================================
  // Cache wait get slot
  // ============================================================

  def getSlotStateIsPresent(state: KceCacheSlotState.Type): Bool = {
    state === KceCacheSlotState.PresentClean || state === KceCacheSlotState.PresentDirty
  }

  val getSlot0NeedsSlotVec = cacheWaitEntries.map(entry =>
    entry.valid && !entry.bits.gettingSlot && !entry.bits.hasSlot)
  val getSlot0Valid = VecInit(getSlot0NeedsSlotVec).asUInt.orR
  val getSlot0Entry = PriorityEncoder(getSlot0NeedsSlotVec)
  val getSlot0Out = Wire(Decoupled(new KteGetSlot01(params)))

  getSlot0Out.bits.entry := getSlot0Entry
  getSlot0Out.bits.cacheLineAddr := cacheWaitEntries(getSlot0Entry).bits.cacheLineAddr
  getSlot0Out.bits.willWrite := cacheWaitEntries(getSlot0Entry).bits.willWrite

  kceClaimSlotReq.valid := getSlot0Valid && getSlot0Out.ready
  kceClaimSlotReq.bits.cacheLineAddr := getSlot0Out.bits.cacheLineAddr
  kceClaimSlotReq.bits.willWrite := getSlot0Out.bits.willWrite
  kceClaimSlotReq.bits.claimIfFetching := true.B
  getSlot0Out.valid := getSlot0Valid && kceClaimSlotReq.ready

  when (getSlot0Out.fire) {
    cacheWaitEntriesNext(getSlot0Out.bits.entry).bits.gettingSlot := true.B
  }

  val getSlot1In = DoubleBuffer(getSlot0Out, true, true)

  val getSlot1Out = Wire(Decoupled(new KteGetSlot12(params)))
  val getSlot1Claimed = kceClaimSlotResp.bits.didClaim
  val getSlot1NeedsAlloc = !kceClaimSlotResp.bits.hasSlot
  val getSlot1RetryLater = kceClaimSlotResp.bits.hasSlot && !kceClaimSlotResp.bits.didClaim

  getSlot1In.ready :=
    kceClaimSlotResp.valid && (getSlot1Claimed || getSlot1RetryLater || getSlot1Out.ready)
  kceClaimSlotResp.ready :=
    getSlot1In.valid && (getSlot1Claimed || getSlot1RetryLater || getSlot1Out.ready)

  getSlot1Out.valid :=
    getSlot1In.valid && kceClaimSlotResp.valid && getSlot1NeedsAlloc
  getSlot1Out.bits.entry := getSlot1In.bits.entry
  getSlot1Out.bits.cacheLineAddr := getSlot1In.bits.cacheLineAddr
  getSlot1Out.bits.willWrite := getSlot1In.bits.willWrite

  when (getSlot1In.valid && kceClaimSlotResp.fire && getSlot1Claimed) {
    cacheWaitEntriesNext(getSlot1In.bits.entry).bits.slot := kceClaimSlotResp.bits.slot
    cacheWaitEntriesNext(getSlot1In.bits.entry).bits.gettingSlot := false.B
    cacheWaitEntriesNext(getSlot1In.bits.entry).bits.hasSlot := true.B
    cacheWaitEntriesNext(getSlot1In.bits.entry).bits.slotAvailable :=
      getSlotStateIsPresent(kceClaimSlotResp.bits.state)
  }
  when (getSlot1In.valid && kceClaimSlotResp.fire && getSlot1RetryLater) {
    cacheWaitEntriesNext(getSlot1In.bits.entry).bits.gettingSlot := false.B
  }

  val getSlot2In = DoubleBuffer(getSlot1Out, true, true)
  val getSlot2Out = Wire(Decoupled(new KteGetSlot23(params)))

  getSlot2Out.valid := getSlot2In.valid && kceAllocSlotReq.ready
  getSlot2Out.bits.entry := getSlot2In.bits.entry
  getSlot2Out.bits.cacheLineAddr := getSlot2In.bits.cacheLineAddr
  getSlot2Out.bits.willWrite := getSlot2In.bits.willWrite
  getSlot2In.ready := kceAllocSlotReq.ready && getSlot2Out.ready

  kceAllocSlotReq.valid := getSlot2In.valid && getSlot2Out.ready
  kceAllocSlotReq.bits.cacheLineAddr := getSlot2In.bits.cacheLineAddr
  kceAllocSlotReq.bits.willWrite := getSlot2In.bits.willWrite

  val getSlot3In = DoubleBuffer(getSlot2Out, true, true)

  getSlot3In.ready := kceAllocSlotResp.valid
  kceAllocSlotResp.ready := getSlot3In.valid
  when (getSlot3In.valid && kceAllocSlotResp.fire) {
    cacheWaitEntriesNext(getSlot3In.bits.entry).bits.slot := kceAllocSlotResp.bits.slot
    cacheWaitEntriesNext(getSlot3In.bits.entry).bits.gettingSlot := false.B
    cacheWaitEntriesNext(getSlot3In.bits.entry).bits.hasSlot := true.B
    cacheWaitEntriesNext(getSlot3In.bits.entry).bits.slotAvailable := false.B
  }

  // ============================================================
  // Cache wait wake
  // ============================================================

  errorsNext.wakeAlreadyAvailable := cacheWaitEntries.map(entry =>
    kceSlotIsAvailable.valid &&
      entry.valid &&
      entry.bits.hasSlot &&
      entry.bits.slotAvailable &&
      entry.bits.slot === kceSlotIsAvailable.bits).reduce(_ || _)

  when (kceSlotIsAvailable.valid) {
    for (entry <- 0 until cacheWaitDepth) {
      when (cacheWaitEntries(entry).valid &&
        cacheWaitEntries(entry).bits.hasSlot &&
        !cacheWaitEntries(entry).bits.slotAvailable &&
        cacheWaitEntries(entry).bits.slot === kceSlotIsAvailable.bits) {
        cacheWaitEntriesNext(entry).bits.slotAvailable := true.B
      }
    }
  }

  // ============================================================
  // Local replay
  // ============================================================

  val replay0CandidateVec = cacheWaitEntries.map(entry =>
    entry.valid && entry.bits.hasSlot && entry.bits.slotAvailable)
  val replay0Valid = VecInit(replay0CandidateVec).asUInt.orR
  val replay0Entry = PriorityEncoder(replay0CandidateVec)
  val replay0Kinstr = Wire(new KinstrWithParams(params))
  replay0Kinstr := cacheWaitEntries(replay0Entry).bits.kinstr
  replay0Kinstr.cacheSlot := cacheWaitEntries(replay0Entry).bits.slot

  val replay0ReleaseFifoSpace = releaseFifoDepth.U - releaseFifoCount
  val replay0CanStartReleaseDelay = replay0ReleaseFifoSpace >= params.localExecLatency.U

  io.localReplay.valid := replay0Valid && replay0CanStartReleaseDelay
  io.localReplay.bits := replay0Kinstr

  val replay0ReleaseEntry = Wire(new KteReleaseEntry(params))
  replay0ReleaseEntry.releaseRf := false.B
  replay0ReleaseEntry.rfAddr := 0.U
  replay0ReleaseEntry.releaseCacheSlot := true.B
  replay0ReleaseEntry.cacheSlot := cacheWaitEntries(replay0Entry).bits.slot

  when (io.localReplay.fire) {
    cacheWaitEntriesNext(replay0Entry).valid := false.B
  }

  val replay0ReleaseDelayValid =
    ShiftRegister(io.localReplay.fire, params.localExecLatency, false.B, true.B)
  val replay0ReleaseDelayBits =
    ShiftRegister(replay0ReleaseEntry, params.localExecLatency)

  // ============================================================
  // Transfer cleanup
  // ============================================================

  val cleanup0CandidateVec = VecInit(kteEntries.map(entry => entry.state === KteState.Cleanup))
  val cleanup0Valid = cleanup0CandidateVec.asUInt.orR
  val cleanup0TeIndex = PriorityEncoder(cleanup0CandidateVec)
  val cleanup0Base = kteEntries(cleanup0TeIndex).kinstr.kinstr.asTypeOf(new KInstrBase(params))
  val cleanup0Indexed = kteEntries(cleanup0TeIndex).kinstr.kinstr.asTypeOf(new IndexedInstr(params))
  val cleanup0IsJte =
    cleanup0Base.opcode === KInstrOpcode.LoadIdxUnord ||
      cleanup0Base.opcode === KInstrOpcode.StoreIdxUnord
  val cleanup0NeedsRelease = cleanup0IsJte
  val cleanup0Ready =
    !cleanup0NeedsRelease || (!replay0ReleaseDelayValid && releaseFifo.io.enq.ready)

  val cleanup0ReleaseEntry = Wire(new KteReleaseEntry(params))
  cleanup0ReleaseEntry.releaseRf := true.B
  cleanup0ReleaseEntry.rfAddr := cleanup0Indexed.reg
  cleanup0ReleaseEntry.releaseCacheSlot := false.B
  cleanup0ReleaseEntry.cacheSlot := 0.U

  when (cleanup0Valid && cleanup0Ready) {
    for (jInK <- 0 until params.jInK) {
      jteClear(jInK).valid := cleanup0IsJte
      jteClear(jInK).bits := cleanup0TeIndex
    }
    kteEntriesNext(cleanup0TeIndex).state := KteState.Free
  }

  val cleanup0ReleaseValid = cleanup0Valid && cleanup0Ready && cleanup0NeedsRelease

  releaseFifo.io.enq.valid := replay0ReleaseDelayValid || cleanup0ReleaseValid
  releaseFifo.io.enq.bits := Mux(replay0ReleaseDelayValid, replay0ReleaseDelayBits, cleanup0ReleaseEntry)
  errorsNext.releaseFifoOverflow := replay0ReleaseDelayValid && !releaseFifo.io.enq.ready

  // ============================================================
  // Release drain
  // ============================================================

  val release0NeedsRf = releaseFifo.io.deq.bits.releaseRf
  val release0RfReady = !release0NeedsRf || rfRelease.ready

  rfRelease.valid := releaseFifo.io.deq.valid && release0NeedsRf
  rfRelease.bits := releaseFifo.io.deq.bits.rfAddr

  kceReleaseSlot.valid :=
    releaseFifo.io.deq.valid &&
      release0RfReady &&
      releaseFifo.io.deq.bits.releaseCacheSlot
  kceReleaseSlot.bits.slot := releaseFifo.io.deq.bits.cacheSlot

  releaseFifo.io.deq.ready := releaseFifo.io.deq.valid && release0RfReady

  releaseFifoCountNext :=
    releaseFifoCount +
      Mux(releaseFifo.io.enq.fire, 1.U, 0.U) -
      Mux(releaseFifo.io.deq.fire, 1.U, 0.U)
}

object KamletTransferEngineGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    new KamletTransferEngine(params)
  }
}

object KamletTransferEngineMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  KamletTransferEngineGenerator.generate(outputDir, Seq(configFile))
}
