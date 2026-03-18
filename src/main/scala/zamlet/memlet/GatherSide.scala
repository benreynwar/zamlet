package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{MessageType, NetworkWord, AddressHeader,  PacketConstants}

object KtbState extends ChiselEnum {
  val Idle, ReceiveReadLineAddr, ReceiveWriteAddr,
      ReceiveReadAddr, ReceiveData, DrainAndDrop = Value
}

class GatherSideErrors(params: ZamletParams) extends Bundle {
  val identAllocOverwrite = Output(Bool())
  val missingHeader = Output(Bool())
  val unexpectedHeader = Output(Bool())
  val unexpectedMsgType = Output(Bool())
  val duplicateArrived = Output(Bool())
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
  val dropEnq = Decoupled(new DropEntry(params))

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

  // MemoryEngine reads gathered data from each slice's local storage.
  val gatheringDataRead = new GatheringDataReadPort(params)

  // Slice 0 enqueues completed gathering slots for MemoryEngine
  // to issue AXI4 writes.
  val completeEnq = Decoupled(UInt(log2Ceil(params.nMemletGatheringSlots).W))

  // Slice 0 enqueues ReadLine requests for MemoryEngine to issue
  // AXI4 reads.
  val readLineEnq = Decoupled(new ReadLineEntry(params))

  // MemoryEngine reads authoritative metadata from slice 0 when
  // dequeuing a completed gathering slot.
  val gatheringMetaRead = new GatheringMetaReadPort(params)

  // MemoryEngine tells slice 0 to free a gathering slot after
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
  val writeAddr = UInt(params.wordWidth.W)
  val readAddr = UInt(params.wordWidth.W)
  val needsRead = Bool()
}

class GatherSide(params: ZamletParams) extends Module {
  val io = IO(new GatherSideIO(params))

  val nGSlots = params.nMemletGatheringSlots
  val localJamlets = params.memletLocalJamlets
  val localWords = params.memletLocalWords
  val wordsPerJamlet = params.cacheSlotWordsPerJamlet

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
    init.bits.writeAddr := DontCare
    init.bits.readAddr := DontCare
    init.bits.needsRead := DontCare
    init
  }))



  // ============================================================
  // MemoryEngine read ports
  // ============================================================

  io.gatheringDataRead.data :=
    gatherSlots(io.gatheringDataRead.slotIdx).bits
      .data(io.gatheringDataRead.wordIdx)
  io.gatheringMetaRead.meta := gatherSlots(io.gatheringMetaRead.slotIdx).bits

  // ============================================================
  // Gathering slot free (from MemoryEngine via slice 0)
  // ============================================================

  when(io.isInnerSlice && io.gatheringFree.valid) {
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

  io.identAllocOut := RegNext(io.identAllocIn)

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
  io.readLineEnq.valid := false.B
  io.readLineEnq.bits := DontCare

  // Signal arrived upstream (or enqueue complete at inner slice)
  when(anyComplete) {
    when(io.isInnerSlice) {
      io.completeEnq.valid := true.B
      io.completeEnq.bits := completeSlot
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
  val freeSlotValid = freeSlotVec.asUInt.orR
  val freeSlotIdx = PriorityEncoder(freeSlotVec)

  // Match the incoming packet's ident against the slot idents

  val identMatch = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    identMatch(s) := gatherSlots(s).valid &&
      gatherSlots(s).bits.ident === bHoHeader.ident
  }
  val identFound = identMatch.asUInt.orR
  val identSlotIdx = PriorityEncoder(identMatch)

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

  val packetTypeNext = Wire(MessageType())
  val packetType = RegNext(packetTypeNext, init=0.U)
  packetTypeNext := packetType

  val errMissingHeader = Wire(Bool())
  val errUnexpectedHeader = Wire(Bool())
  errMissingHeader := false.B
  errUnexpectedHeader := false.B

  when(bHo.valid) {
    if (packetWordsRemaining == 0) {
      errMissingHeader := !bHo.bits.isHeader
      packetWordsRemainingNext := bHoHeader.length
      packetTypeNext := bHoHeader.messageType
    } else {
      errUnexpectedHeader := bHo.bits.isHeader
      packetWordsRemainingNext := packetWordsRemaining - 1.U
    }
  }

  io.errors.missingHeader := errMissingHeader
  io.errors.unexpectedHeader := errUnexpectedHeader
}
