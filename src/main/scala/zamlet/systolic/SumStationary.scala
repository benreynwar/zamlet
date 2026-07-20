package zamlet.systolic

import chisel3._
import chisel3.util._
import zamlet.maths.CSA3to2
import zamlet.utils.{ResetPipeline, ResetPipelineBudget}

class SumStationaryCDrain extends Bundle {
  val data = UInt(32.W)
  val fromLower = Bool()
}

class SumStationaryResetGroup extends RawModule {
  val clock = IO(Input(Clock()))
  val resetIn = IO(Input(Bool()))
  val resetOut = IO(Output(Reset()))

  withClock(clock) {
    val groupReset = RegNext(resetIn)
    dontTouch(groupReset)
    resetOut := groupReset
  }
}

class SumStationaryCellIO extends Bundle {
  // A moves west to east and B moves north to south. Valid and final move with A.
  val aA = Input(UInt(8.W))
  val bA = Output(UInt(8.W))
  val aB = Input(UInt(8.W))
  val bB = Output(UInt(8.W))

  val aValid = Input(Bool())
  val bValid = Output(Bool())
  val aFinal = Input(Bool())
  val bFinal = Output(Bool())

  val eCDrainIn = Input(Valid(new SumStationaryCDrain))
  val eCDrainOut = Output(Valid(new SumStationaryCDrain))
}

/** One signed 8-bit multiply, 32-bit sum-stationary processing element.
  *
  * The data path stages and their boundaries are:
  *   - A: A, B, valid, and final arrive at the cell.
  *   - A-to-B: A, B, valid, and final registers.
  *   - B: signed multiplication.
  *   - B-to-C: optional product, valid, and final registers (`registerBC`).
  *   - C: accumulation.
  *   - C-to-D: accumulator and final registers.
  *   - D: completed accumulator value; carry propagation in carry-save mode.
  *   - D-to-E: optional completed-result register (`registerDE`).
  *   - E: combinational northbound drain mux.
  *
  * `useCarrySaveAccumulator` stores the accumulator as sum and carry words. This
  * removes carry propagation from the recurrence; propagation occurs only when a
  * completed result enters the drain. The conventional mode stores one binary sum.
  *
  * `final` marks a valid product as the last product in its dot product. On the
  * following cycle the completed accumulator enters the drain and the accumulator
  * can begin the next dot product.
  */
class SumStationaryCell(
    useCarrySaveAccumulator: Boolean = false,
    registerBC: Boolean = true,
    registerDE: Boolean = false,
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(1)) extends Module {
  val io = IO(new SumStationaryCellIO)

  val resetPipeline =
    ResetPipeline(clock, reset.asBool, 1, resetBudget, "SumStationaryCell")

  withReset(resetPipeline.localReset) {
    val bValid = RegNext(io.aValid, false.B)
    val bFinal = RegNext(io.aFinal, false.B)
    val bA = RegEnable(io.aA, io.aValid)
    val bB = RegEnable(io.aB, io.aValid)

    val bAB = (bA.asSInt * bB.asSInt).asUInt
    val bABExtended = Cat(Fill(16, bAB(15)), bAB)

    // Optional B-to-C boundary used to separate multiplier and accumulator timing.
    val cAB = if (registerBC) RegNext(bABExtended) else bABExtended
    val cValid = if (registerBC) RegNext(bValid, false.B) else bValid
    val cFinal = if (registerBC) RegNext(bFinal, false.B) else bFinal

    val dFinal = RegNext(cFinal, false.B)
    val dCDrainData = Wire(UInt(32.W))

    if (useCarrySaveAccumulator) {
      val accSumNext = Wire(UInt(32.W))
      val accCarryNext = Wire(UInt(32.W))
      val accSum = RegEnable(accSumNext, 0.U(32.W), cValid || dFinal)
      val accCarry = RegEnable(accCarryNext, 0.U(32.W), cValid || dFinal)

      // Stage C adds the next product into the carry-save accumulator. On the
      // cycle after cFinal, stage D has the completed carry-save value and
      // converts it to binary for output while stage C can start the next sum.
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

    // A local completed result wins the drain mux. The wavefront schedule must
    // prevent it from coinciding with a valid result arriving from the south.
    val eFinal = if (registerDE) RegNext(dFinal, false.B) else dFinal
    val eCDrainData = if (registerDE) RegNext(dCDrainData) else dCDrainData
    io.eCDrainOut.valid := eFinal || io.eCDrainIn.valid
    io.eCDrainOut.bits.data := Mux(eFinal, eCDrainData, io.eCDrainIn.bits.data)
    io.eCDrainOut.bits.fromLower := Mux(eFinal, false.B, io.eCDrainIn.bits.fromLower)

    io.bA := bA
    io.bB := bB
    io.bValid := bValid
    io.bFinal := bFinal
  }
}

class SumStationaryIO(n: Int) extends Bundle {
  val aIn = Input(Vec(n, UInt(8.W)))
  val aOut = Output(Vec(n, UInt(8.W)))

  val bIn = Input(Vec(n, UInt(8.W)))
  val bOut = Output(Vec(n, UInt(8.W)))

  val cOut = Output(Vec(n, UInt(32.W)))

  val stepIn = Input(Bool())
  val completeIn = Input(Bool())
}

/** An `n` by `n` sum-stationary systolic array.
  *
  * A enters from the west, B enters from the north, and every cell retains its
  * dot-product sum until `completeIn` sends the completed sums into the northbound
  * C drain. `stepIn` and `completeIn` are delayed per row to form the same diagonal
  * wavefront as A; the cell carries both controls east with A.
  *
  * @param n square array dimension
  * @param useCarrySaveAccumulator select carry-save rather than binary accumulators
  * @param registerBC insert a register between each multiplier and accumulator
  * @param registerDE register each completed sum before its cell's drain mux
  * @param splitCDrain register the drain at the middle of each column and merge the
  *                    upper and lower drain streams through two north-edge registers
  * @param resetGroupSize when nonzero, add one reset register per square group of
  *                       this size; zero sends the array-level reset directly to cells
  * @param resetBudget number of reset-pipeline stages available through this hierarchy
  */
class SumStationary(
    n: Int = 8,
    useCarrySaveAccumulator: Boolean = false,
    registerBC: Boolean = true,
    registerDE: Boolean = false,
    splitCDrain: Boolean = false,
    resetGroupSize: Int = 0,
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(2)) extends Module {
  override val desiredName =
    s"SumStationary${n}x${n}_CSA${if (useCarrySaveAccumulator) 1 else 0}" +
      s"_BC${if (registerBC) 1 else 0}_DE${if (registerDE) 1 else 0}" +
      s"_SplitDrain${if (splitCDrain) 1 else 0}_ResetGroup$resetGroupSize"
  require(n > 0)
  require(!splitCDrain || (n >= 4 && n % 2 == 0))
  require(resetGroupSize >= 0)
  require(resetGroupSize == 0 || n % resetGroupSize == 0)
  val io = IO(new SumStationaryIO(n))

  val resetPipeline =
    ResetPipeline(clock, reset.asBool, 1, resetBudget, "SumStationary")

  // Large arrays can add a reset-distribution level per resetGroupSize square.
  // Keeping each group register distinct gives placement a local reset source.
  val cellResetBudget = if (resetGroupSize == 0) {
    resetPipeline.childBudget
  } else {
    resetPipeline.childBudget.consume(1, "SumStationary reset groups")
  }
  val groupResets = if (resetGroupSize == 0) {
    Seq.empty
  } else {
    Seq.tabulate(n / resetGroupSize, n / resetGroupSize) { (groupRow, groupCol) =>
      val resetGroup = Module(new SumStationaryResetGroup)
        .suggestName(s"resetGroup_${groupRow}_${groupCol}")
      resetGroup.clock := clock
      resetGroup.resetIn := resetPipeline.childReset.asBool
      resetGroup.resetOut
    }
  }
  def resetFor(row: Int, col: Int): Reset = {
    if (resetGroupSize == 0) {
      resetPipeline.childReset
    } else {
      groupResets(row / resetGroupSize)(col / resetGroupSize)
    }
  }

  val cells = Seq.tabulate(n, n) { (row, col) =>
    withReset(resetFor(row, col)) {
      Module(new SumStationaryCell(
        useCarrySaveAccumulator = useCarrySaveAccumulator,
        registerBC = registerBC,
        registerDE = registerDE,
        resetBudget = cellResetBudget))
    }
  }

  // Row zero receives each control after one register, row one after two, and so
  // on. A is presented with the corresponding timing by the external wavefront.
  val (stepIn, completeIn) = withReset(resetPipeline.localReset) {
    var previousStepIn: Bool = io.stepIn
    val stepIn = Seq.tabulate(n) { lane =>
      previousStepIn = RegNext(previousStepIn, false.B).suggestName(s"stepIn_$lane")
      previousStepIn
    }
    var previousCompleteIn: Bool = io.completeIn
    val completeIn = Seq.tabulate(n) { lane =>
      previousCompleteIn = RegNext(previousCompleteIn, false.B).suggestName(s"completeIn_$lane")
      previousCompleteIn
    }
    (stepIn, completeIn)
  }

  // In split mode, results from the lower half cross into the upper half through
  // a register. fromLower distinguishes that stream when it reaches the north end.
  val middleCDrain = if (splitCDrain) {
    Seq.tabulate(n) { col =>
      val middleCDrainRegister = withReset(resetFor(n / 2, col)) {
        Module(new RegisterWithPipelinedReset(Valid(UInt(32.W)), cellResetBudget))
      }
      middleCDrainRegister.io.in.valid := cells(n / 2)(col).io.eCDrainOut.valid
      middleCDrainRegister.io.in.bits := cells(n / 2)(col).io.eCDrainOut.bits.data
      middleCDrainRegister.io.out
    }
  } else {
    Seq.empty
  }

  for (row <- 0 until n) {
    for (col <- 0 until n) {
      val cell = cells(row)(col)

      // Cell coordinates increase eastward and southward.
      cell.io.aA := (if (col == 0) io.aIn(row) else cells(row)(col - 1).io.bA)
      cell.io.aB := (if (row == 0) io.bIn(col) else cells(row - 1)(col).io.bB)
      val startsCDrain = row == n - 1 || (splitCDrain && row == 0)
      if (startsCDrain) {
        cell.io.eCDrainIn.valid := false.B
        cell.io.eCDrainIn.bits.data := 0.U
        cell.io.eCDrainIn.bits.fromLower := false.B
      } else if (splitCDrain && row == n / 2 - 1) {
        cell.io.eCDrainIn.valid := middleCDrain(col).valid
        cell.io.eCDrainIn.bits.data := middleCDrain(col).bits
        cell.io.eCDrainIn.bits.fromLower := true.B
      } else {
        cell.io.eCDrainIn := cells(row + 1)(col).io.eCDrainOut
      }

      cell.io.aValid := (if (col == 0) stepIn(row) else cells(row)(col - 1).io.bValid)
      cell.io.aFinal := (if (col == 0) completeIn(row) else cells(row)(col - 1).io.bFinal)
    }
  }

  for (row <- 0 until n) {
    io.aOut(row) := cells(row)(n - 1).io.bA
  }

  for (col <- 0 until n) {
    io.bOut(col) := cells(n - 1)(col).io.bB
  }

  for (col <- 0 until n) {
    if (splitCDrain) {
      // Row zero drains separately. Row one's output carries either rows 1..n/2-1
      // or the registered lower half. First merge the two upper sources, then
      // merge that registered result with the lower source. The wavefront makes
      // both asserted-valid combinations protocol errors.
      val northCDrain = cells(0)(col).io.eCDrainOut
      val secondNorthCDrain = cells(1)(col).io.eCDrainOut
      val upperCDrainValid = secondNorthCDrain.valid && !secondNorthCDrain.bits.fromLower
      val lowerCDrainValid = secondNorthCDrain.valid && secondNorthCDrain.bits.fromLower

      assert(!(northCDrain.valid && upperCDrainValid))
      val upperCDrainRegister = withReset(resetFor(0, col)) {
        Module(new RegisterWithPipelinedReset(Valid(UInt(32.W)), cellResetBudget))
      }
      upperCDrainRegister.io.in.valid := northCDrain.valid || upperCDrainValid
      upperCDrainRegister.io.in.bits := Mux(
        upperCDrainValid,
        secondNorthCDrain.bits.data,
        northCDrain.bits.data)

      assert(!(upperCDrainRegister.io.out.valid && lowerCDrainValid))
      val cOutRegister = withReset(resetFor(0, col)) {
        Module(new RegisterWithPipelinedReset(Valid(UInt(32.W)), cellResetBudget))
      }
      cOutRegister.io.in.valid := upperCDrainRegister.io.out.valid || lowerCDrainValid
      cOutRegister.io.in.bits := Mux(
        lowerCDrainValid,
        secondNorthCDrain.bits.data,
        upperCDrainRegister.io.out.bits)
      io.cOut(col) := cOutRegister.io.out.bits
    } else {
      // Without a split, the complete drain flows through every cell to row zero
      // and receives one final register before cOut.
      val cOutRegister = withReset(resetFor(0, col)) {
        Module(new RegisterWithPipelinedReset(Valid(UInt(32.W)), cellResetBudget))
      }
      cOutRegister.io.in.valid := true.B
      cOutRegister.io.in.bits := cells(0)(col).io.eCDrainOut.bits.data
      io.cOut(col) := cOutRegister.io.out.bits
    }
  }
}

object SumStationaryGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val resetGroupSize = args.drop(5).headOption.map(_.toInt).getOrElse(0)
    new SumStationary(
      n = args.headOption.map(_.toInt).getOrElse(8),
      useCarrySaveAccumulator = args.drop(1).headOption.exists(_.toBoolean),
      registerBC = args.drop(2).headOption.forall(_.toBoolean),
      registerDE = args.drop(3).headOption.exists(_.toBoolean),
      splitCDrain = args.drop(4).headOption.exists(_.toBoolean),
      resetGroupSize = resetGroupSize,
      resetBudget = ResetPipelineBudget(if (resetGroupSize == 0) 2 else 3))
  }
}

object SumStationaryMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  SumStationaryGenerator.generate(args(0), args.drop(1))
}
