package fmvpu.amlet

import chisel3._
import chisel3.util._

abstract class ReservationStation[U <: Instr.Resolving, R <: Instr.Resolved]
    (params: AmletParams, Resolving: U, Resolved: R) extends Module {

  def nSlots(): Int

  val io = IO(new Bundle {
    // Input instruction from RegisterFileAndFriends
    val input = Flipped(Decoupled(Resolving))
    
    // Output to Execution Unit when instruction is ready
    val output = Valid(Resolved)
    
    // Write results from execution units for dependency resolution
    val writeBacks = Input(new WriteBacks(params))
  })

  // The reservation stores several instructions.
  // They are stored here until all the values that they depend on have been
  // written.  Then they are issued to the Execution Unit.

  // FIXME: The slots don't have to be initialized all to 0.
  // The valid needs to be 0, but the rest should be DontCare
  val slotsNext = Wire(Vec(nSlots(), Valid(Resolving)))
  val slots = RegNext(slotsNext, VecInit(
    Seq.fill(nSlots())
    (0.U.asTypeOf(Valid(Resolving)))))

  // What the value of 'slots' will be half way through the
  // combinatorial logic for updating them.
  val slotsIntermed = Wire(Vec(nSlots(), Valid(Resolving)))

  // How many of the 'slots' will be getting used next cycle.
  val nUsedSlotsNext = Wire(UInt(log2Ceil(nSlots()+1).W))
  // How many of the 'slots are getting used this cycle.
  val nUsedSlots = RegNext(nUsedSlotsNext, 0.U)

  // Is an instruction being removed, this can be due to being issued or being masked.
  val removeValidNext = Wire(Bool())
  val removeValid = RegNext(removeValidNext, false.B)
  // What slot index are we removing it from.
  val removeSlotIndexNext = Wire(UInt(log2Ceil(nSlots()).W))
  val removeSlotIndex = RegNext(removeSlotIndexNext)

  for (i <- 0 until nSlots()) {
    slotsIntermed(i) := slots(i)
    // We breaking out belowRemoved here so that the condition make sense
    // for all values of i and doesn't result in warnings.
    val belowRemoved = Wire(Bool())
    if (i == nSlots()-1) {
      belowRemoved := false.B
    } else {
      belowRemoved := removeValid && i.U < removeSlotIndex
    }
    when (belowRemoved) {
      // Bounds check: ensure i+1 doesn't exceed array bounds when shifting slots left
      // The condition shouldn't ever be false, but this resolves it before we
      // generate the verilog so we don't have to trust tools to realize that.
      if (i+1 < nSlots()) {
        slotsIntermed(i) := slots(i+1)
      }
    } .elsewhen (io.input.fire && i.U === nUsedSlots) {
      slotsIntermed(i).valid := true.B
      slotsIntermed(i).bits := io.input.bits
    } .elsewhen (i.U >= nUsedSlots) {
      slotsIntermed(i).valid := false.B
      slotsIntermed(i).bits := DontCare
    }
  }

  // Now update them with the effect of the write backs.
  for (i <- 0 until nSlots()) {
    slotsNext(i).valid := slotsIntermed(i).valid
    slotsNext(i).bits := slotsIntermed(i).bits.update(io.writeBacks)
  }


  // Find out which slots will have dependencies resolved next cycle.
  // i.e. slotsNext has resolved dependencies
  //      and 'slots' will have resolved dependencies next cycle.
  val resolvedSlotsNext = slotsNext.zipWithIndex.map { case (slot, index) => 
    index.U < nUsedSlotsNext && 
    slot.bits.isResolved() &&
    !slot.bits.isMasked()
  }
  resolvedSlotsNext.foreach(dontTouch(_))

  // Which slots have masked instructions
  val maskedSlotsNext = slotsNext.zipWithIndex.map { case (slot, index) => 
    index.U < nUsedSlotsNext && 
    slot.bits.isMasked()
  }

  // Is an instruction being issued.
  // This depends on if a slot is fully resolved.
  val issueValidNext = Wire(Bool())
  val issueValid = RegNext(issueValidNext, false.B)

  val issueSlotIndexNext = Wire(UInt(log2Ceil(nSlots()).W))
  val issueSlotIndex = RegNext(issueSlotIndexNext)


  // The first resolved slot is the one we will emit next cycle
  issueValidNext := resolvedSlotsNext.reduce(_ || _)
  issueSlotIndexNext := PriorityEncoder(resolvedSlotsNext)

  // The first masked slot is the one we will delete next cycle
  // (if we aren't issueing)
  val maskValidNext = Wire(Bool())
  val maskSlotIndexNext = Wire(UInt(log2Ceil(nSlots()).W))
  maskValidNext := maskedSlotsNext.reduce(_ || _)
  maskSlotIndexNext := PriorityEncoder(maskedSlotsNext)

  removeValidNext := issueValidNext || maskValidNext
  when (issueValidNext) {
    removeSlotIndexNext := issueSlotIndexNext
  } .otherwise {
    removeSlotIndexNext := maskSlotIndexNext
  }

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
  
  io.output.valid := issueValid
  val issueSlot = slots(issueSlotIndex).bits
  io.output.bits := issueSlot.resolve()

}
