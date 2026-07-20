package zamlet.jamlet

import chisel3._
import zamlet.utils.{ResetPipeline, ResetPipelineBudget}

class JamletMxuIO(n: Int) extends Bundle {
  val ewFromMemory = Input(Vec(n, UInt(8.W)))
  val ewForwardInput = Input(Vec(n, UInt(8.W)))
  val ewBackwardInput = Input(Vec(n, UInt(8.W)))
  val ewUseBackward = Input(Bool())
  val ewForwardOutput = Output(Vec(n, UInt(8.W)))
  val ewBackwardOutput = Output(Vec(n, UInt(8.W)))

  val nsFromMemory = Input(Vec(n, UInt(8.W)))
  val nsForwardInput = Input(Vec(n, UInt(8.W)))
  val nsBackwardInput = Input(Vec(n, UInt(8.W)))
  val nsUseBackward = Input(Bool())
  val nsForwardOutput = Output(Vec(n, UInt(8.W)))
  val nsBackwardOutput = Output(Vec(n, UInt(8.W)))

  val cToMemory = Output(Vec(n, UInt(32.W)))
  val cToMemoryValid = Output(Vec(n, Bool()))

  val init = Input(Bool())
  val stepIn = Input(Bool())
  val completeIn = Input(Bool())
  val error = Output(Bool())
}

class JamletMxu(
    n: Int = 8,
    hasEwLoop: Boolean = true,
    hasNsLoop: Boolean = true,
    useCarrySaveAccumulator: Boolean = false,
    registerBC: Boolean = false,
    registerDE: Boolean = false,
    registerBackwardOutput: Boolean = false,
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(2)) extends Module {
  override val desiredName =
    s"JamletMxu${n}x${n}_EwLoop${if (hasEwLoop) 1 else 0}" +
      s"_NsLoop${if (hasNsLoop) 1 else 0}" +
      s"_CSA${if (useCarrySaveAccumulator) 1 else 0}" +
      s"_BC${if (registerBC) 1 else 0}_DE${if (registerDE) 1 else 0}" +
      s"_BackwardReg${if (registerBackwardOutput) 1 else 0}"
  require(n == 2 || n == 4 || n == 8)
  val io = IO(new JamletMxuIO(n))

  val resetPipeline = ResetPipeline(clock, reset.asBool, 1, resetBudget, "JamletMxu")
  val cellReset = resetPipeline.childReset
  val cellResetBudget = resetPipeline.childBudget

  val ewBackwardInput = Wire(Vec(n, UInt(8.W)))
  val nsBackwardInput = Wire(Vec(n, UInt(8.W)))
  val ewUseBackward = RegNext(io.ewUseBackward, false.B)
  val nsUseBackward = RegNext(io.nsUseBackward, false.B)
  val ewUseBackwardMux = Seq.tabulate(n) { row =>
    RegNext(ewUseBackward, false.B).suggestName(s"ewUseBackwardMux_$row")
  }
  val nsUseBackwardMux = Seq.tabulate(n) { col =>
    RegNext(nsUseBackward, false.B).suggestName(s"nsUseBackwardMux_$col")
  }
  var previousInit: Bool = io.init
  val init = Seq.tabulate(n) { lane =>
    previousInit = RegNext(previousInit, false.B).suggestName(s"init_$lane")
    previousInit
  }
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
  for (index <- 0 until n) {
    if (registerBackwardOutput) {
      ewBackwardInput(index) := RegNext(io.ewBackwardInput(index))
      nsBackwardInput(index) := RegNext(io.nsBackwardInput(index))
    } else {
      ewBackwardInput(index) := io.ewBackwardInput(index)
      nsBackwardInput(index) := io.nsBackwardInput(index)
    }
  }

  def ewTopologyInput(row: Int): UInt = {
    if (hasEwLoop) Mux(ewUseBackwardMux(row), ewBackwardInput(row), io.ewForwardInput(row)) else io.ewForwardInput(row)
  }

  def ewSelectedInput(row: Int): UInt = {
    Mux(init(row), io.ewFromMemory(row), ewTopologyInput(row))
  }

  def nsTopologyInput(col: Int): UInt = {
    if (hasNsLoop) Mux(nsUseBackwardMux(col), nsBackwardInput(col), io.nsForwardInput(col)) else io.nsForwardInput(col)
  }

  def nsSelectedInput(col: Int): UInt = {
    Mux(init(col), io.nsFromMemory(col), nsTopologyInput(col))
  }

  val cells = Seq.tabulate(n, n) { (_, _) =>
    withReset(cellReset) {
      Module(new JamletMxuCell(
        useCarrySaveAccumulator = useCarrySaveAccumulator,
        registerBC = registerBC,
        registerDE = registerDE,
        resetBudget = cellResetBudget))
    }
  }

  for (row <- 0 until n) {
    for (col <- 0 until n) {
      val cell = cells(row)(col)
      cell.io.aA := (if (col == 0) ewSelectedInput(row) else cells(row)(col - 1).io.bA)
      cell.io.aB := (if (row == 0) nsSelectedInput(col) else cells(row - 1)(col).io.bB)
      cell.io.aValid := (if (col == 0) stepIn(row) else cells(row)(col - 1).io.bValid)
      cell.io.aFinal := (if (col == 0) completeIn(row) else cells(row)(col - 1).io.bFinal)
      if (col == n - 1) {
        cell.io.eCDrainIn.valid := false.B
        cell.io.eCDrainIn.bits.data := 0.U
        cell.io.eCDrainIn.bits.fromFar := false.B
      } else {
        cell.io.eCDrainIn := cells(row)(col + 1).io.eCDrainOut
      }
    }

    io.ewForwardOutput(row) := cells(row)(n - 1).io.bA
    io.ewBackwardOutput(row) := ewBackwardInput(row)
    io.cToMemory(row) := RegNext(cells(row)(0).io.eCDrainOut.bits.data, 0.U)
    io.cToMemoryValid(row) := RegNext(cells(row)(0).io.eCDrainOut.valid, false.B)
  }

  for (col <- 0 until n) {
    io.nsForwardOutput(col) := cells(n - 1)(col).io.bB
    io.nsBackwardOutput(col) := nsBackwardInput(col)
  }

  io.error := RegNext(cells.flatten.map(_.io.error).reduce(_ || _), false.B)
}

object JamletMxuGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxu(
      n = args.headOption.map(_.toInt).getOrElse(8),
      hasEwLoop = args.drop(1).headOption.forall(_.toBoolean),
      hasNsLoop = args.drop(2).headOption.forall(_.toBoolean),
      useCarrySaveAccumulator = args.drop(3).headOption.exists(_.toBoolean),
      registerBC = args.drop(4).headOption.exists(_.toBoolean),
      registerDE = args.drop(5).headOption.exists(_.toBoolean),
      registerBackwardOutput = args.drop(6).headOption.exists(_.toBoolean))
  }
}

object JamletMxuCellGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxuCell(
      useCarrySaveAccumulator = args.headOption.exists(_.toBoolean),
      registerBC = args.drop(1).headOption.exists(_.toBoolean),
      registerDE = args.drop(2).headOption.exists(_.toBoolean))
  }
}

object JamletMxuMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuGenerator.generate(args(0), args.drop(1))
}

object JamletMxuCellMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuCellGenerator.generate(args(0), args.drop(1))
}
