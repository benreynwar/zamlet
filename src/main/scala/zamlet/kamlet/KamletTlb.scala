package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.{Ordering, ZamletParams}
import zamlet.jamlet.{JamletTlbAvailable, JamletTlbReq, JamletTlbResp, JamletTlbStatus}
import zamlet.network.{KamletTlbReqHeader, KamletTlbRespHeader, MessageType, NetworkWord, SendType}
import zamlet.utils.{DoubleBuffer, ValidBuffer}

class KamletTlbOrderingUpdate(params: ZamletParams) extends Bundle {
  val physicalStripeAddr = UInt(params.memStripeAddrWidth.W)
  val ordering = new Ordering()
}

class KamletTlbPayload(params: ZamletParams) extends Bundle {
  val physicalStripeAddr = UInt(params.memStripeAddrWidth.W)
  val ordering = new Ordering()
}

class KamletTlbTagMeta(params: ZamletParams) extends Bundle {
  val jInK = UInt(log2Ceil(params.jInK).W)
  val req = new JamletTlbReq(params)
  val jamletReqIndex = UInt(log2Ceil(params.tlbReqTableDepth).W)
}

class KamletTlbJamletReqEntry(params: ZamletParams) extends Bundle {
  val valid = Bool()
  val jInK = UInt(log2Ceil(params.jInK).W)
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val byteIndex = UInt(log2Ceil(params.wordBytes).W)
}

object KamletTlbLamletReqState extends ChiselEnum {
  val WaitingFillReq = Value
  val WaitingResp = Value
  val ReadyWake = Value
}

class KamletTlbLamletReqEntry(params: ZamletParams) extends Bundle {
  val valid = Bool()
  val virtualStripeAddr = UInt(params.memStripeAddrWidth.W)
  val cacheIndex = UInt(log2Ceil(params.tlbCacheTableDepth).W)
  val physicalStripeAddr = UInt(params.memStripeAddrWidth.W)
  val ordering = new Ordering()
  val waiters = UInt(params.tlbReqTableDepth.W)
  val state = KamletTlbLamletReqState()
}

class KamletTlbLookup01(params: ZamletParams) extends Bundle {
  val jInK = UInt(log2Ceil(params.jInK).W)
  val req = new JamletTlbReq(params)
}

class KamletTlbLookup12(params: ZamletParams) extends Bundle {
  val jInK = UInt(log2Ceil(params.jInK).W)
  val req = new JamletTlbReq(params)
  val cacheHit = Bool()
  val cacheIndex = UInt(log2Ceil(params.tlbCacheTableDepth).W)
  val lamletMatch = Bool()
  val lamletIndex = UInt(log2Ceil(params.tlbReqTableDepth).W)
  val hasFreeJamletReq = Bool()
  val freeJamletReqIndex = UInt(log2Ceil(params.tlbReqTableDepth).W)
  val hasFreeLamletReq = Bool()
  val freeLamletReqIndex = UInt(log2Ceil(params.tlbReqTableDepth).W)
}

class KamletTlbResp01(params: ZamletParams) extends Bundle {
  val tlbReqSlot = UInt(log2Ceil(params.tlbReqTableDepth).W)
  val physicalStripeAddr = UInt(params.memStripeAddrWidth.W)
  val ordering = new Ordering()
}

class KamletTlbErrors extends Bundle {
  val packetInBadMessageType = Bool()
  val packetInUnexpectedBody = Bool()
  val respInvalidSlot = Bool()
  val respUnexpectedState = Bool()
  val claimRespQueueOverflow = Bool()
  val reqTxNoLamletMatch = Bool()
  val allocRespNoLamletMatch = Bool()
  val allocRespDuplicateLamletMatch = Bool()
  val reqTxDuplicateLamletMatch = Bool()
}

class KamletTlbIO(params: ZamletParams) extends Bundle {
  val knetX = Input(params.xPos())
  val knetY = Input(params.yPos())
  val lamletKnetX = Input(params.xPos())
  val lamletKnetY = Input(params.yPos())

  val tlbReq = Vec(params.jInK, Flipped(Decoupled(new JamletTlbReq(params))))
  val tlbResp = Vec(params.jInK, Decoupled(new JamletTlbResp(params)))
  val tlbAvailable = Vec(params.jInK, Valid(new JamletTlbAvailable(params)))

  val localOrderingUpdate = Flipped(Valid(new KamletTlbOrderingUpdate(params)))

  val packetOut = Decoupled(new NetworkWord(params))
  val packetIn = Flipped(Decoupled(new NetworkWord(params)))

  val errors = Output(new KamletTlbErrors)
}

class KamletTlb(params: ZamletParams) extends Module {
  val io = IO(new KamletTlbIO(params))
  val tp = params.kamletTlbParams
  val ttp = params.tlbTagTableParams
  require(params.tlbCacheTableDepth > 1)

  val jamletReqInitial = VecInit(Seq.fill(params.tlbReqTableDepth)(
    0.U.asTypeOf(new KamletTlbJamletReqEntry(params))))
  val jamletReqNext = Wire(Vec(params.tlbReqTableDepth, new KamletTlbJamletReqEntry(params)))
  val jamletReq = RegNext(jamletReqNext, jamletReqInitial)

  val lamletReqInitial = VecInit(Seq.fill(params.tlbReqTableDepth)(
    0.U.asTypeOf(new KamletTlbLamletReqEntry(params))))
  val lamletReqNext = Wire(Vec(params.tlbReqTableDepth, new KamletTlbLamletReqEntry(params)))
  val lamletReq = RegNext(lamletReqNext, lamletReqInitial)

  val tlbReq = Seq.tabulate(params.jInK) { jInK =>
    DoubleBuffer(io.tlbReq(jInK), tp.tlbReqFB, tp.tlbReqBB)
  }
  val tlbResp = Wire(Vec(params.jInK, Decoupled(new JamletTlbResp(params))))
  val tlbAvailable = Wire(Vec(params.jInK, Valid(new JamletTlbAvailable(params))))
  val localOrderingUpdate = ValidBuffer(io.localOrderingUpdate, tp.localOrderingUpdateBuffer)
  val packetIn = DoubleBuffer(io.packetIn, tp.packetInFB, tp.packetInBB)
  val packetOut = Wire(Decoupled(new NetworkWord(params)))
  val errors = Wire(new KamletTlbErrors)
  errors := 0.U.asTypeOf(new KamletTlbErrors)

  val tagTable = Module(new TagTable(
    tagWidth = params.memStripeAddrWidth,
    slotWidth = log2Ceil(params.tlbCacheTableDepth),
    params = ttp,
    respMetaType = new KamletTlbTagMeta(params),
    fillMetaType = UInt(0.W),
    payloadType = new KamletTlbPayload(params),
  ))

  tagTable.io.claimReq.valid := false.B
  tagTable.io.claimReq.bits := DontCare
  tagTable.io.allocReq.valid := false.B
  tagTable.io.allocReq.bits := DontCare
  tagTable.io.allocResp.ready := false.B
  tagTable.io.fillReq.ready := false.B
  tagTable.io.fillComplete.valid := false.B
  tagTable.io.fillComplete.bits := DontCare
  tagTable.io.release.valid := false.B
  tagTable.io.release.bits := DontCare
  tagTable.io.writebackReq.ready := true.B
  tagTable.io.writebackComplete.valid := false.B
  tagTable.io.writebackComplete.bits := DontCare
  tagTable.io.slotStatusReq.valid := false.B
  tagTable.io.slotStatusReq.bits := DontCare

  val claimRespQueueDepth = 4
  val claimRespQueueAlmostFullThreshold = (claimRespQueueDepth - 2).U
  val claimRespQueue = Module(new Queue(
    new TagClaimResp(
      log2Ceil(params.tlbCacheTableDepth),
      new KamletTlbTagMeta(params),
      new KamletTlbPayload(params)),
    claimRespQueueDepth))
  claimRespQueue.io.enq.valid := tagTable.io.claimResp.valid
  claimRespQueue.io.enq.bits := tagTable.io.claimResp.bits
  val claimRespQueueBelowThreshold =
    claimRespQueue.io.count < claimRespQueueAlmostFullThreshold
  errors.claimRespQueueOverflow := claimRespQueue.io.enq.valid && !claimRespQueue.io.enq.ready

  for (jInK <- 0 until params.jInK) {
    tlbResp(jInK).valid := false.B
    tlbResp(jInK).bits := DontCare
    io.tlbResp(jInK) <> DoubleBuffer(tlbResp(jInK), tp.tlbRespFB, tp.tlbRespBB)
    tlbAvailable(jInK).valid := false.B
    tlbAvailable(jInK).bits := DontCare
    io.tlbAvailable(jInK) := ValidBuffer(tlbAvailable(jInK), tp.tlbAvailableBuffer)
  }

  packetOut.valid := false.B
  packetOut.bits := DontCare
  io.packetOut <> DoubleBuffer(packetOut, tp.packetOutFB, tp.packetOutBB)
  dontTouch(localOrderingUpdate)

  def tagStateIsPresent(state: TagState.Type): Bool = {
    state === TagState.PresentClean || state === TagState.PresentDirty
  }

  // lookup0: choose one Jamlet lookup request.
  val lookup0Candidates = VecInit((0 until params.jInK).map { jInK =>
    tlbReq(jInK).valid
  })
  val lookup0Reqs = Wire(Vec(params.jInK, new JamletTlbReq(params)))
  for (jInK <- 0 until params.jInK) {
    lookup0Reqs(jInK) := tlbReq(jInK).bits
  }
  val lookup0 = Wire(Decoupled(new KamletTlbLookup01(params)))
  lookup0.valid := lookup0Candidates.reduce(_ || _)
  lookup0.bits.jInK := PriorityEncoder(lookup0Candidates)
  lookup0.bits.req := lookup0Reqs(lookup0.bits.jInK)
  for (jInK <- 0 until params.jInK) {
    tlbReq(jInK).ready := lookup0.ready && lookup0.bits.jInK === jInK.U
  }

  val freeJamletReqs = VecInit((0 until params.tlbReqTableDepth).map { i =>
    !jamletReq(i).valid
  })
  val hasFreeJamletReq = freeJamletReqs.asUInt.orR
  val freeJamletReqIndex = PriorityEncoder(freeJamletReqs)

  val freeLamletReqs = VecInit((0 until params.tlbReqTableDepth).map { i =>
    !lamletReq(i).valid
  })
  val hasFreeLamletReq = freeLamletReqs.asUInt.orR
  val freeLamletReqIndex = PriorityEncoder(freeLamletReqs)
  val freeLamletReq = Wire(Decoupled(UInt(log2Ceil(params.tlbReqTableDepth).W)))
  freeLamletReq.valid := hasFreeLamletReq
  freeLamletReq.bits := freeLamletReqIndex

  // claim0: non-mutating tag-table probe. Hits can return payload immediately;
  // misses are parked after the claim response decides whether allocation is needed.
  tagTable.io.claimReq.valid := lookup0.valid && claimRespQueueBelowThreshold
  tagTable.io.claimReq.bits.tag := lookup0.bits.req.virtualStripeAddr
  tagTable.io.claimReq.bits.willWrite := false.B
  tagTable.io.claimReq.bits.doClaim := false.B
  tagTable.io.claimReq.bits.claimIfPendingFill := false.B
  tagTable.io.claimReq.bits.meta.jInK := lookup0.bits.jInK
  tagTable.io.claimReq.bits.meta.req := lookup0.bits.req
  tagTable.io.claimReq.bits.meta.jamletReqIndex := 0.U
  lookup0.ready := claimRespQueueBelowThreshold

  val claimResp = claimRespQueue.io.deq
  val claimRespPresent = tagStateIsPresent(claimResp.bits.state)
  val claimRespLamletMatches = VecInit((0 until params.tlbReqTableDepth).map { i =>
    lamletReq(i).valid && lamletReq(i).cacheIndex === claimResp.bits.slot
  })
  val claimRespLamletMatch = claimRespLamletMatches.asUInt.orR
  val claimRespLamletIndex = PriorityEncoder(claimRespLamletMatches)
  val claimRespPending = claimResp.bits.hasSlot && !claimRespPresent
  val claimRespFreshMiss = !claimResp.bits.hasSlot
  val claimRespCanParkPending =
    claimRespPending && hasFreeJamletReq && claimRespLamletMatch
  val claimRespCanParkFresh =
    claimRespFreshMiss && hasFreeJamletReq && hasFreeLamletReq
  val claimRespCanPark = claimRespCanParkPending || claimRespCanParkFresh
  val claimRespHardDrop =
    !claimRespPresent && !claimRespCanPark

  val claimRespAllocReady =
    !claimRespFreshMiss || !claimRespCanParkFresh || tagTable.io.allocReq.ready

  tlbResp(claimResp.bits.meta.jInK).valid := claimResp.valid && claimRespAllocReady
  tlbResp(claimResp.bits.meta.jInK).bits.status := Mux(
    claimRespPresent,
    JamletTlbStatus.Hit,
    Mux(claimRespHardDrop, JamletTlbStatus.HardDrop, JamletTlbStatus.SoftDrop),
  )
  tlbResp(claimResp.bits.meta.jInK).bits.teIndex := claimResp.bits.meta.req.teIndex
  tlbResp(claimResp.bits.meta.jInK).bits.byteIndex := claimResp.bits.meta.req.byteIndex
  tlbResp(claimResp.bits.meta.jInK).bits.translation.stripeAddr :=
    claimResp.bits.payload.physicalStripeAddr
  tlbResp(claimResp.bits.meta.jInK).bits.translation.ordering :=
    claimResp.bits.payload.ordering

  tagTable.io.allocReq.valid :=
    claimResp.valid && claimRespFreshMiss && claimRespCanParkFresh && tlbResp(claimResp.bits.meta.jInK).ready
  tagTable.io.allocReq.bits.tag := claimResp.bits.meta.req.virtualStripeAddr
  tagTable.io.allocReq.bits.willWrite := false.B
  tagTable.io.allocReq.bits.meta.jInK := claimResp.bits.meta.jInK
  tagTable.io.allocReq.bits.meta.req := claimResp.bits.meta.req
  tagTable.io.allocReq.bits.meta.jamletReqIndex := freeJamletReqIndex
  tagTable.io.allocReq.bits.fillMeta := DontCare

  claimResp.ready := tlbResp(claimResp.bits.meta.jInK).ready && claimRespAllocReady

  val jamletReqAfterClaim = Wire(Vec(params.tlbReqTableDepth, new KamletTlbJamletReqEntry(params)))
  val lamletReqAfterClaim = Wire(Vec(params.tlbReqTableDepth, new KamletTlbLamletReqEntry(params)))
  jamletReqAfterClaim := jamletReq
  lamletReqAfterClaim := lamletReq
  when (claimResp.fire && claimRespCanPark) {
    jamletReqAfterClaim(freeJamletReqIndex).valid := true.B
    jamletReqAfterClaim(freeJamletReqIndex).jInK := claimResp.bits.meta.jInK
    jamletReqAfterClaim(freeJamletReqIndex).teIndex := claimResp.bits.meta.req.teIndex
    jamletReqAfterClaim(freeJamletReqIndex).byteIndex := claimResp.bits.meta.req.byteIndex
    when (claimRespCanParkPending) {
      lamletReqAfterClaim(claimRespLamletIndex).waiters :=
        lamletReq(claimRespLamletIndex).waiters |
          UIntToOH(freeJamletReqIndex, params.tlbReqTableDepth)
    }
  }

  val lamletReqAfterAllocResp = Wire(Vec(params.tlbReqTableDepth, new KamletTlbLamletReqEntry(params)))
  lamletReqAfterAllocResp := lamletReqAfterClaim
  val allocRespLamletMatches = VecInit((0 until params.tlbReqTableDepth).map { i =>
    lamletReqAfterClaim(i).valid && lamletReqAfterClaim(i).cacheIndex === tagTable.io.allocResp.bits.slot
  })
  val allocRespLamletMatch = allocRespLamletMatches.asUInt.orR
  val allocRespLamletMatchCount = PopCount(allocRespLamletMatches)
  val allocRespLamletIndex = PriorityEncoder(allocRespLamletMatches)
  val allocRespTargetIndex = Mux(tagTable.io.allocResp.bits.didAlloc, freeLamletReq.bits, allocRespLamletIndex)
  tagTable.io.allocResp.ready := Mux(tagTable.io.allocResp.bits.didAlloc, freeLamletReq.valid, true.B)
  freeLamletReq.ready := tagTable.io.allocResp.fire && tagTable.io.allocResp.bits.didAlloc
  errors.allocRespNoLamletMatch :=
    tagTable.io.allocResp.fire && !tagTable.io.allocResp.bits.didAlloc && !allocRespLamletMatch
  errors.allocRespDuplicateLamletMatch :=
    tagTable.io.allocResp.fire && allocRespLamletMatchCount > 1.U
  when (tagTable.io.allocResp.fire) {
    lamletReqAfterAllocResp(allocRespTargetIndex).valid := true.B
    lamletReqAfterAllocResp(allocRespTargetIndex).virtualStripeAddr :=
      tagTable.io.allocResp.bits.meta.req.virtualStripeAddr
    lamletReqAfterAllocResp(allocRespTargetIndex).cacheIndex :=
      tagTable.io.allocResp.bits.slot
    lamletReqAfterAllocResp(allocRespTargetIndex).waiters :=
      lamletReqAfterClaim(allocRespTargetIndex).waiters |
        UIntToOH(tagTable.io.allocResp.bits.meta.jamletReqIndex, params.tlbReqTableDepth)
    when (tagStateIsPresent(tagTable.io.allocResp.bits.state)) {
      lamletReqAfterAllocResp(allocRespTargetIndex).physicalStripeAddr :=
        tagTable.io.allocResp.bits.payload.physicalStripeAddr
      lamletReqAfterAllocResp(allocRespTargetIndex).ordering :=
        tagTable.io.allocResp.bits.payload.ordering
      lamletReqAfterAllocResp(allocRespTargetIndex).state := KamletTlbLamletReqState.ReadyWake
    } .elsewhen (tagTable.io.allocResp.bits.didAlloc) {
      lamletReqAfterAllocResp(allocRespTargetIndex).state := KamletTlbLamletReqState.WaitingFillReq
    }
  }

  val lamletReqAfterTx = Wire(Vec(params.tlbReqTableDepth, new KamletTlbLamletReqEntry(params)))
  lamletReqAfterTx := lamletReqAfterAllocResp

  // reqTx1: fill requests from TagTable are the durable source for network TLB requests.
  val reqTx1 = DoubleBuffer(tagTable.io.fillReq, tp.reqTx01FB, tp.reqTx01BB)
  val reqTx1IsBodyNext = Wire(Bool())
  val reqTx1IsBody = RegEnable(reqTx1IsBodyNext, false.B, packetOut.fire)
  reqTx1IsBodyNext := !reqTx1IsBody

  val reqTx1Header = Wire(new KamletTlbReqHeader(params))
  reqTx1Header := 0.U.asTypeOf(reqTx1Header)
  reqTx1Header.targetX := io.lamletKnetX
  reqTx1Header.targetY := io.lamletKnetY
  reqTx1Header.sourceX := io.knetX
  reqTx1Header.sourceY := io.knetY
  reqTx1Header.length := 1.U
  reqTx1Header.messageType := MessageType.TlbReq
  reqTx1Header.sendType := SendType.Single
  val reqTx1LamletMatches = VecInit((0 until params.tlbReqTableDepth).map { i =>
    lamletReqAfterAllocResp(i).valid && lamletReqAfterAllocResp(i).cacheIndex === reqTx1.bits.slot
  })
  val reqTx1LamletMatch = reqTx1LamletMatches.asUInt.orR
  val reqTx1LamletMatchCount = PopCount(reqTx1LamletMatches)
  val reqTx1LamletIndex = PriorityEncoder(reqTx1LamletMatches)
  reqTx1Header.tlbReqSlot := reqTx1LamletIndex

  packetOut.valid := reqTx1.valid
  packetOut.bits.isHeader := !reqTx1IsBody
  packetOut.bits.data := Mux(
    reqTx1IsBody,
    reqTx1.bits.tag,
    reqTx1Header.asUInt)
  reqTx1.ready := packetOut.ready && reqTx1IsBody
  errors.reqTxNoLamletMatch := reqTx1.fire && !reqTx1LamletMatch
  errors.reqTxDuplicateLamletMatch := reqTx1.fire && reqTx1LamletMatchCount > 1.U

  when (reqTx1.fire) {
    lamletReqAfterTx(reqTx1LamletIndex).state := KamletTlbLamletReqState.WaitingResp
  }

  // resp0: consume a TLB response packet header and body.
  val packetInHeader = packetIn.bits.data.asTypeOf(new KamletTlbRespHeader(params))
  val resp0HeaderValid = packetIn.valid &&
    packetIn.bits.isHeader &&
    packetInHeader.messageType === MessageType.TlbResp
  val resp0BodyValid = packetIn.valid && !packetIn.bits.isHeader
  val resp0Header = RegEnable(packetInHeader, resp0HeaderValid && packetIn.ready)
  val resp0HaveHeader = RegInit(false.B)
  val resp0Out = Wire(Decoupled(new KamletTlbResp01(params)))

  packetIn.ready := Mux(resp0HaveHeader, resp0Out.ready, resp0HeaderValid)
  errors.packetInBadMessageType := packetIn.valid && packetIn.bits.isHeader &&
    packetInHeader.messageType =/= MessageType.TlbResp
  errors.packetInUnexpectedBody := packetIn.valid && !packetIn.bits.isHeader && !resp0HaveHeader
  resp0Out.valid := resp0HaveHeader && resp0BodyValid
  resp0Out.bits.tlbReqSlot := resp0Header.tlbReqSlot
  resp0Out.bits.physicalStripeAddr := packetIn.bits.data
  resp0Out.bits.ordering.wf := resp0Header.wf
  resp0Out.bits.ordering.laneOrder := resp0Header.laneOrder
  when (packetIn.fire && resp0HeaderValid) {
    resp0HaveHeader := true.B
  }
  when (resp0Out.fire) {
    resp0HaveHeader := false.B
  }

  val resp1 = DoubleBuffer(resp0Out, tp.resp01FB, tp.resp01BB)
  resp1.ready := true.B

  val lamletReqAfterResp = Wire(Vec(params.tlbReqTableDepth, new KamletTlbLamletReqEntry(params)))
  lamletReqAfterResp := lamletReqAfterTx

  // resp1: install the translation and make the Lamlet request wakeable.
  errors.respInvalidSlot := resp1.fire && !lamletReqAfterTx(resp1.bits.tlbReqSlot).valid
  errors.respUnexpectedState := resp1.fire &&
    lamletReqAfterTx(resp1.bits.tlbReqSlot).state =/= KamletTlbLamletReqState.WaitingResp
  tagTable.io.fillComplete.valid := resp1.fire
  tagTable.io.fillComplete.bits.slot := lamletReqAfterTx(resp1.bits.tlbReqSlot).cacheIndex
  tagTable.io.fillComplete.bits.payload.physicalStripeAddr := resp1.bits.physicalStripeAddr
  tagTable.io.fillComplete.bits.payload.ordering := resp1.bits.ordering
  when (resp1.fire) {
    lamletReqAfterResp(resp1.bits.tlbReqSlot).physicalStripeAddr := resp1.bits.physicalStripeAddr
    lamletReqAfterResp(resp1.bits.tlbReqSlot).ordering := resp1.bits.ordering
    lamletReqAfterResp(resp1.bits.tlbReqSlot).state := KamletTlbLamletReqState.ReadyWake
  }

  val jamletReqAfterWake = Wire(Vec(params.tlbReqTableDepth, new KamletTlbJamletReqEntry(params)))
  val lamletReqAfterWake = Wire(Vec(params.tlbReqTableDepth, new KamletTlbLamletReqEntry(params)))
  jamletReqAfterWake := jamletReqAfterClaim
  lamletReqAfterWake := lamletReqAfterResp

  // wake0: choose one completed Lamlet request and notify one parked waiter.
  val wake0Candidates = VecInit((0 until params.tlbReqTableDepth).map { i =>
    lamletReqAfterResp(i).valid &&
      lamletReqAfterResp(i).state === KamletTlbLamletReqState.ReadyWake &&
      lamletReqAfterResp(i).waiters =/= 0.U
  })
  val wake0Valid = wake0Candidates.asUInt.orR
  val wake0LamletIndex = PriorityEncoder(wake0Candidates)
  val wake0Waiters = lamletReqAfterResp(wake0LamletIndex).waiters
  val wake0JamletReqIndex = PriorityEncoder(wake0Waiters)
  val wake0JamletReq = jamletReqAfterClaim(wake0JamletReqIndex)
  tlbAvailable(wake0JamletReq.jInK).valid := wake0Valid
  tlbAvailable(wake0JamletReq.jInK).bits.teIndex := wake0JamletReq.teIndex
  tlbAvailable(wake0JamletReq.jInK).bits.byteIndex := wake0JamletReq.byteIndex
  when (wake0Valid) {
    val remainingWaiters =
      lamletReqAfterResp(wake0LamletIndex).waiters &
        ~UIntToOH(wake0JamletReqIndex, params.tlbReqTableDepth)
    jamletReqAfterWake(wake0JamletReqIndex).valid := false.B
    lamletReqAfterWake(wake0LamletIndex).waiters := remainingWaiters
    when (remainingWaiters === 0.U) {
      tagTable.io.release.valid := true.B
      tagTable.io.release.bits := lamletReqAfterResp(wake0LamletIndex).cacheIndex
      lamletReqAfterWake(wake0LamletIndex).valid := false.B
    }
  }

  jamletReqNext := jamletReqAfterWake
  lamletReqNext := lamletReqAfterWake

  io.errors := RegNext(errors)
}

object KamletTlbGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    new KamletTlb(params)
  }
}

object KamletTlbMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  KamletTlbGenerator.generate(outputDir, Seq(configFile))
}
