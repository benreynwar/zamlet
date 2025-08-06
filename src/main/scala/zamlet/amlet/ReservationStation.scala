package zamlet.amlet

import chisel3._
import chisel3.util._

abstract class ReservationStation[U <: Instr.Resolving, R <: Instr.Resolved]
    (params: AmletParams, Resolving: U, Resolved: R) extends Module {

  def nSlots(): Int
  def readyToIssue(allResolving: Vec[U], index: UInt): Bool
  def emptySlot(): U

  val io = IO(new Bundle {
    // Input instruction from RegisterFileAndFriends
    val input = Flipped(Decoupled(Resolving))
    
    // Output to Execution Unit when instruction is ready
    val output = Decoupled(Resolved)
    
    // Results from execution units for dependency resolution
    val resultBus = Input(new ResultBus(params))
  })

  // The reservation stores several instructions.
  // They are stored here until all the values that they depend on have been
  // written.  Then they are issued to the Execution Unit.

  val slotsNext = Wire(Vec(nSlots(), Resolving))
  val slots = RegNext(slotsNext, VecInit(
    Seq.fill(nSlots())
    (emptySlot())))

  // What the value of 'slots' will be half way through the
  // combinatorial logic for updating them.
  val slotsIntermed = Wire(Vec(nSlots(), Resolving))

  // How many of the 'slots' will be getting used next cycle.
  val nUsedSlotsNext = Wire(UInt(log2Ceil(nSlots()+1).W))
  // How many of the 'slots are getting used this cycle.
  val nUsedSlots = RegNext(nUsedSlotsNext, 0.U)

  val issueValidNext = Wire(Bool())
  val issueValid = RegNext(issueValidNext, false.B)
  val issueSlotIndexNext = Wire(UInt(log2Ceil(nSlots()).W))
  val issueSlotIndex = RegNext(issueSlotIndexNext)

  val removeValid = Wire(Bool())
  removeValid := issueValid && io.output.ready

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
    when (io.input.fire && (i+1).U === nUsedSlotsNext) {
      slotsIntermed(i) := io.input.bits
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
    slotsNext(i) := slotsIntermed(i).update(io.resultBus)
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
  val inputReadyNext = Wire(Bool())
  val inputReady = RegNext(inputReadyNext, true.B)

  nUsedSlotsNext := nUsedSlots
  inputReadyNext := inputReady
  when (removeValid && io.input.fire) {
    // We receive an instruction and we issue one
  } .elsewhen (removeValid) {
    // We issued but didn't receive
    nUsedSlotsNext := nUsedSlots - 1.U
    inputReadyNext := true.B
  } .elsewhen (io.input.fire) {
    // We received but didn't issue
    nUsedSlotsNext := nUsedSlots + 1.U
    when (nUsedSlots === (nSlots()-1).U) {
      inputReadyNext := false.B
    }
  }
  io.input.ready := inputReady
  
  io.output.valid := removeValid
  val issueSlot = slots(issueSlotIndex)
  io.output.bits := issueSlot.resolve()

}
