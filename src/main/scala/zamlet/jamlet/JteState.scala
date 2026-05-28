package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer
import zamlet.utils.ValidBuffer

class JteCreate(params: ZamletParams) extends Bundle {
  val slot = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val dataReg = params.rfAddr()
}

class JteStateSlot(params: ZamletParams) extends Bundle {
  val valid = Bool()
  val completeSent = Bool()
  val instrIdent = params.ident()
  val dataReg = params.rfAddr()
  val initiator = Vec(params.wordBytes, JteInitiatorState())
  val walkState = JteWalkState()
}

class JteStateErrors extends Bundle {
  val createSlotInUse = Bool()
  val slotToRegInvalid = Bool()
  val receiverUpdateInvalid = Bool()
  val receiverUpdateIdentMismatch = Bool()
  val initiatorCommitInvalid = Bool()
}

class JteStateDispatchAB(params: ZamletParams) extends Bundle {
  val slot = UInt(log2Ceil(params.witemTableDepth).W)
}

class JteStateDispatchBC(params: ZamletParams) extends Bundle {
  val slot = UInt(log2Ceil(params.witemTableDepth).W)
}

class JteStateIO(params: ZamletParams) extends Bundle {
  val create = Flipped(Valid(new JteCreate(params)))
  val clear = Flipped(Valid(UInt(log2Ceil(params.witemTableDepth).W)))

  val inputReq = Decoupled(UInt(log2Ceil(params.witemTableDepth).W))
  val inputResp = Flipped(Decoupled(new JteInitiatorInput(params)))
  val initiatorDispatch = Decoupled(new JteInitiatorInput(params))
  val initiatorCommit = Flipped(Valid(new JteInitiatorCommit(params)))

  val receiverUpdate = Flipped(Decoupled(new JteReceiverUpdateMsg(params)))
  val slotToRegReq = Flipped(Decoupled(UInt(log2Ceil(params.witemTableDepth).W)))
  val slotToRegResp = Decoupled(params.rfAddr())

  val transferComplete = Output(Vec(params.witemTableDepth, Bool()))
  val errors = Output(new JteStateErrors())
}

class JteState(params: ZamletParams) extends Module {
  val io = IO(new JteStateIO(params))
  val sp = params.jteStateParams

  val slotsInitial = VecInit(Seq.fill(params.witemTableDepth)(0.U.asTypeOf(new JteStateSlot(params))))
  val slotsNext = Wire(Vec(params.witemTableDepth, new JteStateSlot(params)))
  val slots = RegEnable(slotsNext, slotsInitial, true.B)
  slotsNext := slots

  val inputReq = Wire(Decoupled(UInt(log2Ceil(params.witemTableDepth).W)))
  io.inputReq <> DoubleBuffer(inputReq, sp.inputReqFB, sp.inputReqBB)
  val inputResp = DoubleBuffer(io.inputResp, sp.inputRespFB, sp.inputRespBB)
  val initiatorDispatch = Wire(Decoupled(new JteInitiatorInput(params)))
  io.initiatorDispatch <> DoubleBuffer(initiatorDispatch, sp.initiatorDispatchFB, sp.initiatorDispatchBB)
  val receiverUpdate = DoubleBuffer(io.receiverUpdate, sp.receiverUpdateFB, sp.receiverUpdateBB)
  val slotToRegReq = DoubleBuffer(io.slotToRegReq, sp.slotToRegReqFB, sp.slotToRegReqBB)
  val slotToRegResp = Wire(Decoupled(params.rfAddr()))
  io.slotToRegResp <> DoubleBuffer(slotToRegResp, sp.slotToRegRespFB, sp.slotToRegRespBB)
  val create = ValidBuffer(io.create, sp.createBuffer)
  val clear = ValidBuffer(io.clear, sp.clearBuffer)
  val initiatorCommit = ValidBuffer(io.initiatorCommit, sp.initiatorCommitBuffer)

  inputReq.valid := false.B
  inputReq.bits := 0.U
  inputResp.ready := false.B
  initiatorDispatch.valid := false.B
  initiatorDispatch.bits := 0.U.asTypeOf(new JteInitiatorInput(params))
  receiverUpdate.ready := false.B
  slotToRegReq.ready := false.B
  slotToRegResp.valid := false.B
  slotToRegResp.bits := 0.U
  io.errors.createSlotInUse := create.valid && slots(create.bits.slot).valid
  io.errors.slotToRegInvalid := slotToRegReq.valid && !slots(slotToRegReq.bits).valid
  io.errors.receiverUpdateInvalid := receiverUpdate.valid && !slots(receiverUpdate.bits.slot).valid
  io.errors.receiverUpdateIdentMismatch := receiverUpdate.valid &&
    slots(receiverUpdate.bits.slot).valid &&
    slots(receiverUpdate.bits.slot).instrIdent =/= receiverUpdate.bits.ident
  io.errors.initiatorCommitInvalid := initiatorCommit.valid && !slots(initiatorCommit.bits.slot).valid

  slotToRegReq.ready := slotToRegResp.ready
  slotToRegResp.valid := slotToRegReq.valid
  slotToRegResp.bits := slots(slotToRegReq.bits).dataReg
  receiverUpdate.ready := true.B

  // Dispatch A: select a slot that needs another initiator walk.
  val dispatchACandidates = VecInit((0 until params.witemTableDepth).map { i =>
    slots(i).valid && slots(i).walkState === JteWalkState.NeedsProcessing
  })
  val dispatchAValid = dispatchACandidates.reduce(_ || _)
  val dispatchASlot = PriorityEncoder(dispatchACandidates)
  val dispatchAB = Wire(Decoupled(new JteStateDispatchAB(params)))
  dispatchAB.valid := dispatchAValid
  dispatchAB.bits.slot := dispatchASlot
  when (dispatchAB.fire) {
    slotsNext(dispatchASlot).walkState := JteWalkState.InProgress
  }

  // Dispatch B: request the full initiator input from the kamlet core.
  val dispatchABBuffered = DoubleBuffer(dispatchAB, sp.dispatchABFB, sp.dispatchABBB)
  val dispatchBC = Wire(Decoupled(new JteStateDispatchBC(params)))
  inputReq.valid := dispatchABBuffered.valid && dispatchBC.ready
  inputReq.bits := dispatchABBuffered.bits.slot
  dispatchBC.valid := dispatchABBuffered.valid && inputReq.ready
  dispatchBC.bits.slot := dispatchABBuffered.bits.slot
  dispatchABBuffered.ready := inputReq.ready && dispatchBC.ready

  // Dispatch C: wait for the full input and dispatch it to the initiator.
  val dispatchBCBuffered = DoubleBuffer(dispatchBC, sp.dispatchBCFB, sp.dispatchBCBB)
  inputResp.ready := dispatchBCBuffered.valid && initiatorDispatch.ready
  initiatorDispatch.valid := dispatchBCBuffered.valid && inputResp.valid
  initiatorDispatch.bits := inputResp.bits
  initiatorDispatch.bits.slot := dispatchBCBuffered.bits.slot
  dispatchBCBuffered.ready := inputResp.valid && initiatorDispatch.ready

  when (receiverUpdate.fire) {
    val slot = receiverUpdate.bits.slot
    val offset = receiverUpdate.bits.offset
    when (receiverUpdate.bits.drop) {
      slotsNext(slot).initiator(offset) := JteInitiatorState.Dropped
      slotsNext(slot).walkState := JteWalkState.NeedsProcessing
    } .otherwise {
      slotsNext(slot).initiator(offset) := JteInitiatorState.Complete
    }
  }

  when (initiatorCommit.valid) {
    val slot = initiatorCommit.bits.slot
    for (i <- 0 until params.wordBytes) {
      val current = slots(slot).initiator(i)
      when (current === JteInitiatorState.Complete || current === JteInitiatorState.Dropped) {
        slotsNext(slot).initiator(i) := current
      } .otherwise {
        slotsNext(slot).initiator(i) := initiatorCommit.bits.initiator(i)
      }
    }
    when (slots(slot).walkState =/= JteWalkState.NeedsProcessing) {
      slotsNext(slot).walkState := initiatorCommit.bits.walkState
    }
  }

  when (create.valid) {
    val slot = create.bits.slot
    slotsNext(slot).valid := true.B
    slotsNext(slot).completeSent := false.B
    slotsNext(slot).instrIdent := create.bits.instrIdent
    slotsNext(slot).dataReg := create.bits.dataReg
    slotsNext(slot).walkState := JteWalkState.NeedsProcessing
    for (i <- 0 until params.wordBytes) {
      slotsNext(slot).initiator(i) := JteInitiatorState.Initial
    }
  }

  when (clear.valid) {
    slotsNext(clear.bits).valid := false.B
  }

  for (i <- 0 until params.witemTableDepth) {
    val complete = slots(i).valid &&
      slots(i).walkState === JteWalkState.Done &&
      slots(i).initiator.map(_ === JteInitiatorState.Complete).reduce(_ && _)
    io.transferComplete(i) := complete && !slots(i).completeSent
    when (complete) {
      slotsNext(i).completeSent := true.B
    }
  }
}

object JteStateGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val params = ZamletParams.fromFile(args(0))
    new JteState(params)
  }
}

object JteStateMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  JteStateGenerator.generate(args(0), Seq(args(1)))
}
