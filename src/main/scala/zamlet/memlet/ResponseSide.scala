package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.{MessageType, NetworkWord, AddressHeader, PacketConstants, IdentHeader, SendType}


class ResponseSideErrors(params: ZamletParams) extends Bundle {
  val responseAllocOverwrite = Output(Bool())
  val sentInInvalid = Output(Bool())
  val sentInDuplicate = Output(Bool())
}

class ResponseSideIO(params: ZamletParams) extends Bundle {

  // The inner slice handles address packets (ReadLine,
  // WriteLineAddr, WriteLineReadLineAddr) and owns the authoritative
  // gathering slot metadata. Other instances only handle CacheLineData.
  val isInnerSlice = Input(Bool())
  val isOuterSlice = Input(Bool())
  val sliceIdx = Input(UInt(log2Ceil(params.nMemletRouters).W))

  // Kamlet base coordinates, used to compute the sender's jamlet
  // index from the packet's source coordinates.
  val kBaseX = Input(UInt(params.xPosWidth.W))
  val kBaseY = Input(UInt(params.yPosWidth.W))

  // Packet stream to the router's local A-channel output.
  // Carries request packets (header + body words) from kamlet jamlets.
  val aHi = Decoupled(new NetworkWord(params))

  // Drop response enqueue (from GatherSide).
  val dropEnq = Flipped(Decoupled(new NetworkWord(params)))

  // WriteLineResp enqueue (from MemoryEngine, inner slice only).
  val writeLineRespEnq = Flipped(Decoupled(new NetworkWord(params)))

  // MemoryEngine writes response data to each slice's local storage.
  val responseDataWrite = Flipped(Valid(new ResponseDataWrite(params)))

  // Response buffer metadata broadcast (from MemoryEngine, all slices).
  // Allocate or Sendable events.
  val responseMetaEvent = Flipped(Valid(new ResponseMetaEvent(params)))

  // Router coordinates for source fields in outgoing packet headers.
  val routerX = Input(UInt(params.xPosWidth.W))
  val routerY = Input(UInt(params.yPosWidth.W))

  // Response buffer free (inner slice → MemoryEngine).
  // Pulsed when all slices have finished sending for a slot.
  val responseFree = Valid(UInt(log2Ceil(params.nResponseBufferSlots).W))

  // Sent propagation chain (inward toward slice 0).
  // Each slice sends its slot index when it has finished sending
  // all response packets for that response buffer slot.
  val sentIn = Flipped(Valid(UInt(log2Ceil(params.nResponseBufferSlots).W)))
  val sentOut = Valid(UInt(log2Ceil(params.nResponseBufferSlots).W))

  // Errors
  val errors = new ResponseSideErrors(params)
}

class ResponseSlotLocal(params: ZamletParams) extends Bundle {
  val ident = UInt(params.identWidth.W)
  val sramAddr = UInt(params.sramAddrWidth.W)
  val responseType = MemletResponseType()
  val sendable = Bool()
  val sent = Bool()
  val outerSent = Bool()
  val data = Vec(params.memletLocalWords, UInt(params.wordWidth.W))
}

class ResponseSide(params: ZamletParams) extends Module {
  val io = IO(new ResponseSideIO(params))

  val nRSlots = params.nResponseBufferSlots
  val localJamlets = params.memletLocalJamlets
  val localWords = params.memletLocalWords

  // ============================================================
  // Local response buffer storage
  // ============================================================

  val responseSlots = RegInit(VecInit(Seq.fill(nRSlots) {
    val init = Wire(Valid(new ResponseSlotLocal(params)))
    init.valid := false.B
    init.bits.ident := DontCare
    init.bits.sramAddr := DontCare
    init.bits.responseType := DontCare
    init.bits.sendable := false.B
    init.bits.sent := false.B
    init.bits.outerSent := false.B
    init.bits.data := DontCare
    init
  }))

  // ============================================================
  // 1. Response metadata event latch (from MemoryEngine, broadcast)
  // ============================================================

  val errResponseAllocOverwrite = Wire(Bool())
  errResponseAllocOverwrite := false.B
  io.errors.responseAllocOverwrite := errResponseAllocOverwrite

  when(io.responseMetaEvent.valid) {
    val idx = io.responseMetaEvent.bits.slotIdx
    when(io.responseMetaEvent.bits.isSendable) {
      responseSlots(idx).bits.sendable := true.B
    }.otherwise {
      errResponseAllocOverwrite := responseSlots(idx).valid
      responseSlots(idx).valid := true.B
      responseSlots(idx).bits.ident := io.responseMetaEvent.bits.ident
      responseSlots(idx).bits.sramAddr := io.responseMetaEvent.bits.sramAddr
      responseSlots(idx).bits.responseType := io.responseMetaEvent.bits.responseType
      responseSlots(idx).bits.sendable := false.B
      responseSlots(idx).bits.sent := false.B
      responseSlots(idx).bits.outerSent := false.B
    }
  }

  // ============================================================
  // 2. Response data write (from MemoryEngine, one word per cycle)
  // ============================================================

  when(io.responseDataWrite.valid) {
    val idx = io.responseDataWrite.bits.slotIdx
    val wordIdx = io.responseDataWrite.bits.localDataIdx
    responseSlots(idx).bits.data(wordIdx) := io.responseDataWrite.bits.data
  }

  // ============================================================
  // 3. Internal queues
  // ============================================================

  val dropQueue = Module(new Queue(new NetworkWord(params), entries = 4))
  dropQueue.io.enq <> io.dropEnq

  val writeLineRespQueue = Module(new Queue(new NetworkWord(params), entries = 4))
  writeLineRespQueue.io.enq <> io.writeLineRespEnq

  val responseQueue = Module(new Queue(new NetworkWord(params), entries = 4))

  // ============================================================
  // 4. Response TX FSM — reads response buffer, pushes into
  //    responseQueue
  // ============================================================

  object TxState extends ChiselEnum {
    val Idle, EnqueueHeader, SendResponseData = Value
  }

  val txState = RegInit(TxState.Idle)
  val txSlotIdx = Reg(UInt(log2Ceil(nRSlots).W))
  val txJamletIdx = Reg(UInt(log2Ceil(localJamlets).W))
  val txWordIdx = Reg(UInt(log2Ceil(params.cacheSlotWordsPerJamlet).W))
  val txHeader = Reg(UInt(params.wordWidth.W))

  // Find a sendable response buffer slot that we haven't sent yet.
  // Excludes txSlotIdx when the FSM is active, to avoid re-picking
  // a slot we're about to mark sent (register not yet committed).
  val sendableVec = Wire(Vec(nRSlots, Bool()))
  for (s <- 0 until nRSlots) {
    sendableVec(s) := responseSlots(s).valid &&
      responseSlots(s).bits.sendable && !responseSlots(s).bits.sent &&
      !(s.U === txSlotIdx && txState =/= TxState.Idle)
  }
  val sendableSlot = Wire(Valid(UInt(log2Ceil(nRSlots).W)))
  sendableSlot.valid := sendableVec.asUInt.orR
  sendableSlot.bits := PriorityEncoder(sendableVec)

  // Header builder. Reads slot metadata and jamlet index, produces
  // a packed AddressHeader. Used in Idle and on last data word.
  def buildHeader(slotIdx: UInt, jamletIdx: UInt): UInt = {
    val globalJamletIdx =
      io.sliceIdx * localJamlets.U +& jamletIdx
    val slot = responseSlots(slotIdx).bits
    val header = Wire(new AddressHeader(params))
    header.targetX := io.kBaseX +
      globalJamletIdx(log2Ceil(params.jCols) - 1, 0)
    header.targetY := io.kBaseY +
      (globalJamletIdx >> log2Ceil(params.jCols))(
        log2Ceil(params.jRows) - 1, 0)
    header.sourceX := io.routerX
    header.sourceY := io.routerY
    header.length := params.cacheSlotWordsPerJamlet.U
    header.ident := slot.ident
    header.address := slot.sramAddr
    header.sendType := SendType.Single
    header.messageType := Mux(
      slot.responseType === MemletResponseType.ReadLine,
      MessageType.ReadLineResp,
      MessageType.WriteLineReadLineResp
    )
    header._padding := 0.U
    header.asUInt
  }

  // Defaults
  responseQueue.io.enq.valid := false.B
  responseQueue.io.enq.bits := DontCare

  switch(txState) {
    is(TxState.Idle) {
      when(sendableSlot.valid) {
        txSlotIdx := sendableSlot.bits
        txJamletIdx := 0.U
        txHeader := buildHeader(sendableSlot.bits, 0.U)
        txState := TxState.EnqueueHeader
      }
    }
    is(TxState.EnqueueHeader) {
      responseQueue.io.enq.valid := true.B
      responseQueue.io.enq.bits.data := txHeader
      responseQueue.io.enq.bits.isHeader := true.B
      when(responseQueue.io.enq.ready) {
        txWordIdx := 0.U
        txState := TxState.SendResponseData
      }
    }
    is(TxState.SendResponseData) {
      val dataIdx = (txJamletIdx * params.cacheSlotWordsPerJamlet.U + txWordIdx)(
        log2Ceil(localWords) - 1, 0)
      responseQueue.io.enq.valid := true.B
      responseQueue.io.enq.bits.data :=
        responseSlots(txSlotIdx).bits.data(dataIdx)
      responseQueue.io.enq.bits.isHeader := false.B
      when(responseQueue.io.enq.ready) {
        when(txWordIdx === (params.cacheSlotWordsPerJamlet - 1).U) {
          when(txJamletIdx === (localJamlets - 1).U) {
            responseSlots(txSlotIdx).bits.sent := true.B
            when (sendableSlot.valid) {
              txSlotIdx := sendableSlot.bits
              txJamletIdx := 0.U
              txHeader := buildHeader(sendableSlot.bits, 0.U)
              txState := TxState.EnqueueHeader
            } .otherwise {
              txState := TxState.Idle
            }
          }.otherwise {
            val nextJamlet = txJamletIdx + 1.U
            txJamletIdx := nextJamlet
            txHeader := buildHeader(txSlotIdx, nextJamlet)
            txState := TxState.EnqueueHeader
          }
        }.otherwise {
          txWordIdx := txWordIdx + 1.U
        }
      }
    }
  }

  // ============================================================
  // 5. Priority merge → aHi
  //    (1) drops, (2) writeLineResp, (3) response buffer
  //    Once a multi-word packet starts, stay on that source.
  // ============================================================

  val mergeWordsRemaining = RegInit(0.U(PacketConstants.lengthWidth))

  dropQueue.io.deq.ready := false.B
  writeLineRespQueue.io.deq.ready := false.B
  responseQueue.io.deq.ready := false.B
  io.aHi.valid := false.B
  io.aHi.bits := DontCare

  when(mergeWordsRemaining =/= 0.U) {
    // Mid-packet: continue from responseQueue
    io.aHi.valid := responseQueue.io.deq.valid
    io.aHi.bits := responseQueue.io.deq.bits
    responseQueue.io.deq.ready := io.aHi.ready
    when(io.aHi.fire) {
      mergeWordsRemaining := mergeWordsRemaining - 1.U
    }
  }.otherwise {
    when(dropQueue.io.deq.valid) {
      io.aHi.valid := true.B
      io.aHi.bits := dropQueue.io.deq.bits
      dropQueue.io.deq.ready := io.aHi.ready
    }.elsewhen(io.isInnerSlice && writeLineRespQueue.io.deq.valid) {
      io.aHi.valid := true.B
      io.aHi.bits := writeLineRespQueue.io.deq.bits
      writeLineRespQueue.io.deq.ready := io.aHi.ready
    }.elsewhen(responseQueue.io.deq.valid) {
      io.aHi.valid := true.B
      io.aHi.bits := responseQueue.io.deq.bits
      responseQueue.io.deq.ready := io.aHi.ready
      when(io.aHi.fire) {
        val hdr = responseQueue.io.deq.bits.data.asTypeOf(
          new AddressHeader(params))
        mergeWordsRemaining := hdr.length
      }
    }
  }

  // ============================================================
  // 6. Sent detection and propagation (inward toward slice 0)
  // ============================================================

  // Latch sent events from outer slices
  io.errors.sentInInvalid := false.B
  io.errors.sentInDuplicate := false.B
  when(io.sentIn.valid) {
    io.errors.sentInInvalid := !responseSlots(io.sentIn.bits).valid
    io.errors.sentInDuplicate := responseSlots(io.sentIn.bits).bits.outerSent
    responseSlots(io.sentIn.bits).bits.outerSent := true.B
  }

  // Slots ready to signal sent: valid, locally sent, outer slices
  // sent (or we are the outer slice).
  val slotSentComplete = Wire(Vec(nRSlots, Bool()))
  for (s <- 0 until nRSlots) {
    slotSentComplete(s) := responseSlots(s).valid &&
      responseSlots(s).bits.sent &&
      (responseSlots(s).bits.outerSent || io.isOuterSlice)
  }
  val sentCompleteSlot = Wire(Valid(UInt(log2Ceil(nRSlots).W)))
  sentCompleteSlot.valid := slotSentComplete.asUInt.orR
  sentCompleteSlot.bits := PriorityEncoder(slotSentComplete)

  // Default outputs
  io.sentOut.valid := false.B
  io.sentOut.bits := DontCare
  io.responseFree.valid := false.B
  io.responseFree.bits := DontCare

  when(sentCompleteSlot.valid) {
    when(io.isInnerSlice) {
      io.responseFree.valid := true.B
      io.responseFree.bits := sentCompleteSlot.bits
      responseSlots(sentCompleteSlot.bits).valid := false.B
    }.otherwise {
      io.sentOut.valid := true.B
      io.sentOut.bits := sentCompleteSlot.bits
      responseSlots(sentCompleteSlot.bits).valid := false.B
    }
  }
}

