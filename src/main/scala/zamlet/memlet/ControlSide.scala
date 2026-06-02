package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.{CacheLineHeader, MessageType, NetworkWord, PacketConstants, SendType}

class ControlSideErrors(params: ZamletParams) extends Bundle {
  val allocOverwrite = Output(Bool())
  val duplicateComplete = Output(Bool())
  val missingHeader = Output(Bool())
  val unexpectedHeader = Output(Bool())
  val badMessageType = Output(Bool())
  val badPacketLength = Output(Bool())
}

class ControlSlot(params: ZamletParams) extends Bundle {
  val cacheSlot = params.cacheSlot()
  val sourceX = UInt(params.xPosWidth.W)
  val sourceY = UInt(params.yPosWidth.W)
  val writeAddr = UInt(params.wordWidth.W)
  val readAddr = UInt(params.wordWidth.W)
  val reads = Bool()
  val complete = Bool()
  val submitted = Bool()
}

class ControlSideIO(params: ZamletParams) extends Bundle {
  val controlBHo = Flipped(Decoupled(new NetworkWord(params)))
  val controlAHi = Decoupled(new NetworkWord(params))

  val writeLineRespEnq = Flipped(Decoupled(new NetworkWord(params)))

  val cacheSlotAllocOut = Valid(new CacheSlotAllocEvent(params))
  val gatherComplete = Flipped(Valid(new GatheringCompleteEvent(params)))
  val gatheringFree = Flipped(Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W)))

  val completeEnq = Decoupled(new GatheringSlotMeta(params))

  val errors = new ControlSideErrors(params)
}

class ControlSide(params: ZamletParams) extends Module {
  val io = IO(new ControlSideIO(params))

  val nGSlots = params.nMemletGatheringSlots

  // ============================================================
  // Shared request state
  // ============================================================

  val controlSlotsNext = Wire(Vec(nGSlots, Valid(new ControlSlot(params))))
  val controlSlots = RegEnable(
    controlSlotsNext,
    0.U.asTypeOf(Vec(nGSlots, Valid(new ControlSlot(params)))),
    true.B)
  controlSlotsNext := controlSlots

  val freeSlotVec = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    freeSlotVec(s) := !controlSlots(s).valid
  }
  val freeSlot = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
  freeSlot.valid := freeSlotVec.asUInt.orR
  freeSlot.bits := PriorityEncoder(freeSlotVec)

  // ============================================================
  // Parser pipeline state
  // ============================================================

  val lastHeaderNext = Wire(new CacheLineHeader(params))
  val lastHeader = RegEnable(
    lastHeaderNext,
    0.U.asTypeOf(new CacheLineHeader(params)),
    true.B)
  lastHeaderNext := lastHeader

  val selectedSlotNext = Wire(Valid(UInt(log2Ceil(nGSlots).W)))
  val selectedSlot = RegEnable(
    selectedSlotNext,
    0.U.asTypeOf(Valid(UInt(log2Ceil(nGSlots).W))),
    true.B)
  selectedSlotNext := selectedSlot

  val wordsRemainingNext = Wire(UInt(PacketConstants.lengthWidth))
  val wordsRemaining = RegEnable(
    wordsRemainingNext,
    0.U(PacketConstants.lengthWidth),
    true.B)
  wordsRemainingNext := wordsRemaining

  val firstBodyWordNext = Wire(Bool())
  val firstBodyWord = RegEnable(firstBodyWordNext, false.B, true.B)
  firstBodyWordNext := firstBodyWord

  val incomingHeader = io.controlBHo.bits.data.asTypeOf(
    new CacheLineHeader(params))

  // ============================================================
  // Registered error output
  // ============================================================

  val errorsNext = Wire(new ControlSideErrors(params))
  errorsNext.allocOverwrite := false.B
  errorsNext.duplicateComplete := false.B
  errorsNext.missingHeader := false.B
  errorsNext.unexpectedHeader := false.B
  errorsNext.badMessageType := false.B
  errorsNext.badPacketLength := false.B

  io.cacheSlotAllocOut.valid := false.B
  io.cacheSlotAllocOut.bits := DontCare
  io.completeEnq.valid := false.B
  io.completeEnq.bits := DontCare
  io.controlBHo.ready := false.B

  // ============================================================
  // Control response/drop source
  // ============================================================

  val parserDropHeader = Wire(new CacheLineHeader(params))
  parserDropHeader.targetX := lastHeader.sourceX
  parserDropHeader.targetY := lastHeader.sourceY
  parserDropHeader.sourceX := lastHeader.targetX
  parserDropHeader.sourceY := lastHeader.targetY
  parserDropHeader.length := 0.U
  parserDropHeader.slot := lastHeader.slot
  parserDropHeader.sendType := SendType.Single
  parserDropHeader._padding := 0.U
  parserDropHeader.messageType := lastHeader.messageType
  switch(lastHeader.messageType) {
    is(MessageType.WriteLineAddr) {
      parserDropHeader.messageType := MessageType.WriteLineAddrDrop
    }
    is(MessageType.ReadLineAddr) {
      parserDropHeader.messageType := MessageType.ReadLineAddrDrop
    }
    is(MessageType.WriteLineReadLineAddr) {
      parserDropHeader.messageType := MessageType.WriteLineReadLineAddrDrop
    }
  }

  val parserDropValid = Wire(Bool())
  parserDropValid := false.B

  val parserDropWord = Wire(new NetworkWord(params))
  parserDropWord.data := parserDropHeader.asUInt
  parserDropWord.isHeader := true.B

  // ============================================================
  // Gather-completion pipeline
  // ============================================================

  when(io.gatheringFree.valid) {
    controlSlotsNext(io.gatheringFree.bits).valid := false.B
  }

  when(io.gatherComplete.valid) {
    val slotIdx = io.gatherComplete.bits.slotIdx
    errorsNext.duplicateComplete :=
      controlSlots(slotIdx).bits.complete || controlSlots(slotIdx).bits.submitted
    controlSlotsNext(slotIdx).bits.complete := true.B
  }

  val completeVec = Wire(Vec(nGSlots, Bool()))
  for (s <- 0 until nGSlots) {
    completeVec(s) := controlSlots(s).valid &&
      controlSlots(s).bits.complete &&
      !controlSlots(s).bits.submitted
  }
  val completeSlot = PriorityEncoder(completeVec.asUInt)
  val hasComplete = completeVec.asUInt.orR

  when(hasComplete) {
    val slot = controlSlots(completeSlot).bits
    io.completeEnq.valid := true.B
    io.completeEnq.bits.slotIdx := completeSlot
    io.completeEnq.bits.cacheSlot := slot.cacheSlot
    io.completeEnq.bits.sourceX := slot.sourceX
    io.completeEnq.bits.sourceY := slot.sourceY
    io.completeEnq.bits.writeAddr := slot.writeAddr
    io.completeEnq.bits.readAddr := slot.readAddr
    io.completeEnq.bits.writes := true.B
    io.completeEnq.bits.reads := slot.reads
    when(io.completeEnq.ready) {
      controlSlotsNext(completeSlot).bits.submitted := true.B
    }
  }

  // ============================================================
  // Control packet parser/allocation pipeline
  // ============================================================

  when(io.controlBHo.valid && !hasComplete) {
    when(wordsRemaining === 0.U) {
      errorsNext.missingHeader := !io.controlBHo.bits.isHeader
      io.controlBHo.ready := true.B
      when(io.controlBHo.fire) {
        lastHeaderNext := incomingHeader
        wordsRemainingNext := incomingHeader.length
        firstBodyWordNext := true.B
        selectedSlotNext.valid := freeSlot.valid
        selectedSlotNext.bits := freeSlot.bits
      }

      errorsNext.badMessageType := true.B
      switch(incomingHeader.messageType) {
        is(MessageType.WriteLineAddr) {
          errorsNext.badPacketLength := incomingHeader.length =/= 1.U
          errorsNext.badMessageType := false.B
        }
        is(MessageType.ReadLineAddr) {
          errorsNext.badPacketLength := incomingHeader.length =/= 1.U
          errorsNext.badMessageType := false.B
        }
        is(MessageType.WriteLineReadLineAddr) {
          errorsNext.badPacketLength := incomingHeader.length =/= 2.U
          errorsNext.badMessageType := false.B
        }
      }
    }.otherwise {
      errorsNext.unexpectedHeader := io.controlBHo.bits.isHeader

      switch(lastHeader.messageType) {
        is(MessageType.WriteLineAddr) {
          when(selectedSlot.valid) {
            io.controlBHo.ready := true.B
            val slotIdx = selectedSlot.bits
            errorsNext.allocOverwrite := controlSlots(slotIdx).valid
            controlSlotsNext(slotIdx).valid := true.B
            controlSlotsNext(slotIdx).bits.cacheSlot := lastHeader.slot
            controlSlotsNext(slotIdx).bits.sourceX := lastHeader.sourceX
            controlSlotsNext(slotIdx).bits.sourceY := lastHeader.sourceY
            controlSlotsNext(slotIdx).bits.writeAddr := io.controlBHo.bits.data
            controlSlotsNext(slotIdx).bits.readAddr := 0.U
            controlSlotsNext(slotIdx).bits.reads := false.B
            controlSlotsNext(slotIdx).bits.complete := false.B
            controlSlotsNext(slotIdx).bits.submitted := false.B
            io.cacheSlotAllocOut.valid := true.B
            io.cacheSlotAllocOut.bits.slotIdx := slotIdx
            io.cacheSlotAllocOut.bits.cacheSlot := lastHeader.slot
          }.otherwise {
            parserDropValid := firstBodyWord
            io.controlBHo.ready := !firstBodyWord || io.controlAHi.ready
          }
        }
        is(MessageType.WriteLineReadLineAddr) {
          when(selectedSlot.valid) {
            io.controlBHo.ready := true.B
            val slotIdx = selectedSlot.bits
            when(wordsRemaining === 2.U) {
              errorsNext.allocOverwrite := controlSlots(slotIdx).valid
              controlSlotsNext(slotIdx).valid := true.B
              controlSlotsNext(slotIdx).bits.cacheSlot := lastHeader.slot
              controlSlotsNext(slotIdx).bits.sourceX := lastHeader.sourceX
              controlSlotsNext(slotIdx).bits.sourceY := lastHeader.sourceY
              controlSlotsNext(slotIdx).bits.writeAddr := io.controlBHo.bits.data
              controlSlotsNext(slotIdx).bits.reads := true.B
              controlSlotsNext(slotIdx).bits.complete := false.B
              controlSlotsNext(slotIdx).bits.submitted := false.B
            }.otherwise {
              controlSlotsNext(slotIdx).bits.readAddr := io.controlBHo.bits.data
              io.cacheSlotAllocOut.valid := true.B
              io.cacheSlotAllocOut.bits.slotIdx := slotIdx
              io.cacheSlotAllocOut.bits.cacheSlot := lastHeader.slot
            }
          }.otherwise {
            parserDropValid := firstBodyWord
            io.controlBHo.ready := !firstBodyWord || io.controlAHi.ready
          }
        }
        is(MessageType.ReadLineAddr) {
          io.completeEnq.valid := true.B
          io.completeEnq.bits.slotIdx := DontCare
          io.completeEnq.bits.cacheSlot := lastHeader.slot
          io.completeEnq.bits.sourceX := lastHeader.sourceX
          io.completeEnq.bits.sourceY := lastHeader.sourceY
          io.completeEnq.bits.writeAddr := DontCare
          io.completeEnq.bits.readAddr := io.controlBHo.bits.data
          io.completeEnq.bits.writes := false.B
          io.completeEnq.bits.reads := true.B
          when(io.completeEnq.ready) {
            io.controlBHo.ready := true.B
          }.otherwise {
            parserDropValid := firstBodyWord
            io.controlBHo.ready := firstBodyWord && io.controlAHi.ready
          }
        }
      }

      when(io.controlBHo.fire) {
        wordsRemainingNext := wordsRemaining - 1.U
        firstBodyWordNext := false.B
      }
    }
  }

  // ============================================================
  // Control response output pipeline
  // ============================================================

  io.controlAHi.valid := parserDropValid || io.writeLineRespEnq.valid
  io.controlAHi.bits := Mux(
    parserDropValid,
    parserDropWord,
    io.writeLineRespEnq.bits)
  io.writeLineRespEnq.ready := !parserDropValid && io.controlAHi.ready

  val errors = RegEnable(
    errorsNext,
    0.U.asTypeOf(new ControlSideErrors(params)),
    true.B)
  io.errors.allocOverwrite := errors.allocOverwrite
  io.errors.duplicateComplete := errors.duplicateComplete
  io.errors.missingHeader := errors.missingHeader
  io.errors.unexpectedHeader := errors.unexpectedHeader
  io.errors.badMessageType := errors.badMessageType
  io.errors.badPacketLength := errors.badPacketLength
}
