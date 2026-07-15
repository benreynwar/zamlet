package zamlet.jamlet

import chisel3._
import chisel3.util._

class JamletMxuCellIO extends Bundle {
  // Input of A
  val aA = Input(UInt(8.W))
  // Output of A
  val bA = Output(UInt(8.W))
  // Input of B
  val aB = Input(UInt(8.W))
  // Output of B
  val bB = Output(UInt(8.W))

  // Input valid signal
  val aValid = Input(Bool())
  // Output valid signal
  val bValid = Output(Bool())
  // Input final signal (indicates that this A and B value complete the sum
  //                     we are accumulating)
  val aFinal = Input(Bool())
  // Output final signal
  val bFinal = Output(Bool())

  // The shiftbuffer interface that we use to stream the sum out.
  val dShiftData = Input(UInt(16.W))
  val dValid = Input(Bool())
  val eShiftData = Output(UInt(16.W))
  val eValid = Output(Bool())

  val error = Output(Bool())
}

class JamletMxuCell(bcBuffer: Boolean = false) extends Module {
  val io = IO(new JamletMxuCellIO)

  val bValid = RegNext(io.aValid, false.B)
  val bFinal = RegNext(io.aFinal, false.B)
  val bA = RegEnable(io.aA, io.aValid)
  val bB = RegEnable(io.aB, io.aValid)

  val bAB = (bA.asSInt * bB.asSInt).asUInt
  val bABExtended = Cat(Fill(16, bAB(15)), bAB)
  val cAB = if (bcBuffer) RegEnable(bABExtended, bValid) else bABExtended
  val cValid = if (bcBuffer) RegNext(bValid, false.B) else bValid
  val cFinal = if (bcBuffer) RegNext(bFinal, false.B) else bFinal
  val dFinal = RegNext(cFinal, false.B)
  val eFinal = RegNext(dFinal, false.B)

  // Because the output shift-register is only 16-bit wides and our accumulator is
  // 32 bit wide we take two cycles to move the sum into the shift register.
  // cFinal is the final-product cycle.
  //
  // On dFinal, the lower half of dC moves into the shift-data register.
  // On eFinal, the upper half of dC moves into the shift-data register.


  // Stage C computes the value loaded into the C-to-D accumulator register.
  // dC is the output of that register.
  val dCNext = Wire(UInt(32.W))
  // We need to update this register when either cValid is high (active new value from multiplier)
  // or dFinal or eFinal are high (we need to set the value to 0 if cValid is low since we are
  // emptying it).
  val dC = RegEnable(dCNext, 0.U(32.W), cValid || dFinal || eFinal)

  // Choose the accumulator base before adding cAB. dFinal is the first result
  // extraction cycle; eFinal is the second result extraction cycle, where dC
  // contains the old upper half and the new lower half.
  val cCBase = Wire(UInt(32.W))
  cCBase := dC
  when (dFinal) {
    // We just completed the sum last cycle so the new accumluator base is 0.
    cCBase := 0.U
  } .elsewhen (eFinal) {
    // The lower bits were updated last cycle, but the upper bits are still the
    // result being shifted out this cycle.
    cCBase := Cat(Fill(16, dC(15)), dC(15, 0))
  }

  // Add on the result from the multiplier when it is active.
  val cC = Wire(UInt(32.W))
  cC := cCBase
  when (cValid) {
    cC := (cCBase + cAB)(31, 0)
  }

  // dFinal moves the lower half into the shift-data register and keeps the
  // upper half in dC for the next cycle. eFinal moves that upper half into the
  // shift-data register and restores dC to the new accumulator value.
  dCNext := dC
  when (dFinal) {
    dCNext := Cat(dC(31, 16), cC(15, 0))
  } .elsewhen (cValid || dFinal || eFinal) {
    dCNext := cC
  }

  val dShiftChosen = Wire(UInt(16.W))
  dShiftChosen := io.dShiftData
  when (dFinal) {
    dShiftChosen := dC(15, 0)
  } .elsewhen (eFinal) {
    dShiftChosen := dC(31, 16)
  }

  val dShiftInject = dFinal || eFinal
  val dCollision = dShiftInject && io.dValid

  val eShiftData = RegEnable(dShiftChosen, dShiftInject || io.dValid)
  val eValid = RegNext(dShiftInject || io.dValid, false.B)
  val error = RegNext(dCollision, false.B)

  io.bA := bA
  io.bB := bB
  io.bValid := bValid
  io.bFinal := bFinal
  io.eShiftData := eShiftData
  io.eValid := eValid
  io.error := error
}
