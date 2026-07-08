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
  val walkIsActive = Bool()
  val walkIsRequired = Bool()
}

class JteStateErrors extends Bundle {
  val createTeIndexInUse = Bool()
  val teIndexToRegInvalid = Bool()
  val receiverUpdateInvalid = Bool()
  val initiatorCommitInvalid = Bool()
  val tlbAvailableInvalid = Bool()
  val tlbAvailableUnexpectedState = Bool()
  val tlbAvailableReceiverConflict = Bool()
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
  val tlbAvailable = Flipped(Valid(new JamletTlbAvailable(params)))

  val receiverUpdate = Flipped(Decoupled(new JteReceiverUpdateMsg(params)))
  val teIndexToRegReq = Flipped(Decoupled(UInt(log2Ceil(params.witemTableDepth).W)))
  val teIndexToRegResp = Decoupled(params.rfAddr())

  val transferComplete = Output(Vec(params.witemTableDepth, Bool()))
  val errors = Output(new JteStateErrors())
}

class JteState(params: ZamletParams) extends Module {
  val io = IO(new JteStateIO(params))
  val sp = params.jteStateParams

  // Slot state is updated through a combinational pipeline so same-cycle
  // events have explicit ordering.
  val slotsInitial = VecInit(Seq.fill(params.witemTableDepth)(0.U.asTypeOf(new JteStateSlot(params))))
  val slotsNext = Wire(Vec(params.witemTableDepth, new JteStateSlot(params)))
  val slots = RegEnable(slotsNext, slotsInitial, true.B)
  val slotsPostDispatch = Wire(Vec(params.witemTableDepth, new JteStateSlot(params)))
  val slotsPostReceiver = Wire(Vec(params.witemTableDepth, new JteStateSlot(params)))
  val slotsPostCommit = Wire(Vec(params.witemTableDepth, new JteStateSlot(params)))
  val slotsPostAvailable = Wire(Vec(params.witemTableDepth, new JteStateSlot(params)))
  slotsNext := slotsPostAvailable

  val errors = Wire(new JteStateErrors())
  errors := 0.U.asTypeOf(new JteStateErrors())

  // Buffered external interfaces.
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
  val tlbAvailable = io.tlbAvailable

  // Interface defaults.
  inputReq.valid := false.B
  inputReq.bits := 0.U
  inputResp.ready := false.B
  initiatorDispatch.valid := false.B
  initiatorDispatch.bits := 0.U.asTypeOf(new JteInitiatorInput(params))
  receiverUpdate.ready := false.B
  teIndexToRegReq.ready := false.B
  teIndexToRegResp.valid := false.B
  teIndexToRegResp.bits := 0.U

  // Error wires describe input events that do not match the currently tracked
  // slot state. They are reported but do not add backpressure.
  errors.createTeIndexInUse := create.valid && slots(create.bits.teIndex).valid
  errors.teIndexToRegInvalid := teIndexToRegReq.valid && !slots(teIndexToRegReq.bits).valid

  // Always-consumable update/status ports.
  teIndexToRegReq.ready := teIndexToRegResp.ready
  teIndexToRegResp.valid := teIndexToRegReq.valid
  teIndexToRegResp.bits := slots(teIndexToRegReq.bits).dataReg
  receiverUpdate.ready := true.B

  def slotAllBytesComplete(slot: JteStateSlot): Bool = {
    slot.initiator.map(_ === JteInitiatorState.Complete).reduce(_ && _)
  }

  def initiatorHasEligibleByte(initiator: Vec[JteInitiatorState.Type]): Bool = {
    initiator
      .map(state => state === JteInitiatorState.Initial || state === JteInitiatorState.Dropped)
      .reduce(_ || _)
  }

  def slotHasEligibleByte(slot: JteStateSlot): Bool = {
    initiatorHasEligibleByte(slot.initiator)
  }

  def initiatorForRetryWalk(initiator: Vec[JteInitiatorState.Type]): Vec[JteInitiatorState.Type] = {
    val result = Wire(Vec(params.wordBytes, JteInitiatorState()))
    for (i <- 0 until params.wordBytes) {
      result(i) := Mux(initiator(i) === JteInitiatorState.Dropped, JteInitiatorState.Initial, initiator(i))
    }
    result
  }

  // Dispatch A: select a transfer-engine entry that needs another initiator walk.
  val dispatchACandidates = VecInit((0 until params.witemTableDepth).map { i =>
    slots(i).valid && slots(i).walkIsRequired && !slots(i).walkIsActive && slotHasEligibleByte(slots(i))
  })
  val dispatchAValid = dispatchACandidates.reduce(_ || _)
  val dispatchASlot = PriorityEncoder(dispatchACandidates)
  val dispatchAB = Wire(Decoupled(new JteStateDispatchAB(params)))
  dispatchAB.valid := dispatchAValid
  dispatchAB.bits.teIndex := dispatchASlot
  slotsPostDispatch := slots
  when (dispatchAB.fire) {
    slotsPostDispatch(dispatchASlot).walkIsActive := true.B
    slotsPostDispatch(dispatchASlot).walkIsRequired := false.B
    // A retry walk consumes Dropped bytes from the previous pass. If they stay
    // Dropped while this walk is active, the slot remains eligible and can
    // dispatch duplicate requests before the new responses return.
    slotsPostDispatch(dispatchASlot).initiator := initiatorForRetryWalk(slots(dispatchASlot).initiator)
  }

  // Dispatch B: request the full initiator input from the Kamlet core.
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
  initiatorDispatch.bits.initiator := slotsPostDispatch(dispatchBCBuffered.bits.teIndex).initiator
  dispatchBCBuffered.ready := inputResp.valid && initiatorDispatch.ready

  // State update A: receiver responses complete or retry individual bytes.
  slotsPostReceiver := slotsPostDispatch
  when (receiverUpdate.valid) {
    when (!slots(receiverUpdate.bits.teIndex).valid) {
      errors.receiverUpdateInvalid := true.B
    } .otherwise {
      when (receiverUpdate.fire) {
        when (receiverUpdate.bits.drop) {
          slotsPostReceiver(receiverUpdate.bits.teIndex).initiator(receiverUpdate.bits.offset) := JteInitiatorState.Dropped
          slotsPostReceiver(receiverUpdate.bits.teIndex).walkIsRequired := true.B
        } .otherwise {
          slotsPostReceiver(receiverUpdate.bits.teIndex).initiator(receiverUpdate.bits.offset) := JteInitiatorState.Complete
        }
      }
    }
  }

  // State update B: initiator commits the result of one address-walk pass.
  // Existing complete/retry/waiting bytes are preserved over new commit data.
  slotsPostCommit := slotsPostReceiver
  when (initiatorCommit.valid) {
    when (!slots(initiatorCommit.bits.teIndex).valid) {
      errors.initiatorCommitInvalid := true.B
    } .otherwise {
      val commitHasWaitingForTlb = initiatorCommit.bits.initiator
        .map(_ === JteInitiatorState.WaitingForTlb)
        .reduce(_ || _)
      val commitMergedInitiator = Wire(Vec(params.wordBytes, JteInitiatorState()))
      for (i <- 0 until params.wordBytes) {
        when (
          slotsPostReceiver(initiatorCommit.bits.teIndex).initiator(i) === JteInitiatorState.Complete ||
          slotsPostReceiver(initiatorCommit.bits.teIndex).initiator(i) === JteInitiatorState.Dropped ||
          slotsPostReceiver(initiatorCommit.bits.teIndex).initiator(i) === JteInitiatorState.RequestSent ||
          slotsPostReceiver(initiatorCommit.bits.teIndex).initiator(i) === JteInitiatorState.WaitingForTlb
        ) {
          commitMergedInitiator(i) := slotsPostReceiver(initiatorCommit.bits.teIndex).initiator(i)
        } .elsewhen (
          slotsPostReceiver(initiatorCommit.bits.teIndex).initiator(i) === JteInitiatorState.EarlyTlbAvailable &&
          initiatorCommit.bits.initiator(i) === JteInitiatorState.WaitingForTlb
        ) {
          commitMergedInitiator(i) := JteInitiatorState.Dropped
        } .otherwise {
          commitMergedInitiator(i) := initiatorCommit.bits.initiator(i)
        }
      }
      slotsPostCommit(initiatorCommit.bits.teIndex).initiator := commitMergedInitiator
      slotsPostCommit(initiatorCommit.bits.teIndex).walkIsActive := false.B
      slotsPostCommit(initiatorCommit.bits.teIndex).walkIsRequired := initiatorHasEligibleByte(commitMergedInitiator)
      when (
        commitHasWaitingForTlb &&
        !commitMergedInitiator.map(_ === JteInitiatorState.WaitingForTlb).reduce(_ || _)
      ) {
        slotsPostCommit(initiatorCommit.bits.teIndex).walkIsRequired := true.B
      }
    }
  }

  // State update C: TLB availability wakes a soft-dropped byte. If the wake
  // beats the soft-drop commit, remember that with EarlyTlbAvailable.
  slotsPostAvailable := slotsPostCommit
  when (tlbAvailable.valid) {
    when (!slots(tlbAvailable.bits.teIndex).valid) {
      errors.tlbAvailableInvalid := true.B
    } .otherwise {
      val expectedState =
        slots(tlbAvailable.bits.teIndex).initiator(tlbAvailable.bits.byteIndex) === JteInitiatorState.WaitingForTlb ||
        slots(tlbAvailable.bits.teIndex).initiator(tlbAvailable.bits.byteIndex) === JteInitiatorState.Initial ||
        slots(tlbAvailable.bits.teIndex).initiator(tlbAvailable.bits.byteIndex) === JteInitiatorState.Dropped
      errors.tlbAvailableUnexpectedState := !expectedState
      errors.tlbAvailableReceiverConflict := receiverUpdate.valid &&
        tlbAvailable.bits.teIndex === receiverUpdate.bits.teIndex &&
        tlbAvailable.bits.byteIndex === receiverUpdate.bits.offset
      when (
        slotsPostCommit(tlbAvailable.bits.teIndex).valid &&
        slotsPostCommit(tlbAvailable.bits.teIndex).initiator(tlbAvailable.bits.byteIndex) === JteInitiatorState.WaitingForTlb
      ) {
        slotsPostAvailable(tlbAvailable.bits.teIndex).initiator(tlbAvailable.bits.byteIndex) := JteInitiatorState.Dropped
        slotsPostAvailable(tlbAvailable.bits.teIndex).walkIsRequired := true.B
      } .elsewhen (slotsPostCommit(tlbAvailable.bits.teIndex).valid) {
        slotsPostAvailable(tlbAvailable.bits.teIndex).initiator(tlbAvailable.bits.byteIndex) := JteInitiatorState.EarlyTlbAvailable
      }
    }
  }

  // Allocation and release of table slots.
  when (create.valid) {
    val teIndex = create.bits.teIndex
    slotsNext(teIndex).valid := true.B
    slotsNext(teIndex).completeSent := false.B
    slotsNext(teIndex).instrIdent := create.bits.instrIdent
    slotsNext(teIndex).dataReg := create.bits.dataReg
    slotsNext(teIndex).walkIsActive := false.B
    slotsNext(teIndex).walkIsRequired := true.B
    for (i <- 0 until params.wordBytes) {
      slotsNext(teIndex).initiator(i) := JteInitiatorState.Initial
    }
  }

  when (clear.valid) {
    slotsNext(clear.bits).valid := false.B
  }

  // Report each completed transfer-engine entry once.
  for (i <- 0 until params.witemTableDepth) {
    val complete = slots(i).valid &&
      !slots(i).walkIsActive &&
      !slots(i).walkIsRequired &&
      slotAllBytesComplete(slots(i))
    io.transferComplete(i) := complete && !slots(i).completeSent
    when (complete) {
      slotsNext(i).completeSent := true.B
    }
  }

  io.errors := RegNext(errors)
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
