package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.maths.CSA3to2
import zamlet.utils.{ResetPipeline, ResetPipelineBudget}

class JamletMxuCDrain extends Bundle {
  val data = UInt(32.W)
  val fromFar = Bool()
}

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

  // C drain path. Neighbor data passes through unless this cell is emitting
  // its completed accumulator.
  val eCDrainIn = Input(Valid(new JamletMxuCDrain))
  val eCDrainOut = Output(Valid(new JamletMxuCDrain))

  val error = Output(Bool())
}

class JamletMxuCell(
    useCarrySaveAccumulator: Boolean = false,
    registerBC: Boolean = false,
    registerDE: Boolean = false,
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(1)) extends Module {
  val io = IO(new JamletMxuCellIO)

  val resetPipeline =
    ResetPipeline(clock, reset.asBool, 1, resetBudget, "JamletMxuCell")

  withReset(resetPipeline.localReset) {
    val bValid = RegNext(io.aValid, false.B)
    val bFinal = RegNext(io.aFinal, false.B)
    val bA = RegEnable(io.aA, io.aValid)
    val bB = RegEnable(io.aB, io.aValid)

    val bAB = (bA.asSInt * bB.asSInt).asUInt
    val bABExtended = Cat(Fill(16, bAB(15)), bAB)
    val cAB = if (registerBC) RegEnable(bABExtended, bValid) else bABExtended
    val cValid = if (registerBC) RegNext(bValid, false.B) else bValid
    val cFinal = if (registerBC) RegNext(bFinal, false.B) else bFinal
    val dFinal = RegNext(cFinal, false.B)
    val dCDrainData = Wire(UInt(32.W))

    if (useCarrySaveAccumulator) {
      val accSumNext = Wire(UInt(32.W))
      val accCarryNext = Wire(UInt(32.W))
      val accSum = RegEnable(accSumNext, 0.U(32.W), cValid || dFinal)
      val accCarry = RegEnable(accCarryNext, 0.U(32.W), cValid || dFinal)

      val cAccSumBase = Mux(dFinal, 0.U(32.W), accSum)
      val cAccCarryBase = Mux(dFinal, 0.U(32.W), accCarry)
      val csa = Module(new CSA3to2(32))
      csa.io.a := cAccSumBase
      csa.io.b := cAccCarryBase
      csa.io.c := cAB

      accSumNext := cAccSumBase
      accCarryNext := cAccCarryBase
      when (cValid) {
        accSumNext := csa.io.sum
        accCarryNext := csa.io.carry
      }

      dCDrainData := accSum + accCarry
    } else {
      val dCNext = Wire(UInt(32.W))
      val dC = RegEnable(dCNext, 0.U(32.W), cValid || dFinal)
      val cCBase = Mux(dFinal, 0.U(32.W), dC)
      dCNext := cCBase
      when (cValid) {
        dCNext := (cCBase + cAB)(31, 0)
      }
      dCDrainData := dC
    }

    val eFinal = if (registerDE) RegNext(dFinal, false.B) else dFinal
    val eCDrainData = if (registerDE) RegNext(dCDrainData) else dCDrainData
    val eCollision = eFinal && io.eCDrainIn.valid
    val error = RegNext(eCollision, false.B)

    io.bA := bA
    io.bB := bB
    io.bValid := bValid
    io.bFinal := bFinal
    io.eCDrainOut.valid := eFinal || io.eCDrainIn.valid
    io.eCDrainOut.bits.data := Mux(eFinal, eCDrainData, io.eCDrainIn.bits.data)
    io.eCDrainOut.bits.fromFar := Mux(eFinal, false.B, io.eCDrainIn.bits.fromFar)
    io.error := error
  }
}
