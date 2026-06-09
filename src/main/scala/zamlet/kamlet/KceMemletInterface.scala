package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.SendCacheLineCmd
import zamlet.network.{CacheLineHeader, MessageType, NetworkWord, SendType}
import zamlet.utils.{DoubleBuffer, ValidBuffer}

class KceMemletInterfaceErrors extends Bundle {
  val fetchTableFull = Bool()
  val jceFetchDoneUnknownSlot = Bool()
  val jceFetchDoneDuplicate = Bool()
  val packetInBadMessageType = Bool()
  val packetInDrop = Bool()
}

class KceFetchRequestEntry(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val addr = params.cacheLineAddr()
  val jceDone = Vec(params.jInK, Bool())
  val controlQueued = Bool()
}

class KceMemletInterfaceIO(params: ZamletParams) extends Bundle {
  val knetX = Input(params.xPos())
  val knetY = Input(params.yPos())
  val memletKnetX = Input(params.xPos())
  val memletKnetY = Input(params.yPos())

  // Fetch requests from the cache tag table and per-Jamlet fetch completion from JCE.
  val fetchSlotReq = Flipped(Decoupled(new KceFetchSlotReq(params)))
  val fetchSlotComplete = Valid(params.cacheSlot())
  val jceFetchDone = Vec(params.jInK, Flipped(Valid(params.cacheSlot())))

  // Dirty writeback requests from the cache tag table and per-Jamlet writeback triggers.
  val writebackSlotReq = Flipped(Decoupled(new KceWritebackSlotReq(params)))
  val writebackSlotComplete = Valid(params.cacheSlot())
  val jceWritebackReq = Vec(params.jInK, Valid(new SendCacheLineCmd(params)))

  // Kamlet-network control-packet path to/from Memlet.
  val packetIn = Flipped(Decoupled(new NetworkWord(params)))
  val packetOut = Decoupled(new NetworkWord(params))

  val errors = Output(new KceMemletInterfaceErrors)
}

class KceMemletInterface(params: ZamletParams) extends Module {
  val io = IO(new KceMemletInterfaceIO(params))
  val mip = params.kceMemletInterfaceParams

  // ============================================================
  // IO buffering
  // ============================================================

  val fetchSlotReq = DoubleBuffer(io.fetchSlotReq, mip.fetchSlotReqFB, mip.fetchSlotReqBB)
  val fetchSlotComplete = Wire(Valid(params.cacheSlot()))
  io.fetchSlotComplete := ValidBuffer(fetchSlotComplete, mip.fetchSlotCompleteBuffer)

  val jceWritebackReqRaw = Wire(Vec(params.jInK, Valid(new SendCacheLineCmd(params))))
  val jceWritebackReq = (0 until params.jInK).map { jInK =>
    val req = jceWritebackReqRaw(jInK)
    io.jceWritebackReq(jInK) := ValidBuffer(req, mip.jceWritebackReqBuffer)
    req
  }

  val jceFetchDone = (0 until params.jInK).map { jInK =>
    ValidBuffer(io.jceFetchDone(jInK), mip.jceFetchDoneBuffer)
  }

  val writebackSlotReq =
    DoubleBuffer(io.writebackSlotReq, mip.writebackSlotReqFB, mip.writebackSlotReqBB)
  val writebackSlotComplete = Wire(Valid(params.cacheSlot()))
  io.writebackSlotComplete := ValidBuffer(writebackSlotComplete, mip.writebackSlotCompleteBuffer)

  val packetIn = DoubleBuffer(io.packetIn, mip.packetInFB, mip.packetInBB)
  val packetOut = Wire(Decoupled(new NetworkWord(params)))
  io.packetOut <> DoubleBuffer(packetOut, mip.packetOutFB, mip.packetOutBB)

  val errors = Wire(new KceMemletInterfaceErrors)
  errors := 0.U.asTypeOf(errors)
  io.errors := RegNext(errors)

  // ============================================================
  // Fetch request table
  // ============================================================

  val fetchEntriesInitial = Wire(Vec(params.nCacheRequests, Valid(new KceFetchRequestEntry(params))))
  fetchEntriesInitial := 0.U.asTypeOf(fetchEntriesInitial)

  val fetchEntriesNext = Wire(Vec(params.nCacheRequests, Valid(new KceFetchRequestEntry(params))))
  val fetchEntries = RegEnable(fetchEntriesNext, fetchEntriesInitial, true.B)
  fetchEntriesNext := fetchEntries

  private val fetchEntryIndexWidth = log2Ceil(params.nCacheRequests)
  val fetchFreeEntryUpdate = Wire(Bool())
  val fetchFreeEntryNext = Wire(UInt(fetchEntryIndexWidth.W))
  val fetchFreeEntry = RegEnable(fetchFreeEntryNext, 0.U, fetchFreeEntryUpdate)
  fetchFreeEntryUpdate := false.B
  fetchFreeEntryNext := fetchFreeEntry

  val fetchHasFreeEntry = VecInit(fetchEntries.map { entry =>
    !entry.valid
  }).asUInt.orR

  // ============================================================
  // fetch0/fetch1 admission
  // ============================================================

  val fetch0Out = Wire(Decoupled(new KceFetchSlotReq(params)))
  val fetch1In = DoubleBuffer(fetch0Out, mip.fetch01FB, mip.fetch01BB)

  fetch0Out.valid := fetchSlotReq.valid && fetchHasFreeEntry
  fetch0Out.bits := fetchSlotReq.bits
  fetchSlotReq.ready := fetchHasFreeEntry && fetch0Out.ready
  errors.fetchTableFull := fetchSlotReq.valid && !fetchHasFreeEntry

  when (fetch1In.fire) {
    fetchEntriesNext(fetchFreeEntry).valid := true.B
    fetchEntriesNext(fetchFreeEntry).bits.slot := fetch1In.bits.slot
    fetchEntriesNext(fetchFreeEntry).bits.addr := fetch1In.bits.addr
    fetchEntriesNext(fetchFreeEntry).bits.jceDone := 0.U.asTypeOf(fetchEntriesNext(fetchFreeEntry).bits.jceDone)
    fetchEntriesNext(fetchFreeEntry).bits.controlQueued := false.B
  }

  val fetchFreeEntryCandidates = Wire(Vec(params.nCacheRequests, Bool()))
  for (entry <- 0 until params.nCacheRequests) {
    fetchFreeEntryCandidates(entry) := !fetchEntries(entry).valid && fetchFreeEntry =/= entry.U
  }
  when (fetch1In.fire && fetchFreeEntryCandidates.asUInt.orR) {
    fetchFreeEntryUpdate := true.B
    fetchFreeEntryNext := PriorityEncoder(fetchFreeEntryCandidates)
  }

  fetch1In.ready := true.B

  // ============================================================
  // JCE fetch done tracking
  // ============================================================

  val jceFetchDoneUnknown = Wire(Vec(params.jInK, Bool()))
  val jceFetchDoneDuplicate = Wire(Vec(params.jInK, Bool()))
  jceFetchDoneUnknown := 0.U.asTypeOf(jceFetchDoneUnknown)
  jceFetchDoneDuplicate := 0.U.asTypeOf(jceFetchDoneDuplicate)

  for (jInK <- 0 until params.jInK) {
    val doneMatches = VecInit((0 until params.nCacheRequests).map { entry =>
      fetchEntries(entry).valid && fetchEntries(entry).bits.slot === jceFetchDone(jInK).bits
    })
    val doneHasMatch = doneMatches.asUInt.orR
    val doneEntry = PriorityEncoder(doneMatches)

    when (jceFetchDone(jInK).valid && doneHasMatch) {
      fetchEntriesNext(doneEntry).bits.jceDone(jInK) := true.B
    }

    jceFetchDoneUnknown(jInK) := jceFetchDone(jInK).valid && !doneHasMatch
    jceFetchDoneDuplicate(jInK) :=
      jceFetchDone(jInK).valid && doneHasMatch && fetchEntries(doneEntry).bits.jceDone(jInK)
  }

  errors.jceFetchDoneUnknownSlot := jceFetchDoneUnknown.asUInt.orR
  errors.jceFetchDoneDuplicate := jceFetchDoneDuplicate.asUInt.orR

  // ============================================================
  // Fetch complete scan
  // ============================================================

  val completeMatches = VecInit((0 until params.nCacheRequests).map { entry =>
    fetchEntries(entry).valid && fetchEntries(entry).bits.jceDone.asUInt.andR
  })
  val completeHasMatch = completeMatches.asUInt.orR
  val completeEntry = PriorityEncoder(completeMatches)

  fetchSlotComplete.valid := completeHasMatch
  fetchSlotComplete.bits := fetchEntries(completeEntry).bits.slot
  when (fetchSlotComplete.valid) {
    fetchEntriesNext(completeEntry).valid := false.B
  }

  jceWritebackReqRaw := 0.U.asTypeOf(jceWritebackReqRaw)
  for (jInK <- 0 until params.jInK) {
    jceWritebackReq(jInK).bits.slot := writebackSlotReq.bits.slot
  }

  // ============================================================
  // Fetch control packet output
  // ============================================================

  val fetchTx0Matches = VecInit((0 until params.nCacheRequests).map { entry =>
    fetchEntries(entry).valid && !fetchEntries(entry).bits.controlQueued
  })
  val fetchTx0HasMatch = fetchTx0Matches.asUInt.orR
  val fetchTx0Entry = PriorityEncoder(fetchTx0Matches)
  val fetchTx0Out = Wire(Decoupled(UInt(fetchEntryIndexWidth.W)))
  val fetchTx1In = DoubleBuffer(fetchTx0Out, mip.fetchTx01FB, mip.fetchTx01BB)

  fetchTx0Out.valid := fetchTx0HasMatch
  fetchTx0Out.bits := fetchTx0Entry
  when (fetchTx0Out.fire) {
    fetchEntriesNext(fetchTx0Entry).bits.controlQueued := true.B
  }

  val fetchPacketOut = Wire(Decoupled(new NetworkWord(params)))

  val fetchTx1IsBodyNext = Wire(Bool())
  val fetchTx1IsBody = RegEnable(fetchTx1IsBodyNext, false.B, fetchPacketOut.fire)
  fetchTx1IsBodyNext := !fetchTx1IsBody

  val fetchTx1Header = Wire(new CacheLineHeader(params))
  fetchTx1Header := 0.U.asTypeOf(fetchTx1Header)
  fetchTx1Header.targetX := io.memletKnetX
  fetchTx1Header.targetY := io.memletKnetY
  fetchTx1Header.sourceX := io.knetX
  fetchTx1Header.sourceY := io.knetY
  fetchTx1Header.length := 1.U
  fetchTx1Header.messageType := MessageType.ReadLineAddr
  fetchTx1Header.sendType := SendType.Single
  fetchTx1Header.slot := fetchEntries(fetchTx1In.bits).bits.slot

  val fetchTx1AddrWord =
    fetchEntries(fetchTx1In.bits).bits.addr.asTypeOf(params.word())

  fetchPacketOut.valid := fetchTx1In.valid
  fetchPacketOut.bits.isHeader := !fetchTx1IsBody
  fetchPacketOut.bits.data := Mux(
    fetchTx1IsBody,
    fetchTx1AddrWord,
    fetchTx1Header.asUInt)
  fetchTx1In.ready := fetchPacketOut.ready && fetchTx1IsBody

  // ============================================================
  // Writeback control packet output
  // ============================================================

  val writebackPacketOut = Wire(Decoupled(new NetworkWord(params)))

  val writebackTxIsBodyNext = Wire(Bool())
  val writebackTxIsBody =
    RegEnable(writebackTxIsBodyNext, false.B, writebackPacketOut.fire)
  writebackTxIsBodyNext := !writebackTxIsBody

  val writebackTxHeader = Wire(new CacheLineHeader(params))
  writebackTxHeader := 0.U.asTypeOf(writebackTxHeader)
  writebackTxHeader.targetX := io.memletKnetX
  writebackTxHeader.targetY := io.memletKnetY
  writebackTxHeader.sourceX := io.knetX
  writebackTxHeader.sourceY := io.knetY
  writebackTxHeader.length := 1.U
  writebackTxHeader.messageType := MessageType.WriteLineAddr
  writebackTxHeader.sendType := SendType.Single
  writebackTxHeader.slot := writebackSlotReq.bits.slot

  val writebackTxAddrWord =
    writebackSlotReq.bits.addr.asTypeOf(params.word())

  writebackPacketOut.valid := writebackSlotReq.valid
  writebackPacketOut.bits.isHeader := !writebackTxIsBody
  writebackPacketOut.bits.data := Mux(
    writebackTxIsBody,
    writebackTxAddrWord,
    writebackTxHeader.asUInt)
  writebackSlotReq.ready := writebackPacketOut.ready && writebackTxIsBody

  for (jInK <- 0 until params.jInK) {
    jceWritebackReq(jInK).valid := writebackSlotReq.fire
  }

  // Writebacks have priority so the scanner can keep making empty slots.
  packetOut.valid := writebackPacketOut.valid || fetchPacketOut.valid
  packetOut.bits := Mux(writebackPacketOut.valid, writebackPacketOut.bits, fetchPacketOut.bits)
  writebackPacketOut.ready := packetOut.ready
  fetchPacketOut.ready := packetOut.ready && !writebackPacketOut.valid

  writebackSlotComplete.valid := false.B
  writebackSlotComplete.bits := DontCare

  // ============================================================
  // Incoming Memlet control packet decode
  // ============================================================

  val packetInHeader = packetIn.bits.data.asTypeOf(new CacheLineHeader(params))
  val packetInMessageIsDrop =
    packetInHeader.messageType === MessageType.ReadLineAddrDrop ||
      packetInHeader.messageType === MessageType.WriteLineAddrDrop ||
      packetInHeader.messageType === MessageType.WriteLineReadLineAddrDrop ||
      packetInHeader.messageType === MessageType.WriteLineDataDrop
  val packetInMessageIsWritebackResp =
    packetInHeader.messageType === MessageType.WriteLineResp
  val packetInExpected =
    packetIn.bits.isHeader &&
      (packetInMessageIsDrop || packetInMessageIsWritebackResp)

  when (packetIn.valid && packetIn.bits.isHeader && packetInMessageIsWritebackResp) {
    writebackSlotComplete.valid := true.B
    writebackSlotComplete.bits := packetInHeader.slot
  }

  errors.packetInBadMessageType :=
    packetIn.valid && packetIn.bits.isHeader && !packetInExpected
  errors.packetInDrop :=
    packetIn.valid && packetIn.bits.isHeader && packetInMessageIsDrop

  packetIn.ready := true.B
}
