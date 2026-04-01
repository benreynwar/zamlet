package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.{IdentHeader, MessageType, NetworkWord, SendType}

class MemoryEngineIO(params: ZamletParams) extends Bundle {
  val nRouters = params.nMemletRouters
  val nGSlots = params.nMemletGatheringSlots
  val nRSlots = params.nResponseBufferSlots

  // Router 0 coordinates (source for WriteLineResp headers)
  val routerX = Input(UInt(params.xPosWidth.W))
  val routerY = Input(UInt(params.yPosWidth.W))

  // AXI4 master port
  val axi = new AXI4MasterIO(
    addrBits = params.memAddrWidth,
    dataBits = params.memBeatWords * params.wordWidth,
    idBits = params.memAxiIdBits
  )

  // Gathering side: dequeue completed slots with metadata (from slice 0)
  val completeDeq = Flipped(Decoupled(new GatheringSlotMeta(params)))

  // Gathering side: read data (top level demuxes by routerIdx)
  val gatheringDataReq = Decoupled(new GatheringDataReadReq(params))
  val gatheringDataResp = Flipped(Decoupled(UInt(params.wordWidth.W)))

  // Gathering side: free a gathering slot (broadcast to all slices)
  val gatheringFree = Valid(UInt(log2Ceil(nGSlots).W))

  // Response side: write data to slice local storage
  val responseDataWrite = Output(new ResponseDataWrite(params))
  val responseDataRouterSel = Output(UInt(nRouters.W))

  // Response side: broadcast metadata events (allocate + sendable)
  val responseMetaEvent = Valid(new ResponseMetaEvent(params))

  // Response side: WriteLineResp to slice 0 (pre-built NetworkWord)
  val writeLineRespEnq = Decoupled(new NetworkWord(params))

  // Response side: slot freed by slice 0 (all routers done sending)
  val responseFree = Flipped(Valid(UInt(log2Ceil(nRSlots).W)))
}

object TrackerType extends ChiselEnum {
  val WL, RL, WLRL_W, WLRL_R = Value
}

class TrackerEntry(params: ZamletParams) extends Bundle {
  val ttype = TrackerType()
  val ident = UInt(params.identWidth.W)
  val sramAddr = UInt(params.sramAddrWidth.W)
  val sourceX = UInt(params.xPosWidth.W)
  val sourceY = UInt(params.yPosWidth.W)
  val partnerId = UInt(params.memAxiIdBits.W)
  val complete = Bool()
  val partnerComplete = Bool()
  val respSlotIdx = UInt(log2Ceil(params.nResponseBufferSlots).W)
}

class MemoryEngine(params: ZamletParams) extends Module {
  val io = IO(new MemoryEngineIO(params))

  val nIds = 1 << params.memAxiIdBits
  val nGSlots = params.nMemletGatheringSlots
  val nRSlots = params.nResponseBufferSlots
  val nRouters = params.nMemletRouters
  val localJamlets = params.memletLocalJamlets
  val cacheSlotWords = params.cacheSlotWords
  val wordsPerJamlet = params.cacheSlotWordsPerJamlet
  val beatsPerCacheLine = params.memBeatsPerCacheLine

  // ============================================================
  // Transaction tracker
  // ============================================================

  val tracker = RegInit(VecInit(Seq.fill(nIds) {
    val init = Wire(Valid(new TrackerEntry(params)))
    init.valid := false.B
    init.bits := DontCare
    init
  }))

  // ============================================================
  // AXI4 ID free list
  // ============================================================

  val idAvailableNext = Wire(UInt(nIds.W))
  val idAvailable = RegNext(idAvailableNext,
    init = ((BigInt(1) << nIds) - 1).U(nIds.W)).asTypeOf(UInt(nIds.W))

  val freeId0 = Wire(Valid(UInt(params.memAxiIdBits.W)))
  freeId0.valid := idAvailable.orR
  freeId0.bits := PriorityEncoder(idAvailable)

  val idAvailableAfter0 = idAvailable & ~(1.U(nIds.W) << freeId0.bits)

  val freeId1 = Wire(Valid(UInt(params.memAxiIdBits.W)))
  freeId1.valid := idAvailableAfter0.orR
  freeId1.bits := PriorityEncoder(idAvailableAfter0)

  // ============================================================
  // Internal queues
  // ============================================================

  val writeAddrQueue = Module(new Queue(new Bundle {
    val addr = UInt(params.wordWidth.W)
    val id = UInt(params.memAxiIdBits.W)
  }, entries = 4))
  writeAddrQueue.io.enq.valid := false.B
  writeAddrQueue.io.enq.bits := DontCare
  writeAddrQueue.io.deq.ready := false.B

  val writeSlotQueue = Module(new Queue(
    UInt(log2Ceil(nGSlots).W), entries = nGSlots))
  writeSlotQueue.io.enq.valid := false.B
  writeSlotQueue.io.enq.bits := DontCare
  writeSlotQueue.io.deq.ready := false.B

  val readAddrQueue = Module(new Queue(new Bundle {
    val addr = UInt(params.wordWidth.W)
    val id = UInt(params.memAxiIdBits.W)
  }, entries = 4))
  readAddrQueue.io.enq.valid := false.B
  readAddrQueue.io.enq.bits := DontCare
  readAddrQueue.io.deq.ready := false.B

  // ============================================================
  // Response buffer slot allocation tracking
  //
  // Central valid bits only — metadata is broadcast to slices via
  // responseMetaEvent. R Engine sets valid on allocation,
  // responseFree clears it when all routers finish sending.
  // ============================================================

  val respBufAllocated = RegInit(VecInit(Seq.fill(nRSlots)(false.B)))

  when(io.responseFree.valid) {
    respBufAllocated(io.responseFree.bits) := false.B
  }

  // First free slot, used by R Engine for lazy allocation
  val respBufFreeIdx = Wire(Valid(UInt(log2Ceil(nRSlots).W)))
  respBufFreeIdx.valid := VecInit(respBufAllocated.map(!_)).asUInt.orR
  respBufFreeIdx.bits := PriorityEncoder(respBufAllocated.map(!_))

  // Per-engine ID masks, combined into a single idAvailable update.
  val idsAllocByDq = Wire(UInt(nIds.W))
  val idsFreedByB = Wire(UInt(nIds.W))
  val idsFreedByR = Wire(UInt(nIds.W))
  idsAllocByDq := 0.U
  idsFreedByB := 0.U
  idsFreedByR := 0.U

  idAvailableNext :=
    (idAvailable | idsFreedByB | idsFreedByR) & ~idsAllocByDq

  // ============================================================
  // Dequeue Engine
  //
  // Single-cycle. Pops completeDeq, allocates IDs, enqueues addr
  // queues. For writes, enqueues slotIdx to writeSlotQueue; a
  // separate W Engine handles data copy and gathering slot free.
  // ============================================================

  // ============================================================
  // Default IO assignments
  // ============================================================

  io.completeDeq.ready := false.B

  io.gatheringDataReq.valid := false.B
  io.gatheringDataReq.bits := DontCare
  io.gatheringDataResp.ready := false.B
  io.gatheringFree.valid := false.B
  io.gatheringFree.bits := DontCare

  io.responseDataRouterSel := 0.U
  io.responseDataWrite.slotIdx := DontCare
  io.responseDataWrite.localDataIdx := DontCare
  io.responseDataWrite.data := DontCare

  io.responseMetaEvent.valid := false.B
  io.responseMetaEvent.bits := DontCare

  io.writeLineRespEnq.valid := false.B
  io.writeLineRespEnq.bits := DontCare

  io.axi.aw.valid := false.B
  io.axi.aw.bits := DontCare
  io.axi.w.valid := false.B
  io.axi.w.bits := DontCare
  io.axi.b.ready := false.B
  io.axi.ar.valid := false.B
  io.axi.ar.bits := DontCare
  io.axi.r.ready := false.B

  // ============================================================
  // Dequeue Engine body
  // ============================================================

  val dqMeta = io.completeDeq.bits
  val dqId0 = freeId0.bits
  val dqId1 = freeId1.bits
  val dqHaveIds = Mux(dqMeta.writes && dqMeta.reads,
    freeId0.valid && freeId1.valid, freeId0.valid)
  val dqValid = io.completeDeq.valid && dqHaveIds
  val dqCanEnqW = !dqMeta.writes || writeAddrQueue.io.enq.ready
  val dqCanEnqR = !dqMeta.reads || readAddrQueue.io.enq.ready
  val dqCanEnqS = !dqMeta.writes || writeSlotQueue.io.enq.ready

  // Drive queue enq — each valid gated on other streams' ready
  when(dqMeta.writes) {
    writeAddrQueue.io.enq.valid := dqValid && dqCanEnqR && dqCanEnqS
    writeAddrQueue.io.enq.bits.addr := dqMeta.writeAddr
    writeAddrQueue.io.enq.bits.id := dqId0

    writeSlotQueue.io.enq.valid := dqValid && dqCanEnqR && dqCanEnqW
    writeSlotQueue.io.enq.bits := dqMeta.slotIdx
  }
  when(dqMeta.reads) {
    readAddrQueue.io.enq.valid := dqValid && dqCanEnqW && dqCanEnqS
    readAddrQueue.io.enq.bits.addr := dqMeta.readAddr
    readAddrQueue.io.enq.bits.id := Mux(dqMeta.writes, dqId1, dqId0)
  }

  val dqCanFire = dqValid && dqCanEnqW && dqCanEnqR && dqCanEnqS
  io.completeDeq.ready := dqCanEnqW && dqCanEnqR && dqCanEnqS && dqHaveIds

  when(dqCanFire) {
    tracker(dqId0).valid := true.B
    tracker(dqId0).bits.ident := dqMeta.ident
    tracker(dqId0).bits.sramAddr := dqMeta.sramAddr
    tracker(dqId0).bits.sourceX := dqMeta.sourceX
    tracker(dqId0).bits.sourceY := dqMeta.sourceY
    tracker(dqId0).bits.complete := false.B
    tracker(dqId0).bits.partnerComplete := false.B
    tracker(dqId0).bits.ttype := Mux(dqMeta.reads,
      TrackerType.RL, TrackerType.WL)
    idsAllocByDq := 1.U(nIds.W) << dqId0

    when(dqMeta.writes && dqMeta.reads) {
      tracker(dqId0).bits.ttype := TrackerType.WLRL_W
      tracker(dqId0).bits.partnerId := dqId1
      idsAllocByDq :=
        (1.U(nIds.W) << dqId0) | (1.U(nIds.W) << dqId1)

      tracker(dqId1).valid := true.B
      tracker(dqId1).bits.ttype := TrackerType.WLRL_R
      tracker(dqId1).bits.ident := dqMeta.ident
      tracker(dqId1).bits.sramAddr := dqMeta.sramAddr
      tracker(dqId1).bits.sourceX := dqMeta.sourceX
      tracker(dqId1).bits.sourceY := dqMeta.sourceY
      tracker(dqId1).bits.partnerId := dqId0
      tracker(dqId1).bits.complete := false.B
      tracker(dqId1).bits.partnerComplete := false.B
    }
  }

  // ============================================================
  // AW Engine — pop writeAddrQueue, drive AXI4 AW
  // ============================================================

  val axiSize = log2Ceil(params.memBeatWords * params.wordBytes).U

  io.axi.aw.valid := writeAddrQueue.io.deq.valid
  io.axi.aw.bits.id := writeAddrQueue.io.deq.bits.id
  io.axi.aw.bits.addr := writeAddrQueue.io.deq.bits.addr
  io.axi.aw.bits.len := (beatsPerCacheLine - 1).U
  io.axi.aw.bits.size := axiSize
  io.axi.aw.bits.burst := 1.U  // INCR
  writeAddrQueue.io.deq.ready := io.axi.aw.ready

  // ============================================================
  // AR Engine — pop readAddrQueue, drive AXI4 AR
  // ============================================================

  io.axi.ar.valid := readAddrQueue.io.deq.valid
  io.axi.ar.bits.id := readAddrQueue.io.deq.bits.id
  io.axi.ar.bits.addr := readAddrQueue.io.deq.bits.addr
  io.axi.ar.bits.len := (beatsPerCacheLine - 1).U
  io.axi.ar.bits.size := axiSize
  io.axi.ar.bits.burst := 1.U  // INCR
  readAddrQueue.io.deq.ready := io.axi.ar.ready

  // ============================================================
  // W Engine — read gathering data, drive AXI4 W
  //
  // Request side issues gathering reads (can run ahead).
  // Response side drives AXI W from gathering responses.
  // ============================================================

  val wReqWord = RegInit(0.U(log2Ceil(cacheSlotWords).W))
  val wRespWord = RegInit(0.U(log2Ceil(cacheSlotWords).W))
  val wSlotIdx = writeSlotQueue.io.deq.bits
  val wActive = writeSlotQueue.io.deq.valid

  // Slots waiting to be freed after all responses drain
  val wFreeQueue = Module(new Queue(
    UInt(log2Ceil(nGSlots).W), entries = nGSlots))
  wFreeQueue.io.enq.valid := false.B
  wFreeQueue.io.enq.bits := DontCare
  wFreeQueue.io.deq.ready := false.B

  // Request side: issue gathering reads
  io.gatheringDataReq.valid := wActive
  io.gatheringDataReq.bits.routerIdx := wReqWord & (nRouters - 1).U
  io.gatheringDataReq.bits.slotIdx := wSlotIdx
  io.gatheringDataReq.bits.wordIdx := wReqWord >> log2Ceil(nRouters)

  when(io.gatheringDataReq.fire) {
    wReqWord := wReqWord + 1.U
    when(wReqWord === (cacheSlotWords - 1).U) {
      writeSlotQueue.io.deq.ready := true.B
      wFreeQueue.io.enq.valid := true.B
      wFreeQueue.io.enq.bits := wSlotIdx
    }
  }

  // Response side: drive AXI W from gathering responses
  io.gatheringDataResp.ready := io.axi.w.ready
  io.axi.w.valid := io.gatheringDataResp.valid
  io.axi.w.bits.data := io.gatheringDataResp.bits
  io.axi.w.bits.strb :=
    ((BigInt(1) << (params.memBeatWords * params.wordBytes)) - 1).U
  io.axi.w.bits.last := wRespWord === (cacheSlotWords - 1).U

  when(io.axi.w.fire) {
    wRespWord := wRespWord + 1.U
    when(wRespWord === (cacheSlotWords - 1).U) {
      wFreeQueue.io.deq.ready := true.B
      io.gatheringFree.valid := true.B
      io.gatheringFree.bits := wFreeQueue.io.deq.bits
    }
  }

  // ============================================================
  // B Engine — accept AXI4 B, update tracker
  //
  // WL: enqueue WriteLineResp, free entry immediately.
  // WLRL_W: set complete (tracker scan handles the rest).
  // ============================================================

  io.axi.b.ready := !(tracker(io.axi.b.bits.id).bits.ttype === TrackerType.WL) ||
    io.writeLineRespEnq.ready

  when(io.axi.b.fire) {
    when(tracker(io.axi.b.bits.id).bits.ttype === TrackerType.WL) {
      val trkB = tracker(io.axi.b.bits.id).bits
      val hdr = Wire(new IdentHeader(params))
      hdr.targetX := trkB.sourceX
      hdr.targetY := trkB.sourceY
      hdr.sourceX := io.routerX
      hdr.sourceY := io.routerY
      hdr.length := 0.U
      hdr.messageType := MessageType.WriteLineResp
      hdr.sendType := SendType.Single
      hdr.ident := trkB.ident
      hdr._padding := 0.U
      io.writeLineRespEnq.valid := true.B
      io.writeLineRespEnq.bits.data := hdr.asUInt
      io.writeLineRespEnq.bits.isHeader := true.B
      tracker(io.axi.b.bits.id).valid := false.B
      idsFreedByB := 1.U(nIds.W) << io.axi.b.bits.id
    }.otherwise {
      tracker(io.axi.b.bits.id).bits.complete := true.B
      val partnerId = tracker(io.axi.b.bits.id).bits.partnerId
      tracker(partnerId).bits.partnerComplete := true.B
    }
  }

  // rComplete: set by R Engine on rlast (defined later)
  val rComplete = Wire(Valid(UInt(params.memAxiIdBits.W)))
  rComplete.valid := false.B
  rComplete.bits := DontCare

  when(rComplete.valid) {
    tracker(rComplete.bits).bits.complete := true.B
    when(tracker(rComplete.bits).bits.ttype === TrackerType.WLRL_R) {
      val partnerId = tracker(rComplete.bits).bits.partnerId
      tracker(partnerId).bits.partnerComplete := true.B
    }
  }

  // ============================================================
  // R Engine — accept AXI4 R beats, scatter data, manage tracker
  //
  // Stage A: Accept R beat, allocate response buffer slot on first
  // beat. Stage B: scatter data, emit events, signal rComplete.
  // Assumes AXI R does not interleave beats from different IDs.
  // ============================================================

  val raAxi = io.axi.r
  val raNeedsAlloc = RegInit(Bool(), true.B)
  val raCanAlloc = respBufFreeIdx.valid
  val raSlotIdx = respBufFreeIdx.bits
  val raCanProcess = !raNeedsAlloc || raCanAlloc
  val raBeatCount = RegInit(0.U(log2Ceil(beatsPerCacheLine).W))

  val rbValid = RegInit(Bool(), init=false.B)
  val rbData = Reg(UInt(params.wordWidth.W))
  val rbSlotIdx = Reg(UInt(log2Ceil(nRSlots).W))
  val rbBeatCount = Reg(UInt(log2Ceil(beatsPerCacheLine).W))
  val rbAxiId = Reg(UInt(params.memAxiIdBits.W))
  val rbIsAllocBeat = Reg(Bool())
  val rbIsLastBeat = Reg(Bool())

  val rbReady = true.B

  raAxi.ready := raCanProcess && (!rbValid || rbReady)
  when (raAxi.fire) {
    when (raBeatCount === (beatsPerCacheLine - 1).U) {
      raBeatCount := 0.U
      raNeedsAlloc := true.B
    } .otherwise {
      raBeatCount := raBeatCount + 1.U;
      raNeedsAlloc := false.B
    }
    rbValid := true.B
    rbData := raAxi.bits.data
    rbBeatCount := raBeatCount
    rbAxiId := raAxi.bits.id
    rbIsAllocBeat := raNeedsAlloc
    rbIsLastBeat := raAxi.bits.last
    when (raNeedsAlloc) {
      respBufAllocated(raSlotIdx) := true.B
      tracker(raAxi.bits.id).bits.respSlotIdx := raSlotIdx
      rbSlotIdx := raSlotIdx
    }
  } .elsewhen (rbReady) {
    rbValid := false.B
  }

  // Scatter address computation
  val rbJamletIdx = rbBeatCount & (params.jInK - 1).U
  val rbRouterIdx = rbJamletIdx >> log2Ceil(localJamlets)
  val rbLocalJamlet = rbJamletIdx & (localJamlets - 1).U
  val rbWordInJamlet = rbBeatCount >> log2Ceil(params.jInK)
  val rbLocalDataIdx = rbLocalJamlet * wordsPerJamlet.U + rbWordInJamlet

  // ============================================================
  // R Engine stage B — scatter data, emit events, signal rComplete
  // ============================================================

  when(rbValid) {
    io.responseDataRouterSel := 1.U(nRouters.W) << rbRouterIdx
    io.responseDataWrite.slotIdx := rbSlotIdx
    io.responseDataWrite.localDataIdx := rbLocalDataIdx
    io.responseDataWrite.data := rbData

    when(rbIsAllocBeat) {
      val trkEntry = tracker(rbAxiId).bits
      io.responseMetaEvent.valid := true.B
      io.responseMetaEvent.bits.isSendable := false.B
      io.responseMetaEvent.bits.slotIdx := rbSlotIdx
      io.responseMetaEvent.bits.ident := trkEntry.ident
      io.responseMetaEvent.bits.sramAddr := trkEntry.sramAddr
      io.responseMetaEvent.bits.responseType := Mux(
        trkEntry.ttype === TrackerType.RL,
        MemletResponseType.ReadLine,
        MemletResponseType.WlrlRead
      )
    }

    when(rbIsLastBeat) {
      rComplete.valid := true.B
      rComplete.bits := rbAxiId
    }
  }

  // ============================================================
  // Tracker scan — generate sendable events from tracker state
  //
  // Each cycle, find one actionable entry and process it:
  // RL + complete → emit sendable, free entry.
  // WLRL_R + complete + partnerComplete → emit sendable, free both.
  // R Engine allocate events have priority on responseMetaEvent.
  // ============================================================

  val scanMatch = Wire(Vec(nIds, Bool()))
  for (i <- 0 until nIds) {
    val e = tracker(i)
    scanMatch(i) := e.valid && e.bits.complete && (
      e.bits.ttype === TrackerType.RL ||
      (e.bits.ttype === TrackerType.WLRL_R && e.bits.partnerComplete)
    )
  }

  val scanFound = scanMatch.asUInt.orR
  val scanIdx = PriorityEncoder(scanMatch.asUInt)
  val scanEntry = tracker(scanIdx)
  val rbAllocEvent = rbValid && rbIsAllocBeat

  when(scanFound && !rbAllocEvent) {
    io.responseMetaEvent.valid := true.B
    io.responseMetaEvent.bits.isSendable := true.B
    io.responseMetaEvent.bits.slotIdx := scanEntry.bits.respSlotIdx
    io.responseMetaEvent.bits.ident := DontCare
    io.responseMetaEvent.bits.sramAddr := DontCare
    io.responseMetaEvent.bits.responseType := DontCare

    tracker(scanIdx).valid := false.B
    idsFreedByR := 1.U(nIds.W) << scanIdx

    when(scanEntry.bits.ttype === TrackerType.WLRL_R) {
      val partnerId = scanEntry.bits.partnerId
      tracker(partnerId).valid := false.B
      idsFreedByR := (1.U(nIds.W) << scanIdx) | (1.U(nIds.W) << partnerId)
    }
  }
}
