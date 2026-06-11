package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{IdentQueryInstr, IndexedInstr, JteCreate, JteInitiatorInput,
                       KInstr, KInstrBase, KInstrOpcode, KinstrWithParams,
                       LoadSimpleInstr, LocalExec, StoreSimpleInstr, SyncTriggerInstr,
                       TransferMode}
import zamlet.utils.{DoubleBuffer, ValidBuffer}

object KteOpType extends ChiselEnum {
  val CacheWaitLocal, JteTransfer, Sync = Value
}

object KteState extends ChiselEnum {
  val Free, WaitingForJamlets, NeedsSync, WaitingForSync, Cleanup = Value
}

class KteMemFootprint(params: ZamletParams) extends Bundle {
  // True when the operation may touch memory that cannot be represented as one
  // cache line. Unknown footprints conflict conservatively with any write-like
  // memory footprint outside the same writeset.
  val unknown = Bool()

  // True for write-like memory effects. Reads may overlap reads, but writes
  // conflict with other accesses unless the writeset bypass applies.
  val willWrite = Bool()

  // Meaningful only when unknown is false. This is the exact Kamlet cache slot
  // owned by the operation.
  val cacheSlot = params.cacheSlot()

  // Optional write-set identifier. Two valid equal write sets are treated as
  // non-conflicting by the KTE memory conflict checker.
  val writeset = Valid(params.writeset())
}

object KteMemFootprint {
  def conflicts(a: Valid[KteMemFootprint], b: Valid[KteMemFootprint]): Bool = {
    val sameWriteset =
      a.bits.writeset.valid &&
        b.bits.writeset.valid &&
        a.bits.writeset.bits === b.bits.writeset.bits
    val unknownConflict = (a.bits.unknown || b.bits.unknown) && (a.bits.willWrite || b.bits.willWrite)
    val cacheSlotConflict =
      !a.bits.unknown &&
        !b.bits.unknown &&
        a.bits.cacheSlot === b.bits.cacheSlot &&
        (a.bits.willWrite || b.bits.willWrite)
    a.valid && b.valid && !sameWriteset && (unknownConflict || cacheSlotConflict)
  }
}

class KteIssueReq(params: ZamletParams) extends Bundle {
  val opType = KteOpType()

  // Original local-exec payload. CacheWaitLocal entries replay this when the
  // cache line becomes available. JteTransfer entries keep it for instruction
  // identity and register lifetime metadata until the final KTE bundle settles.
  val kinstr = new KinstrWithParams(params)

  // Meaningful for CacheWaitLocal. RS allocates this slot before handing the
  // waiting local instruction to KTE.
  val cacheSlot = params.cacheSlot()
}

object KteIssueReq {
  // Convert a KTE issue request into the same memory-footprint shape used by
  // the conflict checker. Sync requests have no memory footprint.
  def memFootprint(params: ZamletParams, valid: Bool, issue: KteIssueReq): Valid[KteMemFootprint] = {
    val footprint = Wire(Valid(new KteMemFootprint(params)))
    val base = issue.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    val hasMemoryWriteset =
      issue.opType === KteOpType.CacheWaitLocal || issue.opType === KteOpType.JteTransfer
    footprint.valid := valid && (issue.opType === KteOpType.CacheWaitLocal || issue.opType === KteOpType.JteTransfer)
    footprint.bits.unknown := issue.opType === KteOpType.JteTransfer
    footprint.bits.willWrite :=
      base.opcode === KInstrOpcode.StoreSimple || base.opcode === KInstrOpcode.StoreIdxUnord
    footprint.bits.cacheSlot := issue.cacheSlot
    footprint.bits.writeset.valid := hasMemoryWriteset && base.writeset.valid
    footprint.bits.writeset.bits := base.writeset.bits
    footprint
  }
}

class KteCacheWaitEntry(params: ZamletParams) extends Bundle {
  val kinstr = new KinstrWithParams(params)
  val slot = params.cacheSlot()
  val slotAvailable = Bool()
}

class KteEntry(params: ZamletParams) extends Bundle {
  val state = KteState()
  val kinstr = new KinstrWithParams(params)
  val complete = Vec(params.jInK, Bool())
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
  val rfRelease = new RfRelease(params)
  val releaseCacheSlot = Bool()
  val cacheSlot = params.cacheSlot()
}

class KamletTransferEngineIO(params: ZamletParams) extends Bundle {
  // Ready long-latency operations handed off by the future reservation station.
  val rsIssue = Flipped(Decoupled(new KteIssueReq(params)))

  // Combinational conflict check used by RS issue selection.
  val conflictMem = Input(Valid(new KteMemFootprint(params)))
  val conflict = Output(Bool())

  // Cache-ready aligned operation replayed into the Jamlet local-exec issue mux.
  // Kamlet top-level broadcasts this single stream to all Jamlets.
  val localReplay = Decoupled(new KinstrWithParams(params))

  // Physical registers whose KTE-owned lifetimes have ended.
  val rfRelease = Decoupled(new RfRelease(params))

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

  // CacheWaitLocal entries own a slot allocated by RS. KTE waits for that slot
  // to become available, replays the local instruction, then releases it.
  val kceReleaseSlot = Valid(new KceSlotRelease(params))
  val kceSlotIsAvailable = Flipped(Valid(params.cacheSlot()))
  // Status responses are guaranteed to arrive exactly one cycle after the
  // corresponding request, with no buffering on this path.
  val kceSlotStatusReq = Valid(params.cacheSlot())
  val kceSlotStatusResp = Flipped(Valid(Bool()))
  // Instr-start status is a fixed-latency Valid path. KCE must consume the
  // response without backpressure. If a query response says an ident has not
  // started, the corresponding start notification is guaranteed not to arrive
  // at KCE until after KCE has had a cycle to store the request as
  // WaitingForInstrIdent.
  val kceInstrStartedReq = Flipped(Valid(params.ident()))
  val kceInstrStartedResp = Valid(Bool())
  val kceInstrStartedNotify = Valid(params.ident())

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

  val rsIssueBuffer = Module(new DoubleBuffer(new KteIssueReq(params), true, true))
  rsIssueBuffer.io.i <> io.rsIssue
  val rsIssue = rsIssueBuffer.io.o

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

  val rfRelease = Wire(Decoupled(new RfRelease(params)))
  io.rfRelease <> DoubleBuffer(rfRelease, true, true)

  val kceReleaseSlot = Wire(Valid(new KceSlotRelease(params)))
  io.kceReleaseSlot := ValidBuffer(kceReleaseSlot, true)

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
  io.kceSlotStatusReq.valid := false.B
  io.kceSlotStatusReq.bits := DontCare

  val instrQuery0KteMatches = VecInit(kteEntries.map { entry =>
    val base = entry.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    entry.state =/= KteState.Free && base.instrIdent === io.kceInstrStartedReq.bits
  })
  val instrQuery0CacheWaitMatches = VecInit(cacheWaitEntries.map { entry =>
    val base = entry.bits.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    entry.valid && base.instrIdent === io.kceInstrStartedReq.bits
  })
  val instrQuery1Valid = RegNext(io.kceInstrStartedReq.valid, false.B)
  val instrQuery1Started =
    RegNext(instrQuery0KteMatches.asUInt.orR || instrQuery0CacheWaitMatches.asUInt.orR, false.B)
  io.kceInstrStartedResp.valid := instrQuery1Valid
  io.kceInstrStartedResp.bits := instrQuery1Started

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
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).bits.slot := rsIssue.bits.cacheSlot
    cacheWaitEntriesNext(issue0CacheWaitFreeIndex).bits.slotAvailable := false.B
    io.kceSlotStatusReq.valid := true.B
    io.kceSlotStatusReq.bits := rsIssue.bits.cacheSlot
  }
  errorsNext.unsupportedIssueOpcode :=
    rsIssue.fire && !issue0IsSupported

  val issue0InstrStartedNotifyValid = rsIssue.fire && issue0IsSupported
  val issue0InstrStartedNotifyIdent = issue0Base.instrIdent
  val instrNotify0Valid = RegNext(issue0InstrStartedNotifyValid, false.B)
  val instrNotify0Ident = RegNext(issue0InstrStartedNotifyIdent)
  val instrNotify1Valid = RegNext(instrNotify0Valid, false.B)
  val instrNotify1Ident = RegNext(instrNotify0Ident)
  // Delay the start notification relative to the status response path so KCE
  // cannot observe "not started" and then miss the start pulse before the
  // pending entry is visible to the wake logic.
  io.kceInstrStartedNotify.valid := instrNotify1Valid
  io.kceInstrStartedNotify.bits := instrNotify1Ident

  val issue1StatusIndex = RegNext(issue0CacheWaitFreeIndex)
  when (io.kceSlotStatusResp.valid) {
    cacheWaitEntriesNext(issue1StatusIndex).bits.slotAvailable :=
      cacheWaitEntries(issue1StatusIndex).bits.slotAvailable ||
        io.kceSlotStatusResp.bits
  }

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
    input0Resp.rfLaneOrder := input0Entry.kinstr.ordering.laneOrder
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
      (base.opcode === KInstrOpcode.LoadIdxUnord) -> indexed.completionSyncIdent,
      (base.opcode === KInstrOpcode.StoreIdxUnord) -> indexed.completionSyncIdent,
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

  def footprintFromCacheWait(entry: Valid[KteCacheWaitEntry]): Valid[KteMemFootprint] = {
    val footprint = Wire(Valid(new KteMemFootprint(params)))
    val base = entry.bits.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    footprint.valid := entry.valid
    footprint.bits.unknown := false.B
    footprint.bits.willWrite := base.opcode === KInstrOpcode.StoreSimple
    footprint.bits.cacheSlot := entry.bits.slot
    footprint.bits.writeset := base.writeset
    footprint
  }

  def footprintFromKteEntry(entry: KteEntry): Valid[KteMemFootprint] = {
    val footprint = Wire(Valid(new KteMemFootprint(params)))
    val base = entry.kinstr.kinstr.asTypeOf(new KInstrBase(params))
    footprint.valid :=
      entry.state =/= KteState.Free &&
        (base.opcode === KInstrOpcode.LoadIdxUnord || base.opcode === KInstrOpcode.StoreIdxUnord)
    footprint.bits.unknown := true.B
    footprint.bits.willWrite := base.opcode === KInstrOpcode.StoreIdxUnord
    footprint.bits.cacheSlot := 0.U
    footprint.bits.writeset := base.writeset
    footprint
  }

  // KTE owns work once it is inside the rsIssue buffer or the operation tables.
  // The visible rsIssue item writes the tables on fire, so it is still absent
  // from table state during this combinational conflict query. The external
  // io.rsIssue item is producer-owned and is intentionally not checked here.
  val rsIssueHidden = rsIssueBuffer.io.hidden
  val kteMemConflict = Wire(Bool()).suggestName("kteMemConflict")
  kteMemConflict :=
    KteMemFootprint.conflicts(io.conflictMem,
      KteIssueReq.memFootprint(params, rsIssueBuffer.io.fromState, rsIssue.bits)) ||
      KteMemFootprint.conflicts(io.conflictMem,
        KteIssueReq.memFootprint(params, rsIssueHidden.valid, rsIssueHidden.bits)) ||
      cacheWaitEntries.map(entry => KteMemFootprint.conflicts(io.conflictMem, footprintFromCacheWait(entry))).reduce(_ || _) ||
      kteEntries.map(entry => KteMemFootprint.conflicts(io.conflictMem, footprintFromKteEntry(entry))).reduce(_ || _)
  io.conflict := kteMemConflict

  // ============================================================
  // Cache wait wake
  // ============================================================

  errorsNext.wakeAlreadyAvailable := cacheWaitEntries.map(entry =>
    kceSlotIsAvailable.valid &&
      entry.valid &&
      entry.bits.slotAvailable &&
      entry.bits.slot === kceSlotIsAvailable.bits).reduce(_ || _)

  when (kceSlotIsAvailable.valid) {
    for (entry <- 0 until cacheWaitDepth) {
      when (cacheWaitEntries(entry).valid &&
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
    entry.valid && entry.bits.slotAvailable)
  val replay0Valid = VecInit(replay0CandidateVec).asUInt.orR
  val replay0Entry = PriorityEncoder(replay0CandidateVec)
  val replay0Kinstr = Wire(new KinstrWithParams(params))
  replay0Kinstr := cacheWaitEntries(replay0Entry).bits.kinstr
  replay0Kinstr.cacheSlot := cacheWaitEntries(replay0Entry).bits.slot
  val replay0Base = replay0Kinstr.kinstr.asTypeOf(new KInstrBase(params))
  val replay0LoadSimple = replay0Kinstr.kinstr.asTypeOf(new LoadSimpleInstr(params))
  val replay0StoreSimple = replay0Kinstr.kinstr.asTypeOf(new StoreSimpleInstr(params))
  val replay0IsLoadSimple = replay0Base.opcode === KInstrOpcode.LoadSimple
  val replay0IsStoreSimple = replay0Base.opcode === KInstrOpcode.StoreSimple
  val replay0MaskEnabled = Mux(replay0IsLoadSimple,
    replay0LoadSimple.maskEnabled, replay0StoreSimple.maskEnabled)
  val replay0MaskReg = Mux(replay0IsLoadSimple,
    replay0LoadSimple.maskReg, replay0StoreSimple.maskReg)

  val replay0ReleaseDelay = LocalExec.inputToDependentInputMinSeparation(params)
  val replay0ReleaseFifoSpace = releaseFifoDepth.U - releaseFifoCount
  val replay0CanStartReleaseDelay = replay0ReleaseFifoSpace >= replay0ReleaseDelay.U

  io.localReplay.valid := replay0Valid && replay0CanStartReleaseDelay
  io.localReplay.bits := replay0Kinstr

  val replay0ReleaseEntry = Wire(new KteReleaseEntry(params))
  for (rfUse <- replay0ReleaseEntry.rfRelease.uses) {
    rfUse.valid := false.B
    rfUse.addr := 0.U
  }
  replay0ReleaseEntry.rfRelease.uses(0).valid := replay0IsLoadSimple || replay0IsStoreSimple
  replay0ReleaseEntry.rfRelease.uses(0).addr := Mux(replay0IsLoadSimple, replay0LoadSimple.rfAddr,
    replay0StoreSimple.rfAddr)
  replay0ReleaseEntry.rfRelease.uses(1).valid := replay0MaskEnabled
  replay0ReleaseEntry.rfRelease.uses(1).addr := replay0MaskReg
  replay0ReleaseEntry.releaseCacheSlot := true.B
  replay0ReleaseEntry.cacheSlot := cacheWaitEntries(replay0Entry).bits.slot

  when (io.localReplay.fire) {
    cacheWaitEntriesNext(replay0Entry).valid := false.B
  }

  val replay0ReleaseDelayValid =
    ShiftRegister(io.localReplay.fire, replay0ReleaseDelay, false.B, true.B)
  val replay0ReleaseDelayBits =
    ShiftRegister(replay0ReleaseEntry, replay0ReleaseDelay)

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
  for (rfUse <- cleanup0ReleaseEntry.rfRelease.uses) {
    rfUse.valid := false.B
    rfUse.addr := 0.U
  }
  cleanup0ReleaseEntry.rfRelease.uses(0).valid := cleanup0IsJte
  cleanup0ReleaseEntry.rfRelease.uses(0).addr := cleanup0Indexed.reg
  cleanup0ReleaseEntry.rfRelease.uses(1).valid := cleanup0IsJte
  cleanup0ReleaseEntry.rfRelease.uses(1).addr := cleanup0Indexed.indexReg
  cleanup0ReleaseEntry.rfRelease.uses(2).valid := cleanup0IsJte && cleanup0Indexed.maskEnabled
  cleanup0ReleaseEntry.rfRelease.uses(2).addr := cleanup0Indexed.maskReg
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

  val release0NeedsRf = releaseFifo.io.deq.bits.rfRelease.uses.map(_.valid).reduce(_ || _)
  val release0RfReady = !release0NeedsRf || rfRelease.ready

  rfRelease.valid := releaseFifo.io.deq.valid && release0NeedsRf
  rfRelease.bits := releaseFifo.io.deq.bits.rfRelease

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
