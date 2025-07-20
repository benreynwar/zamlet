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
  val slots = RegInit(VecInit(
    Seq.fill(nSlots())
    (0.U.asTypeOf(Valid(Resolving)))))

  val nUsedSlotsNext = Wire(UInt(log2Ceil(nSlots()+1).W))
  val nUsedSlots = RegNext(nUsedSlotsNext, 0.U)

  // The oldest instruction that is resolved gets sent to the Execution Unit.

  // First step is to update the slots.
  val update1Slots = Wire(Vec(nSlots(), Valid(Resolving)))

  // Is an instruction being removed, this can be due to being issued or being masked.
  val removeValidNext = Wire(Bool())
  val removeValid = RegNext(removeValidNext, false.B)
  val removeSlotIndexNext = Wire(UInt(log2Ceil(nSlots()).W))
  val removeSlotIndex = RegNext(removeSlotIndexNext)

  for (i <- 0 until nSlots()) {
    update1Slots(i) := slots(i)
    when (removeValid && i.U >= removeSlotIndex && i.U < nUsedSlots - 1.U) {
      // Bounds check: ensure i+1 doesn't exceed array bounds when shifting slots left
      // This shouldn't be necessary given the loop bounds, but seems to be required
      if (i+1 < nSlots()) {
        update1Slots(i) := slots(i+1)
      }
    } .elsewhen (io.input.fire && i.U === nUsedSlots) {
      update1Slots(i).valid := true.B
      update1Slots(i).bits := io.input.bits
    } .elsewhen (i.U >= nUsedSlots) {
      update1Slots(i).valid := false.B
      update1Slots(i).bits := DontCare
    }
  }

  // Now update them with the effect of the write backs.
  val update2Slots = Wire(Vec(nSlots(), Valid(Resolving)))
  for (i <- 0 until nSlots()) {
    update2Slots(i).valid := update1Slots(i).valid
    update2Slots(i).bits := update1Slots(i).bits.update(io.writeBacks)
  }


  // Find out which slots have all their dependencies resolved.
  val resolvedSlots = update2Slots.zipWithIndex.map { case (slot, index) => 
    index.U < nUsedSlotsNext && 
    slot.bits.isResolved() &&
    !slot.bits.isMasked()
  }
  resolvedSlots.foreach(dontTouch(_))

  // Which slots have masked instructions
  val maskedSlots = update2Slots.zipWithIndex.map { case (slot, index) => 
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
  issueValidNext := resolvedSlots.reduce(_ || _)
  issueSlotIndexNext := PriorityEncoder(resolvedSlots)

  val maskValidNext = Wire(Bool())
  val maskSlotIndexNext = Wire(UInt(log2Ceil(nSlots()).W))
  maskValidNext := maskedSlots.reduce(_ || _)
  maskSlotIndexNext := PriorityEncoder(maskedSlots)

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
  when (removeValidNext && io.input.fire) {
    // We receive an instruction and we issue one
  } .elsewhen (removeValidNext) {
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
