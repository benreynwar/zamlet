package zamlet.systolic

import chisel3._
import chisel3.experimental.ExtModule
import chisel3.util._
import zamlet.utils.{RegisterWithPipelinedReset, ResetPipeline, ResetPipelineBudget}

class WeightStationaryResetGroup extends RawModule {
  val clock = IO(Input(Clock()))
  val resetIn = IO(Input(Bool()))
  val resetOut = IO(Output(Reset()))

  withClock(clock) {
    val groupReset = RegNext(resetIn)
    dontTouch(groupReset)
    resetOut := groupReset
  }
}

class WeightStationaryCellIO extends Bundle {
  val inputIn = Input(UInt(8.W))
  val inputOut = Output(UInt(8.W))

  val weightLoadIn = Input(UInt(8.W))
  val weightLoadOut = Output(UInt(8.W))

  val sumIn = Input(UInt(32.W))
  val sumOut = Output(UInt(32.W))

  val loadWeightIn = Input(Bool())
  val loadWeightOut = Output(Bool())

  val stepIn = Input(Bool())
  val stepOut = Output(Bool())
}

class WeightStationaryCell(
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(1)) extends Module {
  val io = IO(new WeightStationaryCellIO)

  val resetPipeline =
    ResetPipeline(clock, reset.asBool, 1, resetBudget, "WeightStationaryCell")

  withReset(resetPipeline.localReset) {
    val bInput = RegNext(io.inputIn)
    val bStep = RegNext(io.stepIn, false.B)

    // Weight data is combinational through the column. The registered load pulse
    // moves south and captures each weight with its first stage-B input.
    val bLoadWeight = RegNext(io.loadWeightIn, false.B)
    val bWeight = RegEnable(io.weightLoadIn, io.loadWeightIn)

    val bProduct = (bInput.asSInt * bWeight.asSInt).asUInt

    val cProduct = RegNext(Cat(Fill(16, bProduct(15)), bProduct))

    io.inputOut := bInput
    io.weightLoadOut := io.weightLoadIn
    // sumIn enters stage C. The stage-C addition is registered at C-to-D.
    // The next row consumes dSum with the corresponding delayed step.
    val dSum = RegNext((io.sumIn + cProduct)(31, 0))

    io.sumOut := dSum

    io.loadWeightOut := bLoadWeight
    io.stepOut := bStep
  }
}

class WeightStationaryIO(n: Int) extends Bundle {
  val inputIn = Input(Vec(n, UInt(8.W)))
  val weightLoadIn = Input(Vec(n, UInt(8.W)))
  val sumIn = Input(Vec(n, UInt(32.W)))

  val loadWeightIn = Input(Bool())
  val stepIn = Input(Bool())

  val inputOut = Output(Vec(n, UInt(8.W)))
  val sumOut = Output(Vec(n, UInt(32.W)))
}

class WeightStationary(
    n: Int = 8,
    resetGroupSize: Int = 0,
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(2)) extends Module {
  override val desiredName = s"WeightStationary${n}x${n}_ResetGroup$resetGroupSize"
  require(n > 0)
  require(resetGroupSize >= 0)
  require(resetGroupSize == 0 || n % resetGroupSize == 0)
  val io = IO(new WeightStationaryIO(n))

  val resetPipeline =
    ResetPipeline(clock, reset.asBool, 1, resetBudget, "WeightStationary")

  val cellResetBudget = if (resetGroupSize == 0) {
    resetPipeline.childBudget
  } else {
    resetPipeline.childBudget.consume(1, "WeightStationary reset groups")
  }
  val groupResets = if (resetGroupSize == 0) {
    Seq.empty
  } else {
    Seq.tabulate(n / resetGroupSize, n / resetGroupSize) { (groupRow, groupCol) =>
      val resetGroup = Module(new WeightStationaryResetGroup)
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
      Module(new WeightStationaryCell(cellResetBudget))
    }
  }

  val (loadWeightIn, stepIn) = withReset(resetPipeline.localReset) {
    var previousLoadWeightIn: Bool = io.loadWeightIn
    val loadWeightIn = Seq.tabulate(n) { lane =>
      previousLoadWeightIn =
        RegNext(previousLoadWeightIn, false.B).suggestName(s"loadWeightIn_$lane")
      previousLoadWeightIn
    }
    var previousStepIn: Bool = io.stepIn
    val stepIn = Seq.tabulate(n) { lane =>
      previousStepIn = RegNext(previousStepIn, false.B).suggestName(s"stepIn_$lane")
      previousStepIn
    }
    (loadWeightIn, stepIn)
  }

  val sumIn = Seq.tabulate(n) { col =>
    val sumInRegister = withReset(resetFor(0, col)) {
      Module(new RegisterWithPipelinedReset(UInt(32.W), cellResetBudget))
        .suggestName(s"sumInRegister_$col")
    }
    sumInRegister.io.in := io.sumIn(col)
    sumInRegister.io.out
  }

  for (row <- 0 until n) {
    for (col <- 0 until n) {
      val cell = cells(row)(col)

      cell.io.inputIn := (if (col == 0) io.inputIn(row) else cells(row)(col - 1).io.inputOut)
      cell.io.stepIn := (if (col == 0) stepIn(row) else cells(row)(col - 1).io.stepOut)

      cell.io.weightLoadIn := (if (row == 0) io.weightLoadIn(col) else cells(row - 1)(col).io.weightLoadOut)
      cell.io.loadWeightIn := (if (row == 0) loadWeightIn(col) else cells(row - 1)(col).io.loadWeightOut)

      cell.io.sumIn := (if (row == 0) sumIn(col) else cells(row - 1)(col).io.sumOut)
    }
  }

  for (row <- 0 until n) {
    io.inputOut(row) := cells(row)(n - 1).io.inputOut
  }

  for (col <- 0 until n) {
    io.sumOut(col) := cells(n - 1)(col).io.sumOut
  }
}

class WeightStationaryIverilogCore(n: Int, resetGroupSize: Int) extends ExtModule {
  override val desiredName = s"WeightStationary${n}x${n}_ResetGroup$resetGroupSize"

  val clock = IO(Input(Clock()))
  val reset = IO(Input(Reset()))
  val io = IO(new WeightStationaryIO(n))
}

class WeightStationaryIverilogWrapper(n: Int, resetGroupSize: Int) extends Module {
  override val desiredName =
    s"WeightStationary${n}x${n}_ResetGroup${resetGroupSize}IverilogWrapper"
  val io = IO(new WeightStationaryIO(n))
  val powerDumpEnable = IO(Input(Bool()))

  val dut = Module(new WeightStationaryIverilogCore(n, resetGroupSize))
  dut.clock := clock
  dut.reset := reset
  dut.io <> io
}

object WeightStationaryGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val resetGroupSize = args.drop(1).headOption.map(_.toInt).getOrElse(0)
    new WeightStationary(
      n = args.headOption.map(_.toInt).getOrElse(8),
      resetGroupSize = resetGroupSize,
      resetBudget = ResetPipelineBudget(if (resetGroupSize == 0) 2 else 3))
  }
}

object WeightStationaryIverilogWrapperGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module =
    new WeightStationaryIverilogWrapper(
      n = args.headOption.map(_.toInt).getOrElse(8),
      resetGroupSize = args.drop(1).headOption.map(_.toInt).getOrElse(0))
}

object WeightStationaryMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  WeightStationaryGenerator.generate(args(0), args.drop(1))
}

object WeightStationaryIverilogWrapperMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  WeightStationaryIverilogWrapperGenerator.generate(args(0), args.drop(1))
}
