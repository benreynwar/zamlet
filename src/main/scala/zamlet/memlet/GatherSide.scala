package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.{MessageType, NetworkWord, CacheLineHeader, PacketConstants, SendType}

class GatherSideErrors(params: ZamletParams) extends Bundle {
  val cacheSlotAllocOverwrite = Output(Bool())
  val missingHeader = Output(Bool())
  val unexpectedHeader = Output(Bool())
  val duplicateArrived = Output(Bool())
  val badMessageType = Output(Bool())
  val badPacketLength = Output(Bool())
  val badSourceCoord = Output(Bool())
  val unexpectedData = Output(Bool())
}

class GatherSideIO(params: ZamletParams) extends Bundle {

  val isInnerSlice = Input(Bool())
  val isOuterSlice = Input(Bool())

  // Jamlet coordinates expected to send data to this memlet router.
  val jamletCoords = Input(Vec(params.memletLocalJamlets, new Bundle {
    val x = UInt(params.xPosWidth.W)
    val y = UInt(params.yPosWidth.W)
  }))

  // Packet stream from the Jamlet-network router's local B-channel output.
  // Carries WriteLineData packets from kamlet jamlets.
  val bHo = Flipped(Decoupled(new NetworkWord(params)))

  // Enqueue port for drop responses. The drop queue itself lives in
  // MemletSlice; BufferToKamlet dequeues from the other end.
  //
  // When the drop queue is full, back-pressuring the incoming B channel is
  // safe: drop responses go out on channel A, which is always consumable, so
  // this cannot close a cycle.
  val dropEnq = Decoupled(new NetworkWord(params))

  // Cache slot allocation propagation chain (outward from slice 0).
  // When slice 0 allocates a gathering slot, it propagates
  // {slotIdx, cacheSlot} so other slices can match CacheLineData packets.
  val cacheSlotAllocIn = Flipped(Valid(new CacheSlotAllocEvent(params)))
  val cacheSlotAllocOut = Valid(new CacheSlotAllocEvent(params))

  // Arrived propagation chain (inward toward slice 0).
  // Each slice sends its slot index when all its local jamlets have
  // sent CacheLineData for that slot. Slice 0 counts these to
  // determine when the full cache line has been gathered.
  val arrivedIn = Flipped(Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W)))
  val arrivedOut = Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W))

  // MemoryEngine reads gathered data from this slice's local storage.
  val gatheringDataReq = Flipped(Decoupled(new GatheringDataReadSliceReq(params)))
  val gatheringDataResp = Decoupled(UInt(params.wordWidth.W))

  // Slice 0 reports completed gathering slots to ControlSide.
  val complete = Valid(new GatheringCompleteEvent(params))

  // MemoryEngine tells all slices to free a gathering slot after
  // copying its data into the AXI4 write pipeline.
  val gatheringFree = Flipped(Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W)))

  // Errors
  val errors = new GatherSideErrors(params)
}

class GatheringSlotLocal(params: ZamletParams) extends Bundle {
  val cacheSlot = params.cacheSlot()
  val data = Vec(params.memletLocalWords, UInt(params.wordWidth.W))
  val arrived = Vec(params.memletLocalJamlets, Bool())
  val arrivedNotified = Bool()
  val outerArrived = Bool()
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
    init.bits.cacheSlot := DontCare
    init.bits.data := DontCare
    init.bits.arrived := VecInit(Seq.fill(localJamlets)(false.B))
    init.bits.arrivedNotified := false.B
    init.bits.outerArrived := false.B
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
  // Cache slot allocation chain (outward from slice 0)
  //
  // Default: forward cacheSlotAllocIn one cycle later.
  // KamletToBuffer overrides cacheSlotAllocOutValid/Bits when
  // allocating at slice 0.
  // ============================================================

  val errCacheSlotAllocOverwrite = Wire(Bool())
  errCacheSlotAllocOverwrite := false.B

  // Store incoming cache slot allocation
  when(io.cacheSlotAllocIn.valid) {
    val idx = io.cacheSlotAllocIn.bits.slotIdx
    errCacheSlotAllocOverwrite := gatherSlots(idx).valid
    gatherSlots(idx).valid := true.B
    gatherSlots(idx).bits.cacheSlot := io.cacheSlotAllocIn.bits.cacheSlot
    for (j <- 0 until localJamlets) {
      gatherSlots(idx).bits.arrived(j) := false.B
    }
    gatherSlots(idx).bits.arrivedNotified := false.B
    gatherSlots(idx).bits.outerArrived := false.B
  }
  io.errors.cacheSlotAllocOverwrite := errCacheSlotAllocOverwrite

  val cacheSlotAllocOutNext = Wire(Valid(new CacheSlotAllocEvent(params)))
  cacheSlotAllocOutNext := io.cacheSlotAllocIn
  io.cacheSlotAllocOut := RegNext(cacheSlotAllocOutNext, init = {
    val init = Wire(Valid(new CacheSlotAllocEvent(params)))
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
  io.complete.valid := false.B
  io.complete.bits := DontCare

  // Signal arrived upstream (or enqueue complete at inner slice)
  when(anyComplete) {
    when(io.isInnerSlice) {
      io.complete.valid := true.B
      io.complete.bits.slotIdx := completeSlot
      gatherSlots(completeSlot).bits.arrivedNotified := true.B
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
  val paHeader = paFromNetwork.bits.data.asTypeOf(new CacheLineHeader(params))
  dontTouch(paHeader)
  val paLastHeaderNext = Wire(new CacheLineHeader(params))
  val paLastHeader = RegNext(paLastHeaderNext)
  paLastHeaderNext := paLastHeader

  val paFirstBodyWordNext = Wire(Bool())
  val paFirstBodyWord = RegNext(paFirstBodyWordNext, init = false.B)
  paFirstBodyWordNext := paFirstBodyWord

  // Match data packets by cache slot.
  val paCacheSlotMatch = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    paCacheSlotMatch(s) := gatherSlots(s).valid &&
      gatherSlots(s).bits.cacheSlot === paHeader.slot
  }
  val paCacheSlotMatchSlot = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
  paCacheSlotMatchSlot.valid := paCacheSlotMatch.asUInt.orR
  paCacheSlotMatchSlot.bits := PriorityEncoder(paCacheSlotMatch)
  dontTouch(paCacheSlotMatchSlot)

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
  // All slices receive only WriteLineData packets here.

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
  val errBadSourceCoord = Wire(Bool())
  val errUnexpectedData = Wire(Bool())
  errMissingHeader := false.B
  errUnexpectedHeader := false.B
  errBadMessageType := false.B
  errBadPacketLength := false.B
  errBadSourceCoord := false.B
  errUnexpectedData := false.B

  // Drop header is sent when we're working on the first body word.
  val dropHeader = Wire(new CacheLineHeader(params))
  dropHeader.targetX := paLastHeader.sourceX
  dropHeader.targetY := paLastHeader.sourceY
  dropHeader.sourceX := paLastHeader.targetX
  dropHeader.sourceY := paLastHeader.targetY
  dropHeader.length := 0.U
  dropHeader.slot := paLastHeader.slot
  dropHeader.sendType := SendType.Single
  dropHeader._padding := 0.U
  dropHeader.messageType := MessageType.WriteLineDataDrop

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
        paSlotNext := paCacheSlotMatchSlot
        val sourceMatches = VecInit((0 until localJamlets).map { j =>
          paHeader.sourceX === io.jamletCoords(j).x &&
            paHeader.sourceY === io.jamletCoords(j).y
        })
        val sourceMatchCount = PopCount(sourceMatches)
        val sourceMatchValid = sourceMatchCount === 1.U
        paSlotNext.valid := paCacheSlotMatchSlot.valid && sourceMatchValid
        paJamletIdxNext := PriorityEncoder(sourceMatches)
        errBadSourceCoord := paFromNetwork.bits.isHeader &&
          paHeader.messageType === MessageType.WriteLineData &&
          !sourceMatchValid
      }
      errBadPacketLength := false.B
      errBadMessageType := paHeader.messageType =/= MessageType.WriteLineData
      switch(paHeader.messageType) {
        is(MessageType.WriteLineData) {
          errBadPacketLength := (paHeader.length =/= params.cacheSlotWordsPerJamlet.U)
        }
      }
    } .otherwise {
      when (paFromNetwork.ready) {
        paWordsRemainingNext := paWordsRemaining - 1.U
      }
      errUnexpectedHeader := paFromNetwork.bits.isHeader
      switch(paLastHeader.messageType) {
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
  io.errors.badSourceCoord := errBadSourceCoord
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
