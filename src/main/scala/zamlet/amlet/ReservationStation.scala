package zamlet.amlet

import chisel3._
import chisel3.util._
import zamlet.utils.{DoubleBuffer, RegBuffer, ValidBuffer, ResetStage}

class ReservationStationErrors extends Bundle {
  val noFreeSlots = Bool()
}

abstract class ReservationStation[U <: Instr.Resolving, R <: Instr.Resolved]
    (params: AmletParams, rsParams: ReservationStationParams, Resolving: U, Resolved: R) extends Module {

  def nSlots(): Int = rsParams.nSlots
  def readyToIssue(allResolving: Vec[U], index: UInt): Bool
  def emptySlot(): U

  val io = IO(new Bundle {
    // Input instruction from RegisterFileAndFriends
    val input = Flipped(Decoupled(Resolving))
    
    // Output to Execution Unit when instruction is ready
    val output = Decoupled(Resolved)
    
    // Results from execution units for dependency resolution
    val resultBus = Input(new ResultBus(params))
    
    // Error outputs
    val error = Output(new ReservationStationErrors)
  })

  val resetBuffered = ResetStage(clock, reset)

  // Add input buffer using ValidBuffer
    val iFire = Wire(Valid(chiselTypeOf(io.input.bits)))
    iFire.valid := io.input.valid && io.input.ready
    iFire.bits := io.input.bits
    val aInput = ValidBuffer(iFire, rsParams.iaBuffer)
    
    // Buffer the resultBus using RegBuffer
    val aResultBus = RegBuffer(io.resultBus, rsParams.iaBuffer)

    // Internal output before buffering
    val internalOutput = Wire(Decoupled(Resolved))

    // The reservation stores several instructions.
    // They are stored here until all the values that they depend on have been
    // written.  Then they are issued to the Execution Unit.

    val slotsNext = Wire(Vec(nSlots(), Resolving))
    val slots = Wire(Vec(nSlots(), Resolving))

    // What the value of 'slots' will be half way through the
    // combinatorial logic for updating them.
    val slotsIntermed = Wire(Vec(nSlots(), Resolving))

    // How many of the 'slots' will be getting used next cycle.
    val nUsedSlotsNext = Wire(UInt(log2Ceil(nSlots()+1).W))
    // How many of the 'slots are getting used this cycle.
    val nUsedSlots = Wire(UInt(log2Ceil(nSlots()+1).W))

    val issueValidNext = Wire(Bool())
    val issueValid = Wire(Bool())
    val issueSlotIndexNext = Wire(UInt(log2Ceil(nSlots()).W))
    val issueSlotIndex = Wire(UInt(log2Ceil(nSlots()).W))

    // Declare wire variables that will be assigned from registers
    val inputReadyNext = Wire(Bool())
    val inputReady = Wire(Bool())

    withReset(resetBuffered) {
      slots := RegNext(slotsNext, VecInit(Seq.fill(nSlots())(emptySlot())))
      nUsedSlots := RegNext(nUsedSlotsNext, 0.U)
      issueValid := RegNext(issueValidNext, false.B)
      issueSlotIndex := RegNext(issueSlotIndexNext)
      inputReady := RegNext(inputReadyNext, true.B)
    }

    val removeValid = Wire(Bool())
    removeValid := issueValid && internalOutput.ready

    for (i <- 0 until nSlots()) {
      slotsIntermed(i) := slots(i)
      // We breaking out belowRemoved here so that the condition make sense
      // for all values of i and doesn't result in warnings.
      val belowRemoved = Wire(Bool())
      if (i == nSlots()-1) {
        belowRemoved := false.B
      } else {
        belowRemoved := (!removeValid) || i.U < issueSlotIndex
      }
      when (aInput.valid && (i+1).U === nUsedSlotsNext) {
        slotsIntermed(i) := aInput.bits
      } .elsewhen (belowRemoved) {
        slotsIntermed(i) := slots(i)
      } .elsewhen (i.U < nUsedSlots) {
        // Bounds check: ensure i+1 doesn't exceed array bounds when shifting slots left
        // The condition shouldn't ever be false, but this resolves it before we
        // generate the verilog so we don't have to trust tools to realize that.
        if (i+1 < nSlots()) {
          slotsIntermed(i) := slots(i+1)
        }
      } .elsewhen (i.U >= nUsedSlots) {
        slotsIntermed(i) := emptySlot()
      }
    }

    // Now update them with the effect of the write backs.
    for (i <- 0 until nSlots()) {
      slotsNext(i) := slotsIntermed(i).update(aResultBus)
    }


    // Find out which slots will have dependencies resolved next cycle.
    // i.e. slotsNext has resolved dependencies
    //      and 'slots' will have resolved dependencies next cycle.
    val resolvedSlotsNext = slotsNext.zipWithIndex.map { case (slot, index) => 
      index.U < nUsedSlotsNext && 
      readyToIssue(slotsNext, index.U)
    }
    resolvedSlotsNext.foreach(dontTouch(_))

    // Assign the issue signals
    issueValidNext := resolvedSlotsNext.reduce((a: Bool, b: Bool) => a || b)
    issueSlotIndexNext := PriorityEncoder(resolvedSlotsNext)

    // Update our count of the number of instructions in the RS
    // Set input.ready high if there is a spare slot.

    // Determine ready threshold based on iaBuffer setting
    val readyThreshold = if (rsParams.iaBuffer) (nSlots() - 2).U else (nSlots() - 1).U

    // Error check: if aInput.valid, there should always be at least one free slot
    val errorNoFreeSlots = Wire(Bool())
    errorNoFreeSlots := aInput.valid && (nUsedSlots >= nSlots().U)
    
    withReset(resetBuffered) {
      io.error.noFreeSlots := RegNext(errorNoFreeSlots, false.B)
    }
    

    nUsedSlotsNext := nUsedSlots
    inputReadyNext := inputReady
    when (removeValid && aInput.valid) {
      // We receive an instruction and we issue one
    } .elsewhen (removeValid) {
      // We issued but didn't receive
      nUsedSlotsNext := nUsedSlots - 1.U
      inputReadyNext := true.B
    } .elsewhen (aInput.valid) {
      // We received but didn't issue
      nUsedSlotsNext := nUsedSlots + 1.U
      when (nUsedSlots >= readyThreshold) {
        inputReadyNext := false.B
      }
    }
    io.input.ready := inputReady
    
    internalOutput.valid := removeValid
    val issueSlot = slots(issueSlotIndex)
    internalOutput.bits := issueSlot.resolve()

    // Add DoubleBuffer at output with individual enable parameters
    val outputBuffer = Module(new DoubleBuffer(chiselTypeOf(internalOutput.bits), rsParams.boForwardBuffer, rsParams.boBackwardBuffer))
    outputBuffer.io.i <> internalOutput
    io.output <> outputBuffer.io.o
}
