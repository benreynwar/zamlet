package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer
import zamlet.utils.ValidBuffer

class JteCreate(params: ZamletParams) extends Bundle {
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
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
  val createTeIndexInUse = Bool()
  val teIndexToRegInvalid = Bool()
  val receiverUpdateInvalid = Bool()
  val receiverUpdateIdentMismatch = Bool()
  val initiatorCommitInvalid = Bool()
}

class JteStateDispatchAB(params: ZamletParams) extends Bundle {
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
}

class JteStateDispatchBC(params: ZamletParams) extends Bundle {
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
}

class JteStateIO(params: ZamletParams) extends Bundle {
  val create = Flipped(Valid(new JteCreate(params)))
  val clear = Flipped(Valid(UInt(log2Ceil(params.witemTableDepth).W)))

  val inputReq = Decoupled(UInt(log2Ceil(params.witemTableDepth).W))
  val inputResp = Flipped(Decoupled(new JteInitiatorInput(params)))
  val initiatorDispatch = Decoupled(new JteInitiatorInput(params))
  val initiatorCommit = Flipped(Valid(new JteInitiatorCommit(params)))

  val receiverUpdate = Flipped(Decoupled(new JteReceiverUpdateMsg(params)))
  val teIndexToRegReq = Flipped(Decoupled(UInt(log2Ceil(params.witemTableDepth).W)))
  val teIndexToRegResp = Decoupled(params.rfAddr())

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
  val teIndexToRegReq = DoubleBuffer(io.teIndexToRegReq, sp.slotToRegReqFB, sp.slotToRegReqBB)
  val teIndexToRegResp = Wire(Decoupled(params.rfAddr()))
  io.teIndexToRegResp <> DoubleBuffer(teIndexToRegResp, sp.slotToRegRespFB, sp.slotToRegRespBB)
  val create = ValidBuffer(io.create, sp.createBuffer)
  val clear = ValidBuffer(io.clear, sp.clearBuffer)
  val initiatorCommit = ValidBuffer(io.initiatorCommit, sp.initiatorCommitBuffer)

  inputReq.valid := false.B
  inputReq.bits := 0.U
  inputResp.ready := false.B
  initiatorDispatch.valid := false.B
  initiatorDispatch.bits := 0.U.asTypeOf(new JteInitiatorInput(params))
  receiverUpdate.ready := false.B
  teIndexToRegReq.ready := false.B
  teIndexToRegResp.valid := false.B
  teIndexToRegResp.bits := 0.U
  io.errors.createTeIndexInUse := create.valid && slots(create.bits.teIndex).valid
  io.errors.teIndexToRegInvalid := teIndexToRegReq.valid && !slots(teIndexToRegReq.bits).valid
  io.errors.receiverUpdateInvalid := receiverUpdate.valid && !slots(receiverUpdate.bits.teIndex).valid
  io.errors.receiverUpdateIdentMismatch := receiverUpdate.valid &&
    slots(receiverUpdate.bits.teIndex).valid &&
    slots(receiverUpdate.bits.teIndex).instrIdent =/= receiverUpdate.bits.ident
  io.errors.initiatorCommitInvalid := initiatorCommit.valid && !slots(initiatorCommit.bits.teIndex).valid

  teIndexToRegReq.ready := teIndexToRegResp.ready
  teIndexToRegResp.valid := teIndexToRegReq.valid
  teIndexToRegResp.bits := slots(teIndexToRegReq.bits).dataReg
  receiverUpdate.ready := true.B

  // Dispatch A: select a transfer-engine entry that needs another initiator walk.
  val dispatchACandidates = VecInit((0 until params.witemTableDepth).map { i =>
    slots(i).valid && slots(i).walkState === JteWalkState.NeedsProcessing
  })
  val dispatchAValid = dispatchACandidates.reduce(_ || _)
  val dispatchASlot = PriorityEncoder(dispatchACandidates)
  val dispatchAB = Wire(Decoupled(new JteStateDispatchAB(params)))
  dispatchAB.valid := dispatchAValid
  dispatchAB.bits.teIndex := dispatchASlot
  when (dispatchAB.fire) {
    slotsNext(dispatchASlot).walkState := JteWalkState.InProgress
  }

  // Dispatch B: request the full initiator input from the kamlet core.
  val dispatchABBuffered = DoubleBuffer(dispatchAB, sp.dispatchABFB, sp.dispatchABBB)
  val dispatchBC = Wire(Decoupled(new JteStateDispatchBC(params)))
  inputReq.valid := dispatchABBuffered.valid && dispatchBC.ready
  inputReq.bits := dispatchABBuffered.bits.teIndex
  dispatchBC.valid := dispatchABBuffered.valid && inputReq.ready
  dispatchBC.bits.teIndex := dispatchABBuffered.bits.teIndex
  dispatchABBuffered.ready := inputReq.ready && dispatchBC.ready

  // Dispatch C: wait for the full input and dispatch it to the initiator.
  val dispatchBCBuffered = DoubleBuffer(dispatchBC, sp.dispatchBCFB, sp.dispatchBCBB)
  inputResp.ready := dispatchBCBuffered.valid && initiatorDispatch.ready
  initiatorDispatch.valid := dispatchBCBuffered.valid && inputResp.valid
  initiatorDispatch.bits := inputResp.bits
  initiatorDispatch.bits.teIndex := dispatchBCBuffered.bits.teIndex
  dispatchBCBuffered.ready := inputResp.valid && initiatorDispatch.ready

  when (receiverUpdate.fire) {
    val teIndex = receiverUpdate.bits.teIndex
    val offset = receiverUpdate.bits.offset
    when (receiverUpdate.bits.drop) {
      slotsNext(teIndex).initiator(offset) := JteInitiatorState.Dropped
      slotsNext(teIndex).walkState := JteWalkState.NeedsProcessing
    } .otherwise {
      slotsNext(teIndex).initiator(offset) := JteInitiatorState.Complete
    }
  }

  when (initiatorCommit.valid) {
    val teIndex = initiatorCommit.bits.teIndex
    for (i <- 0 until params.wordBytes) {
      val current = slots(teIndex).initiator(i)
      when (current === JteInitiatorState.Complete || current === JteInitiatorState.Dropped) {
        slotsNext(teIndex).initiator(i) := current
      } .otherwise {
        slotsNext(teIndex).initiator(i) := initiatorCommit.bits.initiator(i)
      }
    }
    when (slots(teIndex).walkState =/= JteWalkState.NeedsProcessing) {
      slotsNext(teIndex).walkState := initiatorCommit.bits.walkState
    }
  }

  when (create.valid) {
    val teIndex = create.bits.teIndex
    slotsNext(teIndex).valid := true.B
    slotsNext(teIndex).completeSent := false.B
    slotsNext(teIndex).instrIdent := create.bits.instrIdent
    slotsNext(teIndex).dataReg := create.bits.dataReg
    slotsNext(teIndex).walkState := JteWalkState.NeedsProcessing
    for (i <- 0 until params.wordBytes) {
      slotsNext(teIndex).initiator(i) := JteInitiatorState.Initial
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
