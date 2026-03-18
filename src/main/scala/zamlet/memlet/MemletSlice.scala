package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{CombinedNetworkNode, MessageType, NetworkWord, AddressHeader}

object KtbState extends ChiselEnum {
  val Idle, ReceiveReadLineAddr, ReceiveWriteAddr,
      ReceiveReadAddr, ReceiveData, DrainAndDrop = Value
}

class MemletSliceIO(params: ZamletParams) extends Bundle {
  // Router position
  val x = Input(UInt(params.xPosWidth.W))
  val y = Input(UInt(params.yPosWidth.W))
  val kBaseX = Input(UInt(params.xPosWidth.W))
  val kBaseY = Input(UInt(params.yPosWidth.W))

  // When true, this slice handles address packets and gathering metadata
  val isSlice0 = Input(Bool())

  // Mesh ports — A channels
  val aNi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aNo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aSi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aSo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aEi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aEo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aWi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aWo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))

  // Mesh ports — B channels
  val bNi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bNo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bSi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bSo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bEi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bEo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bWi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bWo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))

  // Associate a slice with an ident.
  // Propagates from slice 0.
  val identAllocIn = Flipped(Valid(new IdentAllocEvent(params)))
  val identAllocOut = Valid(new IdentAllocEvent(params))

  val responseMetaIn = Flipped(Valid(new ResponseMetaEvent(params)))
  val responseMetaOut = Valid(new ResponseMetaEvent(params))

  // Inter-slice propagation chains — inward (toward slice 0)
  val arrivedIn = Flipped(Valid(
    UInt(log2Ceil(params.nMemletGatheringSlots).W)))
  val arrivedOut = Valid(
    UInt(log2Ceil(params.nMemletGatheringSlots).W))
  val routerDoneIn = Flipped(Valid(
    UInt(log2Ceil(params.nResponseBufferSlots).W)))
  val routerDoneOut = Valid(
    UInt(log2Ceil(params.nResponseBufferSlots).W))

  // Gathering side — all slices
  val gatheringDataRead = new GatheringDataReadPort(params)

  // Response side — all slices
  val responseDataWrite = Flipped(Valid(new ResponseDataWrite(params)))

  // Gathering side — active when isSlice0
  val completeEnq = Decoupled(
    UInt(log2Ceil(params.nMemletGatheringSlots).W))
  val readLineEnq = Decoupled(new ReadLineEntry(params))
  val gatheringMetaRead = new GatheringMetaReadPort(params)
  val gatheringFree = Flipped(Valid(
    UInt(log2Ceil(params.nMemletGatheringSlots).W)))

  // Response side — active when isSlice0
  val writeLineResp = Flipped(Decoupled(new WriteLineRespEntry(params)))
  val responseFree = Valid(
    UInt(log2Ceil(params.nResponseBufferSlots).W))

  // Errors
  val errIdentAllocOverwrite = Output(Bool())
  val errBhoNotHeader = Output(Bool())
  val errUnexpectedMsgType = Output(Bool())
}

class MemletSlice(params: ZamletParams) extends Module {
  val io = IO(new MemletSliceIO(params))

  val router = Module(new CombinedNetworkNode(params))
  router.io.thisX := io.x
  router.io.thisY := io.y

  // Connect mesh ports to router
  router.io.aNi <> io.aNi
  router.io.aNo <> io.aNo
  router.io.aSi <> io.aSi
  router.io.aSo <> io.aSo
  router.io.aEi <> io.aEi
  router.io.aEo <> io.aEo
  router.io.aWi <> io.aWi
  router.io.aWo <> io.aWo
  router.io.bNi <> io.bNi
  router.io.bNo <> io.bNo
  router.io.bSi <> io.bSi
  router.io.bSo <> io.bSo
  router.io.bEi <> io.bEi
  router.io.bEo <> io.bEo
  router.io.bWi <> io.bWi
  router.io.bWo <> io.bWo

  // aHo unused — memlet doesn't receive on A channel locally
  router.io.aHo.ready := false.B

  // bHi unused — memlet doesn't inject on B channel locally
  router.io.bHi.valid := false.B
  router.io.bHi.bits := DontCare

  // ============================================================
  // Local storage
  // ============================================================

  val nGSlots = params.nMemletGatheringSlots
  val nRSlots = params.nResponseBufferSlots
  val localJamlets = params.memletLocalJamlets
  val localWords = params.memletLocalWords
  val wordsPerJamlet = params.cacheSlotWordsPerJamlet

  // Gathering slot ident replicas (for CacheLineData lookup)
  val gatherIdentValid = RegInit(VecInit(Seq.fill(nGSlots)(false.B)))
  val gatherIdentValue = Reg(Vec(nGSlots, UInt(params.identWidth.W)))

  // Gathering slot local data
  val gatherData = Reg(Vec(nGSlots,
    Vec(localWords, UInt(params.wordWidth.W))))

  // Gathering slot local arrived bits
  val gatherArrived = RegInit(VecInit(Seq.fill(nGSlots)(
    VecInit(Seq.fill(localJamlets)(false.B)))))

  // Gathering slot authoritative metadata (active when isSlice0)
  val gatherMetaValid = RegInit(VecInit(Seq.fill(nGSlots)(false.B)))
  val gatherMeta = Reg(Vec(nGSlots, new GatheringSlotMeta(params)))

  // Per-slot count of remote slices that have completed arrival
  // (active when isSlice0)
  val gatherRemoteCount = RegInit(VecInit(Seq.fill(nGSlots)(
    0.U(log2Ceil(params.nMemletRouters max 2).W))))

  // Response buffer local data
  val respData = Reg(Vec(nRSlots,
    Vec(localWords, UInt(params.wordWidth.W))))

  // Response buffer local routerDone
  val respRouterDone = RegInit(VecInit(
    Seq.fill(nRSlots)(false.B)))

  // Response buffer replicated metadata
  val respMetaValid = RegInit(VecInit(
    Seq.fill(nRSlots)(false.B)))
  val respMetaSendable = RegInit(VecInit(
    Seq.fill(nRSlots)(false.B)))
  val respMetaIdent = Reg(Vec(nRSlots,
    UInt(params.identWidth.W)))
  val respMetaSramAddr = Reg(Vec(nRSlots,
    UInt(params.sramAddrWidth.W)))
  val respMetaRespType = Reg(Vec(nRSlots,
    MemletResponseType()))

  // Drop queue
  val dropQueue = Module(new Queue(new DropEntry(params), entries = 4))
  dropQueue.io.enq.valid := false.B
  dropQueue.io.enq.bits := DontCare
  dropQueue.io.deq.ready := false.B

  // ============================================================
  // Gathering data read port (MemoryEngine reads from here)
  // ============================================================

  io.gatheringDataRead.data :=
    gatherData(io.gatheringDataRead.slotIdx)(io.gatheringDataRead.wordIdx)

  // ============================================================
  // Gathering metadata read port (slice 0 only)
  // ============================================================

  io.gatheringMetaRead.meta := gatherMeta(io.gatheringMetaRead.slotIdx)

  // ============================================================
  // Response buffer data write (from MemoryEngine R Engine)
  // ============================================================

  when(io.responseDataWrite.valid) {
    respData(io.responseDataWrite.bits.slotIdx)(
      io.responseDataWrite.bits.localDataIdx) :=
      io.responseDataWrite.bits.data
  }

  // ============================================================
  // Gathering slot free (from MemoryEngine via slice 0)
  // ============================================================

  when(io.isSlice0 && io.gatheringFree.valid) {
    gatherMetaValid(io.gatheringFree.bits) := false.B
    gatherIdentValid(io.gatheringFree.bits) := false.B
    gatherRemoteCount(io.gatheringFree.bits) := 0.U
  }

  // ============================================================
  // Propagation chains (to be implemented with FSMs)
  // ============================================================

  // Ident allocation (outward from slice 0): registered output.
  // Default: forward identAllocIn. KamletToBuffer overrides when
  // allocating at slice 0.
  val identAllocOutValid = RegInit(false.B)
  val identAllocOutBits = Reg(new IdentAllocEvent(params))

  identAllocOutValid := io.identAllocIn.valid
  identAllocOutBits := io.identAllocIn.bits

  val errIdentAllocOverwrite = Wire(Bool())
  errIdentAllocOverwrite := false.B

  when(io.identAllocIn.valid) {
    val idx = io.identAllocIn.bits.slotIdx
    errIdentAllocOverwrite := gatherIdentValid(idx)
    gatherIdentValid(idx) := true.B
    gatherIdentValue(idx) := io.identAllocIn.bits.ident
    for (j <- 0 until localJamlets) {
      gatherArrived(idx)(j) := false.B
    }
    localArrivedDone(idx) := false.B
  }

  io.identAllocOut.valid := identAllocOutValid
  io.identAllocOut.bits := identAllocOutBits
  io.errIdentAllocOverwrite := errIdentAllocOverwrite

  // Response buffer metadata: latch from upstream, forward downstream
  when(io.responseMetaIn.valid) {
    val idx = io.responseMetaIn.bits.slotIdx
    when(!io.responseMetaIn.bits.isSendable) {
      respMetaValid(idx) := true.B
      respMetaIdent(idx) := io.responseMetaIn.bits.ident
      respMetaSramAddr(idx) := io.responseMetaIn.bits.sramAddr
      respMetaRespType(idx) := io.responseMetaIn.bits.responseType
      respMetaSendable(idx) := false.B
    }.otherwise {
      respMetaSendable(idx) := true.B
    }
  }
  io.responseMetaOut := RegNext(io.responseMetaIn)

  // Per-slot flag: true once all local jamlets have arrived and
  // we've acted on it. Cleared when the slot is (re)allocated
  // via the ident alloc chain.
  val localArrivedDone = RegInit(VecInit(Seq.fill(nGSlots)(false.B)))

  // Detect newly-completed slots: all local arrived bits set,
  // ident replica still valid, not yet acted on
  val newLocalArrived = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    newLocalArrived(s) := gatherIdentValid(s) &&
      !localArrivedDone(s) &&
      gatherArrived(s).asUInt.andR
  }
  val anyNewLocal = newLocalArrived.asUInt.orR
  val newLocalSlot = PriorityEncoder(newLocalArrived)

  io.arrivedOut.valid := false.B
  io.arrivedOut.bits := DontCare

  // RouterDone: forward from downstream, merge with local events
  // (local event generation handled by BufferToKamlet below)
  io.routerDoneOut.valid := false.B
  io.routerDoneOut.bits := DontCare

  // Arrived count at slice 0
  when(io.isSlice0 && io.arrivedIn.valid) {
    gatherRemoteCount(io.arrivedIn.bits) :=
      gatherRemoteCount(io.arrivedIn.bits) + 1.U
  }

  // ============================================================
  // Slice 0 output defaults
  // ============================================================

  io.completeEnq.valid := false.B
  io.completeEnq.bits := DontCare
  io.readLineEnq.valid := false.B
  io.readLineEnq.bits := DontCare
  io.writeLineResp.ready := false.B
  io.responseFree.valid := false.B
  io.responseFree.bits := DontCare

  // aHi driven by BufferToKamlet (to be implemented)
  router.io.aHi.valid := false.B
  router.io.aHi.bits := DontCare

  // ============================================================
  // KamletToBuffer FSM
  //
  // Receives packets from the router's local B-channel output (bHo)
  // and writes data into gathering slots. Slice 0 handles all
  // message types (ReadLine, WriteLineAddr, WriteLineReadLineAddr,
  // CacheLineData). Other slices only handle CacheLineData.
  //
  // Packets arrive word-by-word: first an isHeader word containing
  // an AddressHeader, then `length` data words.
  // ============================================================

  // Alias for the router's local B-channel output port
  val bHo = router.io.bHo

  // Speculatively parse the current bHo word as an AddressHeader.
  // Only meaningful when bHo.bits.isHeader is true.
  val bHoHeader = bHo.bits.data.asTypeOf(new AddressHeader(params))

  val rxState = RegInit(KtbState.Idle)
  val rxHeader = Reg(new AddressHeader(params))  // latched in Idle
  val rxWordCount = Reg(UInt(4.W))  // data words received (counts up)
  val rxSlotIndex = Reg(UInt(log2Ceil(nGSlots).W))  // target slot
  val rxWordsRemaining = Reg(UInt(4.W))  // body words left (counts down)

  // Global jamlet index of the sender, from source coords relative
  // to kamlet base: jIndex = (sourceY - kBaseY) * jCols + (sourceX - kBaseX)
  val rxJIndex = Reg(UInt(log2Ceil(params.jInK).W))

  // Scan gatherMetaValid for the first free gathering slot.
  // Used by slice 0 when allocating on WriteLineAddr /
  // WriteLineReadLineAddr.
  val freeSlotVec = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    freeSlotVec(s) := !gatherMetaValid(s)
  }
  val freeSlotValid = freeSlotVec.asUInt.orR
  val freeSlotIdx = PriorityEncoder(freeSlotVec)

  // Match the incoming packet's ident against the local ident
  // replicas to find which gathering slot a CacheLineData packet
  // belongs to. Works on all slices.
  val identMatch = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    identMatch(s) := gatherIdentValid(s) &&
      gatherIdentValue(s) === bHoHeader.ident
  }
  val identFound = identMatch.asUInt.orR
  val identSlotIdx = PriorityEncoder(identMatch)

  // Default: don't consume from bHo. Overridden by FSM states.
  bHo.ready := false.B

  // ---- Idle state: routing decision ----
  // Consume the header word, check resources, and either:
  //   - accept: latch header + jIndex, go to a receive state
  //   - drop: enqueue drop response, go to DrainAndDrop
  //   - stall: leave bHo.ready low (resources and drop queue both full)

  io.errBhoNotHeader := rxState === KtbState.Idle &&
    bHo.valid && !bHo.bits.isHeader
  io.errUnexpectedMsgType := false.B

  when(rxState === KtbState.Idle && bHo.valid) {
    val jX = bHoHeader.sourceX - io.kBaseX
    val jY = bHoHeader.sourceY - io.kBaseY
    val jIdx = jY * params.jCols.U + jX

    // Latched unconditionally — only read by subsequent states,
    // which we only enter when bHo actually fires
    rxHeader := bHoHeader
    rxJIndex := jIdx

    when(io.isSlice0 &&
        bHoHeader.messageType === MessageType.ReadLine) {
      bHo.ready := true.B
      rxState := KtbState.ReceiveReadLineAddr
    }

    // WriteLineAddr / WriteLineReadLineAddr (slice 0 only):
    // Allocate a gathering slot and receive address body words.
    val isWLA = bHoHeader.messageType === MessageType.WriteLineAddr
    val isWLRLA = bHoHeader.messageType === MessageType.WriteLineReadLineAddr
    when(io.isSlice0 && (isWLA || isWLRLA)) {
      when(freeSlotValid) {
        bHo.ready := true.B
        rxSlotIndex := freeSlotIdx
        // Initialize authoritative metadata
        gatherMetaValid(freeSlotIdx) := true.B
        gatherMeta(freeSlotIdx).ident := bHoHeader.ident
        gatherMeta(freeSlotIdx).sramAddr := bHoHeader.address
        gatherMeta(freeSlotIdx).needsRead := isWLRLA
        // Set local ident replica
        gatherIdentValid(freeSlotIdx) := true.B
        gatherIdentValue(freeSlotIdx) := bHoHeader.ident
        for (j <- 0 until localJamlets) {
          gatherArrived(freeSlotIdx)(j) := false.B
        }
        // Propagate ident to downstream slices
        identAllocOutValid := true.B
        identAllocOutBits.slotIdx := freeSlotIdx
        identAllocOutBits.ident := bHoHeader.ident
        rxState := KtbState.ReceiveWriteAddr
      }.elsewhen(dropQueue.io.enq.ready) {
        bHo.ready := true.B
        dropQueue.io.enq.valid := true.B
        dropQueue.io.enq.bits.messageType := Mux(isWLA,
          MessageType.WriteLineDrop,
          MessageType.WriteLineReadLineDrop)
        dropQueue.io.enq.bits.ident := bHoHeader.ident
        dropQueue.io.enq.bits.targetX := bHoHeader.sourceX
        dropQueue.io.enq.bits.targetY := bHoHeader.sourceY
        rxWordsRemaining := bHoHeader.length
        rxState := KtbState.DrainAndDrop
      }
    }

    // CacheLineData (all slices): look up gathering slot by ident,
    // then receive data words into the slot's local storage.
    val isCLD = bHoHeader.messageType === MessageType.CacheLineData
    when(isCLD) {
      when(identFound) {
        bHo.ready := true.B
        rxSlotIndex := identSlotIdx
        rxWordCount := 0.U
        rxState := KtbState.ReceiveData
      }.elsewhen(dropQueue.io.enq.ready) {
        bHo.ready := true.B
        dropQueue.io.enq.valid := true.B
        dropQueue.io.enq.bits.messageType := MessageType.CacheLineDataDrop
        dropQueue.io.enq.bits.ident := bHoHeader.ident
        dropQueue.io.enq.bits.targetX := bHoHeader.sourceX
        dropQueue.io.enq.bits.targetY := bHoHeader.sourceY
        rxWordsRemaining := bHoHeader.length
        rxState := KtbState.DrainAndDrop
      }
    }

    // Error: message type not handled by this slice
    val isRL = bHoHeader.messageType === MessageType.ReadLine
    val knownSlice0 = isRL || isWLA || isWLRLA || isCLD
    val knownOther = isCLD
    io.errUnexpectedMsgType := Mux(io.isSlice0,
      !knownSlice0, !knownOther)
  }

  // ---- ReceiveReadLineAddr: forward 1 body word to readLineQueue ----
  // Drop decision happens here: if the queue can't accept, send a
  // ReadLineDrop instead. If drop queue is also full, stall.
  when(rxState === KtbState.ReceiveReadLineAddr && bHo.valid) {
    when(io.readLineEnq.ready) {
      bHo.ready := true.B
      io.readLineEnq.valid := true.B
      io.readLineEnq.bits.ident := rxHeader.ident
      io.readLineEnq.bits.sramAddr := rxHeader.address
      io.readLineEnq.bits.memAddr := bHo.bits.data
      rxState := KtbState.Idle
    }.elsewhen(dropQueue.io.enq.ready) {
      bHo.ready := true.B
      dropQueue.io.enq.valid := true.B
      dropQueue.io.enq.bits.messageType := MessageType.ReadLineDrop
      dropQueue.io.enq.bits.ident := rxHeader.ident
      dropQueue.io.enq.bits.targetX := rxHeader.sourceX
      dropQueue.io.enq.bits.targetY := rxHeader.sourceY
      rxState := KtbState.Idle
    }
  }

  // ---- ReceiveWriteAddr: store 1 body word (writeAddr) into slot ----
  when(rxState === KtbState.ReceiveWriteAddr && bHo.valid) {
    bHo.ready := true.B
    gatherMeta(rxSlotIndex).writeAddr := bHo.bits.data
    rxState := Mux(
      rxHeader.messageType === MessageType.WriteLineReadLineAddr,
      KtbState.ReceiveReadAddr,
      KtbState.Idle)
  }

  // ---- ReceiveReadAddr: store 1 body word (readAddr) into slot ----
  when(rxState === KtbState.ReceiveReadAddr && bHo.valid) {
    bHo.ready := true.B
    gatherMeta(rxSlotIndex).readAddr := bHo.bits.data
    rxState := KtbState.Idle
  }

  // ---- ReceiveData: store data words into gathering slot ----
  // Each word goes to gatherData(slot)(localJIdx * wordsPerJamlet + wordCount).
  // After the last word, mark this jamlet as arrived.
  when(rxState === KtbState.ReceiveData && bHo.valid) {
    bHo.ready := true.B
    val localJIdx = rxJIndex & (localJamlets - 1).U
    val dataIdx = localJIdx * wordsPerJamlet.U + rxWordCount
    gatherData(rxSlotIndex)(dataIdx) := bHo.bits.data
    val nextCount = rxWordCount + 1.U
    rxWordCount := nextCount
    when(nextCount === wordsPerJamlet.U) {
      gatherArrived(rxSlotIndex)(localJIdx) := true.B
      rxState := KtbState.Idle
    }
  }

  // ---- DrainAndDrop: consume and discard remaining body words ----
  when(rxState === KtbState.DrainAndDrop && bHo.valid) {
    bHo.ready := true.B
    val nextRemaining = rxWordsRemaining - 1.U
    rxWordsRemaining := nextRemaining
    when(nextRemaining === 0.U) {
      rxState := KtbState.Idle
    }
  }
}
