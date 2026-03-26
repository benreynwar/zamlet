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
  // Also enqueues the read requests.
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
  val wordsPerJamlet = params.cacheSlotWordsPerJamlet

  // We use the prefixes pa, pb, .. to represent the pipeline stages
  // of processing the packet stream.
  val paFromNetwork = Wire(Decoupled(new NetworkWord(params)))
  paFromNetwork <> io.bHo
  dontTouch(paFromNetwork)

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

  val gatheringDataRespQ = Module(new Queue(UInt(params.wordWidth.W), entries = 2))
  gatheringDataRespQ.io.enq.valid := io.gatheringDataReq.valid
  gatheringDataRespQ.io.enq.bits :=
    gatherSlots(io.gatheringDataReq.bits.slotIdx).bits
      .data(io.gatheringDataReq.bits.wordIdx)
  io.gatheringDataReq.ready := gatheringDataRespQ.io.enq.ready
  io.gatheringDataResp <> gatheringDataRespQ.io.deq

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

  // Store incoming ident allocation
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

  // Have a completeEnq for reads (doesn't use gathering slots)
  // and one for the others.
  val completeReadEnq = Wire(Decoupled(new GatheringSlotMeta(params)))
  completeReadEnq.valid := false.B
  completeReadEnq.bits := DontCare
  completeReadEnq.ready := DontCare
  val completeGatheredEnq = Wire(Decoupled(new GatheringSlotMeta(params)))
  completeGatheredEnq.valid := false.B
  completeGatheredEnq.bits := DontCare
  completeGatheredEnq.ready := DontCare

  io.completeEnq.valid := completeReadEnq.valid || completeGatheredEnq.valid
  when (!completeReadEnq.valid) {
    io.completeEnq.bits := completeGatheredEnq.bits
  } .otherwise {
    io.completeEnq.bits := completeReadEnq.bits
  }

  // Signal arrived upstream (or enqueue complete at inner slice)
  when(anyComplete) {
    when(io.isInnerSlice) {
      val slot = gatherSlots(completeSlot).bits
      completeGatheredEnq.valid := true.B
      completeGatheredEnq.bits.slotIdx := completeSlot
      completeGatheredEnq.bits.ident := slot.ident
      completeGatheredEnq.bits.sramAddr := slot.sramAddr
      completeGatheredEnq.bits.sourceX := slot.sourceX
      completeGatheredEnq.bits.sourceY := slot.sourceY
      completeGatheredEnq.bits.writeAddr := slot.writeAddr
      completeGatheredEnq.bits.readAddr := slot.readAddr
      completeGatheredEnq.bits.writes := true.B
      completeGatheredEnq.bits.reads := slot.reads
      when(!completeReadEnq.valid && io.completeEnq.ready) {
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
  val paHeader = paFromNetwork.bits.data.asTypeOf(new AddressHeader(params))
  dontTouch(paHeader)
  val paLastHeaderNext = Wire(new AddressHeader(params))
  val paLastHeader = RegNext(paLastHeaderNext)
  paLastHeaderNext := paLastHeader

  val paFirstBodyWordNext = Wire(Bool())
  val paFirstBodyWord = RegNext(paFirstBodyWordNext, init = false.B)
  paFirstBodyWordNext := paFirstBodyWord

  // Find if there are any free slots.

  val freeSlotVec = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    freeSlotVec(s) := !gatherSlots(s).valid
  }

  // We'll use this if it is a address packet.
  val freeSlot = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
  freeSlot.valid := freeSlotVec.asUInt.orR
  freeSlot.bits := PriorityEncoder(freeSlotVec)

  // We'll use this if it is a data packet.
  val paIdentMatch = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    paIdentMatch(s) := gatherSlots(s).valid &&
      gatherSlots(s).bits.ident === paHeader.ident
  }
  val paIdentMatchSlot = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
  paIdentMatchSlot.valid := paIdentMatch.asUInt.orR
  paIdentMatchSlot.bits := PriorityEncoder(paIdentMatch)
  dontTouch(paIdentMatchSlot)

  // The slot that we need to put something in based on the arriving header.
  val paHeaderSlot = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
  paHeaderSlot.valid := false.B
  paHeaderSlot.bits := DontCare
  // A register where we store the slot to use for the body.
  val paSlotNext = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
  val paSlot = RegNext(paSlotNext, init = {
    val init = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
    init.valid := false.B
    init.bits := DontCare
    init
  })
  paSlotNext := paSlot

  // The local jamlet index that the last packet header came from.
  val paJamletIdxNext = Wire(UInt(log2Ceil(localJamlets).W))
  val paJamletIdx = RegNext(paJamletIdxNext)
  paJamletIdxNext := paJamletIdx

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
  
  val paWordsRemainingNext = Wire(UInt(PacketConstants.lengthWidth))
  val paWordsRemaining = RegNext(paWordsRemainingNext, init=0.U)
  paWordsRemainingNext := paWordsRemaining

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

  // Drop header is sent when we're working on the
  // first body word.
  val dropHeader = Wire(new IdentHeader(params))
  dropHeader.targetX := paLastHeader.sourceX
  dropHeader.targetY := paLastHeader.sourceY
  dropHeader.sourceX := paLastHeader.targetX
  dropHeader.sourceY := paLastHeader.targetY
  dropHeader.length := 0.U
  dropHeader.ident := paLastHeader.ident
  dropHeader.sendType := SendType.Single
  dropHeader.messageType := paLastHeader.messageType
  dropHeader._padding := 0.U

  io.dropEnq.valid := false.B
  io.dropEnq.bits.data := dropHeader.asUInt
  io.dropEnq.bits.isHeader := true.B
  paFromNetwork.ready := false.B

  when(paFromNetwork.valid) {
    when (paFromNetwork.ready) {
      paFirstBodyWordNext := paFromNetwork.bits.isHeader
    }
    when (paWordsRemaining === 0.U) {
      // This should be a header.
      errMissingHeader := !paFromNetwork.bits.isHeader
      // Set a default value for ready. Can be overriden.
      paFromNetwork.ready := true.B
      // Update the state registers.
      when (paFromNetwork.ready) {
        paWordsRemainingNext := paHeader.length
        paLastHeaderNext := paHeader
        paSlotNext := paHeaderSlot
        paJamletIdxNext := {
          val jX = paHeader.sourceX - io.kBaseX
          val jY = paHeader.sourceY - io.kBaseY
          val jIdx = jY * params.jCols.U + jX
          (jIdx & (localJamlets - 1).U)(log2Ceil(localJamlets) - 1, 0)
        }
      }
      errBadPacketLength := false.B
      errBadMessageType := true.B
      switch(paHeader.messageType) {
        is(MessageType.WriteLineAddr) {
          paHeaderSlot := freeSlot
          errBadPacketLength := (paHeader.length =/= 1.U)
          errBadMessageType := !io.isInnerSlice
          when (!paHeaderSlot.valid) {
            io.dropEnq.valid := true.B
            paFromNetwork.ready := io.dropEnq.ready
          }
        }
        is(MessageType.ReadLineAddr) {
          paHeaderSlot := freeSlot
          errBadPacketLength := (paHeader.length =/= 1.U)
          errBadMessageType := !io.isInnerSlice
          when (!paHeaderSlot.valid) {
            io.dropEnq.valid := true.B
            paFromNetwork.ready := io.dropEnq.ready
          }
        }
        is(MessageType.WriteLineReadLineAddr) {
          paHeaderSlot := freeSlot
          errBadPacketLength := (paHeader.length =/= 2.U)
          errBadMessageType := !io.isInnerSlice
          when (!paHeaderSlot.valid) {
            io.dropEnq.valid := true.B
            paFromNetwork.ready := io.dropEnq.ready
          }
        }
        is(MessageType.WriteLineData) {
          paHeaderSlot := paIdentMatchSlot
          errBadPacketLength := (paHeader.length =/= params.cacheSlotWordsPerJamlet.U)
          errBadMessageType := false.B
          when (!paHeaderSlot.valid) {
            io.dropEnq.valid := true.B
            paFromNetwork.ready := io.dropEnq.ready
          }
        }
      }
    } .otherwise {
      when (paFromNetwork.ready) {
        paWordsRemainingNext := paWordsRemaining - 1.U
      }
      errUnexpectedHeader := paFromNetwork.bits.isHeader
      switch(paLastHeader.messageType) {
        is(MessageType.WriteLineAddr) {
          // We got a new write request. We need to allocate a slot for it.
          when (paSlot.valid) {
            paFromNetwork.ready := true.B
            gatherSlots(paSlot.bits).valid := true.B
            gatherSlots(paSlot.bits).bits.ident := paLastHeader.ident
            for (j <- 0 until localJamlets) {
              gatherSlots(paSlot.bits).bits.arrived(j) := false.B
            }
            gatherSlots(paSlot.bits).bits.arrivedNotified := false.B
            gatherSlots(paSlot.bits).bits.outerArrived := false.B
            gatherSlots(paSlot.bits).bits.sramAddr := paLastHeader.address
            gatherSlots(paSlot.bits).bits.sourceX := paLastHeader.sourceX
            gatherSlots(paSlot.bits).bits.sourceY := paLastHeader.sourceY
            gatherSlots(paSlot.bits).bits.writeAddr := paFromNetwork.bits.data
            gatherSlots(paSlot.bits).bits.readAddr := 0.U
            gatherSlots(paSlot.bits).bits.reads := false.B
            identAllocOutNext.valid := true.B
            identAllocOutNext.bits.ident := paLastHeader.ident
            identAllocOutNext.bits.slotIdx := paSlot.bits
          } .otherwise {
            when (paFirstBodyWord) {
              io.dropEnq.valid := true.B
              paFromNetwork.ready := io.dropEnq.ready
            } .otherwise {
              paFromNetwork.ready := true.B
            }
          }
        }
        is(MessageType.WriteLineReadLineAddr) {
          // We got a new write/read request. We need to allocate a slot for it
          // and submit a read request.
          // The first packet word is the write address.
          // The second is the read address.
          when (paSlot.valid) {
            paFromNetwork.ready := true.B
            when (paWordsRemaining === 2.U) {
              // Get the write address
              gatherSlots(paSlot.bits).valid := false.B
              gatherSlots(paSlot.bits).bits.ident := paLastHeader.ident
              for (j <- 0 until localJamlets) {
                gatherSlots(paSlot.bits).bits.arrived(j) := false.B
              }
              gatherSlots(paSlot.bits).bits.arrivedNotified := false.B
              gatherSlots(paSlot.bits).bits.outerArrived := false.B
              gatherSlots(paSlot.bits).bits.sramAddr := paLastHeader.address
              gatherSlots(paSlot.bits).bits.sourceX := paLastHeader.sourceX
              gatherSlots(paSlot.bits).bits.sourceY := paLastHeader.sourceY
              gatherSlots(paSlot.bits).bits.writeAddr := paFromNetwork.bits.data
              gatherSlots(paSlot.bits).bits.reads := true.B
            } .otherwise {
              // Get the read address
              gatherSlots(paSlot.bits).valid := true.B
              gatherSlots(paSlot.bits).bits.readAddr := paFromNetwork.bits.data
              identAllocOutNext.valid := true.B
              identAllocOutNext.bits.ident := paLastHeader.ident
              identAllocOutNext.bits.slotIdx := paSlot.bits
            }
          } .otherwise {
            when (paFirstBodyWord) {
              io.dropEnq.valid := true.B
              paFromNetwork.ready := io.dropEnq.ready
            } .otherwise {
              paFromNetwork.ready := true.B
            }
          }
        }
        is(MessageType.ReadLineAddr) {
          completeReadEnq.valid := true.B
          completeReadEnq.bits.slotIdx := DontCare
          completeReadEnq.bits.ident := paLastHeader.ident
          completeReadEnq.bits.sramAddr := paLastHeader.address
          completeReadEnq.bits.sourceX := paLastHeader.sourceX
          completeReadEnq.bits.sourceY := paLastHeader.sourceY
          completeReadEnq.bits.writeAddr := DontCare
          completeReadEnq.bits.readAddr := paFromNetwork.bits.data
          completeReadEnq.bits.writes := false.B
          completeReadEnq.bits.reads := true.B
          when (io.completeEnq.ready) {
            paFromNetwork.ready := true.B
          } .otherwise {
            io.dropEnq.valid := true.B
            paFromNetwork.ready := io.dropEnq.ready
          }
        }
        is(MessageType.WriteLineData) {
          when (paSlot.valid) {
            paFromNetwork.ready := true.B
            val wordOffset = (wordsPerJamlet.U - paWordsRemaining)(log2Ceil(wordsPerJamlet) - 1, 0)
            val dataIdx = paJamletIdx * wordsPerJamlet.U + wordOffset
            gatherSlots(paSlot.bits).bits.data(dataIdx) := paFromNetwork.bits.data
            when (paWordsRemaining === 1.U) {
              gatherSlots(paSlot.bits).bits.arrived(paJamletIdx) := true.B
              errUnexpectedData := gatherSlots(paSlot.bits).bits.arrived(paJamletIdx)
            }
          } .otherwise {
            when (paFirstBodyWord) {
              io.dropEnq.valid := true.B
              paFromNetwork.ready := io.dropEnq.ready
            } .otherwise {
              paFromNetwork.ready := true.B
            }

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
