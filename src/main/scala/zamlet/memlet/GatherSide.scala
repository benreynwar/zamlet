package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.{MessageType, NetworkWord, AddressHeader, PacketConstants, IdentHeader, SendType}

class GatherSideErrors(params: ZamletParams) extends Bundle {
  val identAllocOverwrite = Output(Bool())
  val missingHeader = Output(Bool())
  val unexpectedHeader = Output(Bool())
  val duplicateArrived = Output(Bool())
  val badMessageType = Output(Bool())
  val badPacketLength = Output(Bool())
  val unexpectedData = Output(Bool())
}

class GatherSideIO(params: ZamletParams) extends Bundle {

  // The inner slice handles address packets (ReadLine,
  // WriteLineAddr, WriteLineReadLineAddr) and owns the authoritative
  // gathering slot metadata. Other instances only handle CacheLineData.
  val isInnerSlice = Input(Bool())
  val isOuterSlice = Input(Bool())

  // Kamlet base coordinates, used to compute the sender's jamlet
  // index from the packet's source coordinates.
  val kBaseX = Input(UInt(params.xPosWidth.W))
  val kBaseY = Input(UInt(params.yPosWidth.W))

  // Packet stream from the router's local B-channel output.
  // Carries request packets (header + body words) from kamlet jamlets.
  val bHo = Flipped(Decoupled(new NetworkWord(params)))

  // Enqueue port for drop responses. The drop queue itself lives in
  // MemletSlice; BufferToKamlet dequeues from the other end.
  val dropEnq = Decoupled(new NetworkWord(params))

  // Ident allocation propagation chain (outward from slice 0).
  // When slice 0 allocates a gathering slot, it propagates {slotIdx, ident}
  // so other slices can match CacheLineData packets by ident.
  val identAllocIn = Flipped(Valid(new IdentAllocEvent(params)))
  val identAllocOut = Valid(new IdentAllocEvent(params))

  // Arrived propagation chain (inward toward slice 0).
  // Each slice sends its slot index when all its local jamlets have
  // sent CacheLineData for that slot. Slice 0 counts these to
  // determine when the full cache line has been gathered.
  val arrivedIn = Flipped(Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W)))
  val arrivedOut = Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W))

  // MemoryEngine reads gathered data from this slice's local storage.
  val gatheringDataReq = Flipped(Decoupled(new GatheringDataReadSliceReq(params)))
  val gatheringDataResp = Decoupled(UInt(params.wordWidth.W))

  // Slice 0 enqueues completed gathering slots with metadata
  // for MemoryEngine to issue AXI4 writes.
  val completeEnq = Decoupled(new GatheringSlotMeta(params))

  // MemoryEngine tells all slices to free a gathering slot after
  // copying its data into the AXI4 write pipeline.
  val gatheringFree = Flipped(Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W)))

  // Errors
  val errors = new GatherSideErrors(params)
}

class GatheringSlotLocal(params: ZamletParams) extends Bundle {
  val ident = UInt(params.identWidth.W)
  val data = Vec(params.memletLocalWords, UInt(params.wordWidth.W))
  val arrived = Vec(params.memletLocalJamlets, Bool())
  val arrivedNotified = Bool()
  val outerArrived = Bool()
  // Authoritative metadata (only meaningful at slice 0)
  val sramAddr = UInt(params.sramAddrWidth.W)
  val sourceX = UInt(params.xPosWidth.W)
  val sourceY = UInt(params.yPosWidth.W)
  val writeAddr = UInt(params.wordWidth.W)
  val readAddr = UInt(params.wordWidth.W)
  val reads = Bool()
}

class GatherSide(params: ZamletParams) extends Module {
  val io = IO(new GatherSideIO(params))

  val nGSlots = params.nMemletGatheringSlots
  val localJamlets = params.memletLocalJamlets

  // ============================================================
  // Local storage
  // ============================================================

  val gatherSlots = RegInit(VecInit(Seq.fill(nGSlots) {
    val init = Wire(Valid(new GatheringSlotLocal(params)))
    init.valid := false.B
    init.bits.ident := DontCare
    init.bits.data := DontCare
    init.bits.arrived := VecInit(Seq.fill(localJamlets)(false.B))
    init.bits.arrivedNotified := false.B
    init.bits.outerArrived := false.B
    init.bits.sramAddr := DontCare
    init.bits.sourceX := DontCare
    init.bits.sourceY := DontCare
    init.bits.writeAddr := DontCare
    init.bits.readAddr := DontCare
    init.bits.reads := DontCare
    init
  }))



  // ============================================================
  // MemoryEngine read ports
  // ============================================================

  io.gatheringDataReq.ready := io.gatheringDataResp.ready
  io.gatheringDataResp.valid := io.gatheringDataReq.valid
  io.gatheringDataResp.bits :=
    gatherSlots(io.gatheringDataReq.bits.slotIdx).bits
      .data(io.gatheringDataReq.bits.wordIdx)

  // ============================================================
  // Gathering slot free (from MemoryEngine, broadcast to all slices)
  // ============================================================

  when(io.gatheringFree.valid) {
    gatherSlots(io.gatheringFree.bits).valid := false.B
  }

  // ============================================================
  // Ident allocation chain (outward from slice 0)
  //
  // Default: forward identAllocIn one cycle later.
  // KamletToBuffer overrides identAllocOutValid/Bits when
  // allocating at slice 0.
  // ============================================================

  val errIdentAllocOverwrite = Wire(Bool())
  errIdentAllocOverwrite := false.B

  // Latch incoming ident allocation into local replica
  when(io.identAllocIn.valid) {
    val idx = io.identAllocIn.bits.slotIdx
    errIdentAllocOverwrite := gatherSlots(idx).valid
    gatherSlots(idx).valid := true.B
    gatherSlots(idx).bits.ident := io.identAllocIn.bits.ident
    for (j <- 0 until localJamlets) {
      gatherSlots(idx).bits.arrived(j) := false.B
    }
    gatherSlots(idx).bits.arrivedNotified := false.B
    gatherSlots(idx).bits.outerArrived := false.B
  }
  io.errors.identAllocOverwrite := errIdentAllocOverwrite

  val identAllocOutNext = Wire(Valid(new IdentAllocEvent(params)))
  identAllocOutNext := io.identAllocIn
  io.identAllocOut := RegNext(identAllocOutNext, init = {
    val init = Wire(Valid(new IdentAllocEvent(params)))
    init.valid := false.B
    init.bits := DontCare
    init
  })

  // ============================================================
  // Arrived detection
  // ============================================================

  // Slots ready to signal arrived: valid, all local jamlets arrived,
  // outer slices arrived (or we are the outer slice), not yet notified.
  val slotComplete = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    slotComplete(s) := gatherSlots(s).valid &&
      !gatherSlots(s).bits.arrivedNotified &&
      gatherSlots(s).bits.arrived.asUInt.andR &&
      (gatherSlots(s).bits.outerArrived || io.isOuterSlice)
  }
  val anyComplete = slotComplete.asUInt.orR
  val completeSlot = PriorityEncoder(slotComplete)

  // Defaults
  io.arrivedOut.valid := false.B
  io.arrivedOut.bits := DontCare
  io.completeEnq.valid := false.B
  io.completeEnq.bits := DontCare

  // Signal arrived upstream (or enqueue complete at inner slice)
  when(anyComplete) {
    when(io.isInnerSlice) {
      val slot = gatherSlots(completeSlot).bits
      io.completeEnq.valid := true.B
      io.completeEnq.bits.slotIdx := completeSlot
      io.completeEnq.bits.ident := slot.ident
      io.completeEnq.bits.sramAddr := slot.sramAddr
      io.completeEnq.bits.sourceX := slot.sourceX
      io.completeEnq.bits.sourceY := slot.sourceY
      io.completeEnq.bits.writeAddr := slot.writeAddr
      io.completeEnq.bits.readAddr := slot.readAddr
      io.completeEnq.bits.writes := true.B
      io.completeEnq.bits.reads := slot.reads
      when(io.completeEnq.ready) {
        gatherSlots(completeSlot).bits.arrivedNotified := true.B
      }
    }.otherwise {
      io.arrivedOut.valid := true.B
      io.arrivedOut.bits := completeSlot
      gatherSlots(completeSlot).bits.arrivedNotified := true.B
    }
  }

  // Latch arrived events from outer slices
  io.errors.duplicateArrived := false.B
  when(io.arrivedIn.valid) {
    val s = io.arrivedIn.bits
    io.errors.duplicateArrived := gatherSlots(s).bits.outerArrived
    gatherSlots(s).bits.outerArrived := true.B
  }

  // Deal with receiving the packets.
  val bHo = io.bHo

  val bHoHeader = bHo.bits.data.asTypeOf(new AddressHeader(params))

  // Find if there are any free slots.

  val freeSlotVec = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    freeSlotVec(s) := !gatherSlots(s).valid
  }

  val freeSlot = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
  freeSlot.valid := freeSlotVec.asUInt.orR
  freeSlot.bits := PriorityEncoder(freeSlotVec)

  val packetSlotNext = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
  val packetSlot = RegNext(packetSlotNext, init = {
    val init = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
    init.valid := false.B
    init.bits := DontCare
    init
  })
  packetSlotNext := packetSlot

  // Match the incoming packet's ident against the slot idents

  val identMatch = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    identMatch(s) := gatherSlots(s).valid &&
      gatherSlots(s).bits.ident === bHoHeader.ident
  }
  val packetIdentFound = RegNext(identMatch.asUInt.orR)
  val packetIdentSlotIdx = RegNext(PriorityEncoder(identMatch))
  dontTouch(identMatch)
  dontTouch(packetIdentFound)
  dontTouch(bHoHeader)
  val bHoJamletIdx = {
    val jX = bHoHeader.sourceX - io.kBaseX
    val jY = bHoHeader.sourceY - io.kBaseY
    val jIdx = jY * params.jCols.U + jX
    (jIdx & (localJamlets - 1).U)(log2Ceil(localJamlets) - 1, 0)
  }
  val packetJamletIdx = RegNext(bHoJamletIdx)

  // We need to grab packets and process them based on what they are.
  //
  // slice 0 can get packets of type:
  //   write_line_address
  //   read_write_line_address
  //   read_line_address
  //   write_data
  //   
  // other slices can get packets of type:
  //   write_data

  // We need some state to track the processing of the packet.
  // packetWordsRemaining
  // packetType
  
  val packetWordsRemainingNext = Wire(UInt(PacketConstants.lengthWidth))
  val packetWordsRemaining = RegNext(packetWordsRemainingNext, init=0.U)
  packetWordsRemainingNext := packetWordsRemaining

  val packetHeaderNext = Wire(new AddressHeader(params))
  val packetHeader = RegNext(packetHeaderNext)
  packetHeaderNext := packetHeader

  val errMissingHeader = Wire(Bool())
  val errUnexpectedHeader = Wire(Bool())
  val errBadMessageType = Wire(Bool())
  val errBadPacketLength = Wire(Bool())
  val errUnexpectedData = Wire(Bool())
  errMissingHeader := false.B
  errUnexpectedHeader := false.B
  errBadMessageType := false.B
  errBadPacketLength := false.B
  errUnexpectedData := false.B

  val dropHeader = Wire(new IdentHeader(params))
  dropHeader.targetX := packetHeader.sourceX
  dropHeader.targetY := packetHeader.sourceY
  dropHeader.sourceX := packetHeader.targetX
  dropHeader.sourceY := packetHeader.targetY
  dropHeader.length := 0.U
  dropHeader.ident := packetHeader.ident
  dropHeader.sendType := SendType.Single
  dropHeader.messageType := DontCare
  dropHeader._padding := 0.U

  io.dropEnq.valid := false.B
  io.dropEnq.bits.data := dropHeader.asUInt
  io.dropEnq.bits.isHeader := true.B
  bHo.ready := false.B

  when(bHo.valid) {
    when (packetWordsRemaining === 0.U) {
      bHo.ready := true.B
      packetSlotNext := freeSlot
      errMissingHeader := !bHo.bits.isHeader
      packetWordsRemainingNext := bHoHeader.length
      packetHeaderNext := bHoHeader
      errBadPacketLength := false.B
      errBadMessageType := true.B
      switch(bHoHeader.messageType) {
        is(MessageType.WriteLineAddr) {
          errBadPacketLength := (bHoHeader.length =/= 1.U)
          errBadMessageType := !io.isInnerSlice
        }
        is(MessageType.ReadLineAddr) {
          errBadPacketLength := (bHoHeader.length =/= 1.U)
          errBadMessageType := !io.isInnerSlice
        }
        is(MessageType.WriteLineReadLineAddr) {
          errBadPacketLength := (bHoHeader.length =/= 2.U)
          errBadMessageType := !io.isInnerSlice
        }
        is(MessageType.WriteLineData) {
          errBadPacketLength :=
            (bHoHeader.length =/= params.cacheSlotWordsPerJamlet.U)
          errBadMessageType := false.B
        }
      }
    } .otherwise {
      errUnexpectedHeader := bHo.bits.isHeader
      packetWordsRemainingNext := packetWordsRemaining - 1.U
      switch(packetHeader.messageType) {
        is(MessageType.WriteLineAddr) {
          // We got a new write request. We need to allocate a slot for it.
          when (packetSlot.valid) {
            bHo.ready := true.B
            gatherSlots(packetSlot.bits).valid := true.B
            gatherSlots(packetSlot.bits).bits.ident := packetHeader.ident
            for (j <- 0 until localJamlets) {
              gatherSlots(packetSlot.bits).bits.arrived(j) := false.B
            }
            gatherSlots(packetSlot.bits).bits.arrivedNotified := false.B
            gatherSlots(packetSlot.bits).bits.outerArrived := false.B
            gatherSlots(packetSlot.bits).bits.sramAddr := packetHeader.address
            gatherSlots(packetSlot.bits).bits.sourceX := packetHeader.sourceX
            gatherSlots(packetSlot.bits).bits.sourceY := packetHeader.sourceY
            gatherSlots(packetSlot.bits).bits.writeAddr := bHo.bits.data
            gatherSlots(packetSlot.bits).bits.readAddr := 0.U
            gatherSlots(packetSlot.bits).bits.reads := false.B
            identAllocOutNext.valid := true.B
            identAllocOutNext.bits.ident := packetHeader.ident
            identAllocOutNext.bits.slotIdx := packetSlot.bits
          } .otherwise {
            dropHeader.messageType := MessageType.WriteLineAddrDrop
            io.dropEnq.valid := true.B
            bHo.ready := io.dropEnq.ready
          }
        }
        is(MessageType.WriteLineReadLineAddr) {
          // We got a new write/read request. We need to allocate a slot for it
          // and submit a read request.
          // The first packet word is the write address.
          // The second is the read address.
          when (packetSlot.valid) {
            bHo.ready := true.B
            when (packetWordsRemaining === 2.U) {
              // Get the write address
              gatherSlots(packetSlot.bits).valid := false.B
              gatherSlots(packetSlot.bits).bits.ident := packetHeader.ident
              for (j <- 0 until localJamlets) {
                gatherSlots(packetSlot.bits).bits.arrived(j) := false.B
              }
              gatherSlots(packetSlot.bits).bits.arrivedNotified := false.B
              gatherSlots(packetSlot.bits).bits.outerArrived := false.B
              gatherSlots(packetSlot.bits).bits.sramAddr := packetHeader.address
              gatherSlots(packetSlot.bits).bits.sourceX := packetHeader.sourceX
              gatherSlots(packetSlot.bits).bits.sourceY := packetHeader.sourceY
              gatherSlots(packetSlot.bits).bits.writeAddr := bHo.bits.data
              gatherSlots(packetSlot.bits).bits.reads := true.B
            } .otherwise {
              // Get the read address
              gatherSlots(packetSlot.bits).valid := true.B
              gatherSlots(packetSlot.bits).bits.readAddr := bHo.bits.data
              identAllocOutNext.valid := true.B
              identAllocOutNext.bits.ident := packetHeader.ident
              identAllocOutNext.bits.slotIdx := packetSlot.bits
            }
          } .otherwise {
            dropHeader.messageType := MessageType.WriteLineReadLineAddrDrop
            io.dropEnq.valid := true.B
            bHo.ready := io.dropEnq.ready
          }
        }
        is(MessageType.ReadLineAddr) {
          val completeEnqBusy = anyComplete && io.isInnerSlice
          io.completeEnq.bits.slotIdx := DontCare
          io.completeEnq.bits.ident := packetHeader.ident
          io.completeEnq.bits.sramAddr := packetHeader.address
          io.completeEnq.bits.sourceX := packetHeader.sourceX
          io.completeEnq.bits.sourceY := packetHeader.sourceY
          io.completeEnq.bits.writeAddr := DontCare
          io.completeEnq.bits.readAddr := bHo.bits.data
          io.completeEnq.bits.writes := false.B
          io.completeEnq.bits.reads := true.B
          when (!completeEnqBusy) {
            io.completeEnq.valid := true.B
            bHo.ready := io.completeEnq.ready
          } .otherwise {
            dropHeader.messageType := MessageType.ReadLineAddrDrop
            io.dropEnq.valid := true.B
            bHo.ready := io.dropEnq.ready
          }
        }
        is(MessageType.WriteLineData) {
          when (packetIdentFound) {
            bHo.ready := true.B
            val wordsPerJamlet = params.cacheSlotWordsPerJamlet
            val wordOffset =
              (wordsPerJamlet.U - packetWordsRemaining)(
                log2Ceil(wordsPerJamlet) - 1, 0)
            val dataIdx = packetJamletIdx * wordsPerJamlet.U + wordOffset
            gatherSlots(packetIdentSlotIdx).bits.data(dataIdx) := bHo.bits.data
            when (packetWordsRemaining === 1.U) {
              gatherSlots(packetIdentSlotIdx).bits.arrived(packetJamletIdx) :=
                true.B
              errUnexpectedData :=
                gatherSlots(packetIdentSlotIdx).bits.arrived(packetJamletIdx)
            }
          } .otherwise {
            dropHeader.messageType := MessageType.WriteLineDataDrop
            io.dropEnq.valid := true.B
            bHo.ready := io.dropEnq.ready
          }
        }
      }
    }
  }

  io.errors.badMessageType := errBadMessageType
  io.errors.badPacketLength := errBadPacketLength
  io.errors.missingHeader := errMissingHeader
  io.errors.unexpectedHeader := errUnexpectedHeader
  io.errors.unexpectedData := errUnexpectedData
}

object GatherSideGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    new GatherSide(params)
  }
}

object GatherSideMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  GatherSideGenerator.generate(args(0), Seq(args(1)))
}
