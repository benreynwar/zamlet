package zamlet.jamlet

import chisel3._
import chisel3.experimental.ExtModule
import zamlet.utils.ResetPipeline

class JamletMxuGridIO(n: Int) extends Bundle {
  val aIn = Input(Vec(n, UInt(8.W)))
  val aOut = Output(Vec(n, UInt(8.W)))

  val bIn = Input(Vec(n, UInt(8.W)))
  val bOut = Output(Vec(n, UInt(8.W)))

  val cIn = Input(Vec(n, UInt(16.W)))
  val cOut = Output(Vec(n, UInt(16.W)))
  val cValidIn = Input(Vec(n, Bool()))
  val cValidOut = Output(Vec(n, Bool()))

  val stepIn = Input(Vec(n, Bool()))
  val stepOut = Output(Vec(n, Bool()))
  val completeIn = Input(Vec(n, Bool()))
  val completeOut = Output(Vec(n, Bool()))
  val error = Output(Bool())
}

class JamletMxuGrid(n: Int = 4, bcBuffer: Boolean = false) extends Module {
  val io = IO(new JamletMxuGridIO(n))

  val cellReset = ResetPipeline(clock, reset.asBool, 1)
  val cells = withReset(cellReset) {
    Seq.tabulate(n, n) { (_, _) => Module(new JamletMxuCell(bcBuffer)) }
  }

  for (row <- 0 until n) {
    for (col <- 0 until n) {
      val cell = cells(row)(col)

      cell.io.aA := (if (col == 0) io.aIn(row) else cells(row)(col - 1).io.bA)
      cell.io.aB := (if (row == 0) io.bIn(col) else cells(row - 1)(col).io.bB)
      cell.io.dShiftData := (if (col == n - 1) io.cIn(row) else cells(row)(col + 1).io.eShiftData)
      cell.io.dValid := (if (col == n - 1) io.cValidIn(row) else cells(row)(col + 1).io.eValid)

      cell.io.aValid := (if (col == 0) io.stepIn(row) else cells(row)(col - 1).io.bValid)
      cell.io.aFinal := (if (col == 0) io.completeIn(row) else cells(row)(col - 1).io.bFinal)
    }

    io.aOut(row) := cells(row)(n - 1).io.bA
    io.cOut(row) := cells(row)(0).io.eShiftData
    io.cValidOut(row) := cells(row)(0).io.eValid
    io.stepOut(row) := cells(row)(n - 1).io.bValid
    io.completeOut(row) := cells(row)(n - 1).io.bFinal
  }

  for (col <- 0 until n) {
    io.bOut(col) := cells(n - 1)(col).io.bB
  }

  io.error := cells.flatten.map(_.io.error).reduce(_ || _)
}

class JamletMxuGridHardMacro(n: Int = 4) extends ExtModule {
  require(n == 4)
  override val desiredName = "JamletMxuGrid"

  val clock = IO(Input(Clock()))
  val reset = IO(Input(Bool()))
  val io = IO(new JamletMxuGridIO(n))
}

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

  val cToMemory = Output(Vec(n, UInt(16.W)))
  val cToMemoryValid = Output(Vec(n, Bool()))

  val init = Input(Vec(n, Bool()))
  val stepIn = Input(Vec(n, Bool()))
  val completeIn = Input(Vec(n, Bool()))
  val error = Output(Bool())
}

class JamletMxu(
    n: Int = 8,
    hasEwLoop: Boolean = true,
    hasNsLoop: Boolean = true,
    bcBuffer: Boolean = false,
    registerBackwardOutput: Boolean = false,
    useHardMacros: Boolean = false) extends Module {
  require(n == 2 || n == 4 || n == 8)
  require(!useHardMacros || n == 8)
  val io = IO(new JamletMxuIO(n))

  val ewBackwardInput = Wire(Vec(n, UInt(8.W)))
  val nsBackwardInput = Wire(Vec(n, UInt(8.W)))
  for (index <- 0 until n) {
    if (registerBackwardOutput) {
      ewBackwardInput(index) := RegNext(io.ewBackwardInput(index))
      nsBackwardInput(index) := RegNext(io.nsBackwardInput(index))
    } else {
      ewBackwardInput(index) := io.ewBackwardInput(index)
      nsBackwardInput(index) := io.nsBackwardInput(index)
    }
  }

  def instantiateGrid(name: String): JamletMxuGridIO = {
    if (useHardMacros) {
      val grid = Module(new JamletMxuGridHardMacro(4))
      grid.suggestName(name)
      grid.clock := clock
      grid.reset := reset.asBool
      grid.io
    } else {
      val grid = Module(new JamletMxuGrid(4, bcBuffer))
      grid.suggestName(name)
      grid.io
    }
  }

  def ewTopologyInput(row: Int): UInt = {
    if (hasEwLoop) Mux(io.ewUseBackward, ewBackwardInput(row), io.ewForwardInput(row)) else io.ewForwardInput(row)
  }

  def ewSelectedInput(row: Int): UInt = {
    Mux(io.init(row), io.ewFromMemory(row), ewTopologyInput(row))
  }

  def nsTopologyInput(col: Int): UInt = {
    if (hasNsLoop) Mux(io.nsUseBackward, nsBackwardInput(col), io.nsForwardInput(col)) else io.nsForwardInput(col)
  }

  def nsSelectedInput(col: Int): UInt = {
    Mux(io.init(col), io.nsFromMemory(col), nsTopologyInput(col))
  }

  if (n <= 4) {
    val grid = Module(new JamletMxuGrid(n, bcBuffer))

    for (row <- 0 until n) {
      grid.io.aIn(row) := ewSelectedInput(row)
      grid.io.cIn(row) := 0.U
      grid.io.cValidIn(row) := false.B
      grid.io.stepIn(row) := io.stepIn(row)
      grid.io.completeIn(row) := io.completeIn(row)
      io.ewForwardOutput(row) := grid.io.aOut(row)
      io.ewBackwardOutput(row) := ewBackwardInput(row)
      io.cToMemory(row) := grid.io.cOut(row)
      io.cToMemoryValid(row) := grid.io.cValidOut(row)
    }

    for (col <- 0 until n) {
      grid.io.bIn(col) := nsSelectedInput(col)
      io.nsForwardOutput(col) := grid.io.bOut(col)
      io.nsBackwardOutput(col) := nsBackwardInput(col)
    }

    io.error := RegNext(grid.io.error, false.B)
  } else {
    val nw = instantiateGrid("nw")
    val ne = instantiateGrid("ne")
    val sw = instantiateGrid("sw")
    val se = instantiateGrid("se")

    for (row <- 0 until 4) {
      nw.aIn(row) := ewSelectedInput(row)
      ne.aIn(row) := nw.aOut(row)
      sw.aIn(row) := ewSelectedInput(row + 4)
      se.aIn(row) := sw.aOut(row)
      io.ewForwardOutput(row) := ne.aOut(row)
      io.ewForwardOutput(row + 4) := se.aOut(row)
      io.ewBackwardOutput(row) := ewBackwardInput(row)
      io.ewBackwardOutput(row + 4) := ewBackwardInput(row + 4)

      nw.stepIn(row) := io.stepIn(row)
      ne.stepIn(row) := nw.stepOut(row)
      sw.stepIn(row) := io.stepIn(row + 4)
      se.stepIn(row) := sw.stepOut(row)

      nw.completeIn(row) := io.completeIn(row)
      ne.completeIn(row) := nw.completeOut(row)
      sw.completeIn(row) := io.completeIn(row + 4)
      se.completeIn(row) := sw.completeOut(row)

      ne.cIn(row) := 0.U
      ne.cValidIn(row) := false.B
      nw.cIn(row) := ne.cOut(row)
      nw.cValidIn(row) := ne.cValidOut(row)
      se.cIn(row) := 0.U
      se.cValidIn(row) := false.B
      sw.cIn(row) := se.cOut(row)
      sw.cValidIn(row) := se.cValidOut(row)
      io.cToMemory(row) := nw.cOut(row)
      io.cToMemoryValid(row) := nw.cValidOut(row)
      io.cToMemory(row + 4) := sw.cOut(row)
      io.cToMemoryValid(row + 4) := sw.cValidOut(row)

    }

    for (col <- 0 until 4) {
      nw.bIn(col) := nsSelectedInput(col)
      sw.bIn(col) := nw.bOut(col)
      ne.bIn(col) := nsSelectedInput(col + 4)
      se.bIn(col) := ne.bOut(col)
      io.nsForwardOutput(col) := sw.bOut(col)
      io.nsForwardOutput(col + 4) := se.bOut(col)
      io.nsBackwardOutput(col) := nsBackwardInput(col)
      io.nsBackwardOutput(col + 4) := nsBackwardInput(col + 4)
    }

    io.error := RegNext(nw.error || ne.error || sw.error || se.error, false.B)
  }
}

object JamletMxuGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxu(
      n = args.headOption.map(_.toInt).getOrElse(8),
      hasEwLoop = args.drop(1).headOption.forall(_.toBoolean),
      hasNsLoop = args.drop(2).headOption.forall(_.toBoolean),
      bcBuffer = args.drop(3).headOption.exists(_.toBoolean),
      registerBackwardOutput = args.drop(4).headOption.exists(_.toBoolean))
  }
}

object JamletMxuHardMacroGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxu(
      n = args.headOption.map(_.toInt).getOrElse(8),
      hasEwLoop = args.drop(1).headOption.forall(_.toBoolean),
      hasNsLoop = args.drop(2).headOption.forall(_.toBoolean),
      bcBuffer = true,
      registerBackwardOutput = args.drop(3).headOption.exists(_.toBoolean),
      useHardMacros = true)
  }
}

object JamletMxuGridGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxuGrid(
      n = args.headOption.map(_.toInt).getOrElse(4),
      bcBuffer = args.drop(1).headOption.exists(_.toBoolean))
  }
}

object JamletMxuCellGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxuCell(
      bcBuffer = args.headOption.exists(_.toBoolean))
  }
}

object JamletMxuMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuGenerator.generate(args(0), args.drop(1))
}

object JamletMxuHardMacroMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuHardMacroGenerator.generate(args(0), args.drop(1))
}

object JamletMxuGridMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuGridGenerator.generate(args(0), args.drop(1))
}

object JamletMxuCellMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuCellGenerator.generate(args(0), args.drop(1))
}
