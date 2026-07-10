package zamlet.jamlet

import chisel3._
import chisel3.util._

class JamletMxuCellIO extends Bundle {
  val aIn = Input(UInt(8.W))
  val aOut = Output(UInt(8.W))
  val aStoreIn = Input(UInt(8.W))
  val aStoreOut = Output(UInt(8.W))

  val bIn = Input(UInt(8.W))
  val bOut = Output(UInt(8.W))
  val bStoreIn = Input(UInt(8.W))
  val bStoreOut = Output(UInt(8.W))

  val cShiftIn = Input(UInt(32.W))
  val cShiftOut = Output(UInt(32.W))

  val initialize = Input(Bool())
  val storeAccumulator = Input(Bool())
  val step = Input(Bool())
  val load = Input(Bool())
  val dump = Input(Bool())
}

class JamletMxuCell(registerProduct: Boolean = false) extends Module {
  val io = IO(new JamletMxuCellIO)

  val initialize = RegNext(io.initialize, false.B)
  val storeAccumulator = RegNext(io.storeAccumulator, false.B)
  val step = RegNext(io.step, false.B)
  val load = RegNext(io.load, false.B)
  val dump = RegNext(io.dump, false.B)

  val aStore = RegEnable(io.aStoreIn, load)
  val bStore = RegEnable(io.bStoreIn, load)

  val a = RegEnable(Mux(initialize, aStore, io.aIn), initialize || step)
  val b = RegEnable(Mux(initialize, bStore, io.bIn), initialize || step)

  val product = (a.asSInt * b.asSInt).asUInt
  val productExtendedRaw = Cat(Fill(16, product(15)), product)
  val productExtended = if (registerProduct) RegEnable(productExtendedRaw, step) else productExtendedRaw
  val accumulateStep = if (registerProduct) RegNext(step, false.B) else step
  val cNext = Wire(UInt(32.W))
  val c = RegEnable(cNext, accumulateStep || storeAccumulator)
  cNext := Mux(storeAccumulator, Mux(accumulateStep, productExtended, 0.U), (c + productExtended)(31, 0))

  val cStore = RegEnable(Mux(storeAccumulator, c, io.cShiftIn), storeAccumulator || dump)

  io.aOut := a
  io.aStoreOut := aStore
  io.bOut := b
  io.bStoreOut := bStore
  io.cShiftOut := cStore
}

class JamletMxuGridIO(n: Int) extends Bundle {
  val aWestIn = Input(Vec(n, UInt(8.W)))
  val aEastOut = Output(Vec(n, UInt(8.W)))

  val bNorthIn = Input(Vec(n, UInt(8.W)))
  val bSouthOut = Output(Vec(n, UInt(8.W)))

  val aStoreNorthIn = Input(Vec(n, UInt(8.W)))
  val aStoreSouthOut = Output(Vec(n, UInt(8.W)))

  val bStoreNorthIn = Input(Vec(n, UInt(8.W)))
  val bStoreSouthOut = Output(Vec(n, UInt(8.W)))

  val cEastIn = Input(Vec(n, UInt(32.W)))
  val cWestOut = Output(Vec(n, UInt(32.W)))

  val initialize = Input(Bool())
  val storeAccumulator = Input(Bool())
  val step = Input(Bool())
  val load = Input(Bool())
  val dump = Input(Bool())
}

class JamletMxuGrid(n: Int = 4, registerProduct: Boolean = false) extends Module {
  val io = IO(new JamletMxuGridIO(n))

  val initialize = RegNext(io.initialize, false.B)
  val storeAccumulator = RegNext(io.storeAccumulator, false.B)
  val step = RegNext(io.step, false.B)
  val load = RegNext(io.load, false.B)
  val dump = RegNext(io.dump, false.B)

  val cells = Seq.tabulate(n, n) { (_, _) => Module(new JamletMxuCell(registerProduct)) }

  for (row <- 0 until n) {
    for (col <- 0 until n) {
      val cell = cells(row)(col)

      cell.io.aIn := (if (col == 0) io.aWestIn(row) else cells(row)(col - 1).io.aOut)
      cell.io.bIn := (if (row == 0) io.bNorthIn(col) else cells(row - 1)(col).io.bOut)
      cell.io.aStoreIn := (if (row == 0) io.aStoreNorthIn(col) else cells(row - 1)(col).io.aStoreOut)
      cell.io.bStoreIn := (if (row == 0) io.bStoreNorthIn(col) else cells(row - 1)(col).io.bStoreOut)
      cell.io.cShiftIn := (if (col == n - 1) io.cEastIn(row) else cells(row)(col + 1).io.cShiftOut)

      cell.io.initialize := initialize
      cell.io.storeAccumulator := storeAccumulator
      cell.io.step := step
      cell.io.load := load
      cell.io.dump := dump
    }

    io.aEastOut(row) := cells(row)(n - 1).io.aOut
    io.cWestOut(row) := cells(row)(0).io.cShiftOut
  }

  for (col <- 0 until n) {
    io.bSouthOut(col) := cells(n - 1)(col).io.bOut
    io.aStoreSouthOut(col) := cells(n - 1)(col).io.aStoreOut
    io.bStoreSouthOut(col) := cells(n - 1)(col).io.bStoreOut
  }
}

class JamletMxuIO(n: Int) extends Bundle {
  val ewInput = Input(Vec(n, UInt(8.W)))
  val ewLoopInput = Input(Vec(n, UInt(8.W)))
  val ewLoop = Input(Bool())
  val ewOutput = Output(Vec(n, UInt(8.W)))

  val nsInput = Input(Vec(n, UInt(8.W)))
  val nsLoopInput = Input(Vec(n, UInt(8.W)))
  val nsLoop = Input(Bool())
  val nsOutput = Output(Vec(n, UInt(8.W)))

  val aStoreNorthIn = Input(Vec(n, UInt(8.W)))
  val aStoreSouthOut = Output(Vec(n, UInt(8.W)))

  val bStoreNorthIn = Input(Vec(n, UInt(8.W)))
  val bStoreSouthOut = Output(Vec(n, UInt(8.W)))

  val cEastIn = Input(Vec(n, UInt(32.W)))
  val cWestOut = Output(Vec(n, UInt(32.W)))

  val initialize = Input(Bool())
  val storeAccumulator = Input(Bool())
  val step = Input(Bool())
  val load = Input(Bool())
  val dump = Input(Bool())
}

class JamletMxu(
    n: Int = 8,
    hasEwLoop: Boolean = true,
    hasNsLoop: Boolean = true,
    registerProduct: Boolean = false) extends Module {
  require(n == 2 || n == 4 || n == 8)
  val io = IO(new JamletMxuIO(n))

  def connectControls(grid: JamletMxuGrid): Unit = {
    grid.io.initialize := io.initialize
    grid.io.storeAccumulator := io.storeAccumulator
    grid.io.step := io.step
    grid.io.load := io.load
    grid.io.dump := io.dump
  }

  def ewInput(row: Int): UInt = {
    if (hasEwLoop) Mux(io.ewLoop, io.ewLoopInput(row), io.ewInput(row)) else io.ewInput(row)
  }

  def nsInput(col: Int): UInt = {
    if (hasNsLoop) Mux(io.nsLoop, io.nsLoopInput(col), io.nsInput(col)) else io.nsInput(col)
  }

  if (n <= 4) {
    val grid = Module(new JamletMxuGrid(n, registerProduct))
    connectControls(grid)

    for (row <- 0 until n) {
      grid.io.aWestIn(row) := ewInput(row)
      grid.io.cEastIn(row) := io.cEastIn(row)
      io.ewOutput(row) := grid.io.aEastOut(row)
      io.cWestOut(row) := grid.io.cWestOut(row)
    }

    for (col <- 0 until n) {
      grid.io.bNorthIn(col) := nsInput(col)
      grid.io.aStoreNorthIn(col) := io.aStoreNorthIn(col)
      grid.io.bStoreNorthIn(col) := io.bStoreNorthIn(col)
      io.nsOutput(col) := grid.io.bSouthOut(col)
      io.aStoreSouthOut(col) := grid.io.aStoreSouthOut(col)
      io.bStoreSouthOut(col) := grid.io.bStoreSouthOut(col)
    }
  } else {
    val nw = Module(new JamletMxuGrid(4, registerProduct))
    val ne = Module(new JamletMxuGrid(4, registerProduct))
    val sw = Module(new JamletMxuGrid(4, registerProduct))
    val se = Module(new JamletMxuGrid(4, registerProduct))
    val grids = Seq(nw, ne, sw, se)
    grids.foreach(connectControls)

    for (row <- 0 until 4) {
      nw.io.aWestIn(row) := ewInput(row)
      ne.io.aWestIn(row) := nw.io.aEastOut(row)
      sw.io.aWestIn(row) := ewInput(row + 4)
      se.io.aWestIn(row) := sw.io.aEastOut(row)
      io.ewOutput(row) := ne.io.aEastOut(row)
      io.ewOutput(row + 4) := se.io.aEastOut(row)

      ne.io.cEastIn(row) := io.cEastIn(row)
      nw.io.cEastIn(row) := ne.io.cWestOut(row)
      se.io.cEastIn(row) := io.cEastIn(row + 4)
      sw.io.cEastIn(row) := se.io.cWestOut(row)
      io.cWestOut(row) := nw.io.cWestOut(row)
      io.cWestOut(row + 4) := sw.io.cWestOut(row)

    }

    for (col <- 0 until 4) {
      nw.io.bNorthIn(col) := nsInput(col)
      sw.io.bNorthIn(col) := nw.io.bSouthOut(col)
      ne.io.bNorthIn(col) := nsInput(col + 4)
      se.io.bNorthIn(col) := ne.io.bSouthOut(col)
      io.nsOutput(col) := sw.io.bSouthOut(col)
      io.nsOutput(col + 4) := se.io.bSouthOut(col)

      nw.io.aStoreNorthIn(col) := io.aStoreNorthIn(col)
      sw.io.aStoreNorthIn(col) := nw.io.aStoreSouthOut(col)
      ne.io.aStoreNorthIn(col) := io.aStoreNorthIn(col + 4)
      se.io.aStoreNorthIn(col) := ne.io.aStoreSouthOut(col)
      io.aStoreSouthOut(col) := sw.io.aStoreSouthOut(col)
      io.aStoreSouthOut(col + 4) := se.io.aStoreSouthOut(col)

      nw.io.bStoreNorthIn(col) := io.bStoreNorthIn(col)
      sw.io.bStoreNorthIn(col) := nw.io.bStoreSouthOut(col)
      ne.io.bStoreNorthIn(col) := io.bStoreNorthIn(col + 4)
      se.io.bStoreNorthIn(col) := ne.io.bStoreSouthOut(col)
      io.bStoreSouthOut(col) := sw.io.bStoreSouthOut(col)
      io.bStoreSouthOut(col + 4) := se.io.bStoreSouthOut(col)
    }
  }
}

class JamletMxuTestGridIO(gridRows: Int, gridCols: Int, mxuN: Int) extends Bundle {
  val aWestIn = Input(Vec(gridRows, Vec(mxuN, UInt(8.W))))
  val westLoop = Input(Bool())
  val aEastOut = Output(Vec(gridRows, Vec(mxuN, UInt(8.W))))

  val bNorthIn = Input(Vec(gridCols, Vec(mxuN, UInt(8.W))))
  val northLoop = Input(Bool())
  val bSouthOut = Output(Vec(gridCols, Vec(mxuN, UInt(8.W))))

  val aStoreNorthIn = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(8.W)))))
  val aStoreSouthOut = Output(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(8.W)))))

  val bStoreNorthIn = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(8.W)))))
  val bStoreSouthOut = Output(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(8.W)))))

  val cEastIn = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(32.W)))))
  val cWestOut = Output(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(32.W)))))

  val initialize = Input(Bool())
  val storeAccumulator = Input(Bool())
  val step = Input(Bool())
  val load = Input(Bool())
  val dump = Input(Bool())
}

class JamletMxuTestGrid(
    gridRows: Int = 2,
    gridCols: Int = 2,
    mxuN: Int = 4,
    registerProduct: Boolean = false) extends Module {
  require(gridRows > 0 && isPow2(gridRows))
  require(gridCols > 0 && isPow2(gridCols))
  val io = IO(new JamletMxuTestGridIO(gridRows, gridCols, mxuN))

  def foldedIndex(index: Int, size: Int): Int = {
    if (index % 2 == 0) {
      index / 2
    } else {
      size - ((index + 1) / 2)
    }
  }

  val physicalToLogicalRow = Seq.tabulate(gridRows)(foldedIndex(_, gridRows))
  val physicalToLogicalCol = Seq.tabulate(gridCols)(foldedIndex(_, gridCols))
  val logicalToPhysicalRow = physicalToLogicalRow.zipWithIndex.sortBy(_._1).map(_._2)
  val logicalToPhysicalCol = physicalToLogicalCol.zipWithIndex.sortBy(_._1).map(_._2)

  val blocks = Seq.tabulate(gridRows, gridCols) { (_, _) =>
    Module(new JamletMxu(
      n = mxuN,
      hasEwLoop = true,
      hasNsLoop = true,
      registerProduct = registerProduct))
  }

  for (physicalRow <- 0 until gridRows) {
    for (physicalCol <- 0 until gridCols) {
      val block = blocks(physicalRow)(physicalCol)
      val logicalRow = physicalToLogicalRow(physicalRow)
      val logicalCol = physicalToLogicalCol(physicalCol)

      block.io.initialize := io.initialize
      block.io.storeAccumulator := io.storeAccumulator
      block.io.step := io.step
      block.io.load := io.load
      block.io.dump := io.dump

      block.io.ewLoop := (if (logicalCol == 0) io.westLoop else false.B)
      block.io.nsLoop := (if (logicalRow == 0) io.northLoop else false.B)

      for (row <- 0 until mxuN) {
        block.io.ewInput(row) := (
          if (logicalCol == 0) {
            io.aWestIn(logicalRow)(row)
          } else {
            blocks(logicalToPhysicalRow(logicalRow))(logicalToPhysicalCol(logicalCol - 1)).io.ewOutput(row)
          })
        block.io.ewLoopInput(row) := blocks(logicalToPhysicalRow(logicalRow))(logicalToPhysicalCol(gridCols - 1)).io.ewOutput(row)
        block.io.cEastIn(row) := io.cEastIn(logicalRow)(logicalCol)(row)
        io.cWestOut(logicalRow)(logicalCol)(row) := block.io.cWestOut(row)
      }

      for (col <- 0 until mxuN) {
        block.io.nsInput(col) := (
          if (logicalRow == 0) {
            io.bNorthIn(logicalCol)(col)
          } else {
            blocks(logicalToPhysicalRow(logicalRow - 1))(logicalToPhysicalCol(logicalCol)).io.nsOutput(col)
          })
        block.io.nsLoopInput(col) := blocks(logicalToPhysicalRow(gridRows - 1))(logicalToPhysicalCol(logicalCol)).io.nsOutput(col)
        block.io.aStoreNorthIn(col) := io.aStoreNorthIn(logicalRow)(logicalCol)(col)
        block.io.bStoreNorthIn(col) := io.bStoreNorthIn(logicalRow)(logicalCol)(col)
        io.aStoreSouthOut(logicalRow)(logicalCol)(col) := block.io.aStoreSouthOut(col)
        io.bStoreSouthOut(logicalRow)(logicalCol)(col) := block.io.bStoreSouthOut(col)
      }
    }
  }

  for (logicalRow <- 0 until gridRows) {
    for (row <- 0 until mxuN) {
      io.aEastOut(logicalRow)(row) := blocks(logicalToPhysicalRow(logicalRow))(logicalToPhysicalCol(gridCols - 1)).io.ewOutput(row)
    }
  }

  for (logicalCol <- 0 until gridCols) {
    for (col <- 0 until mxuN) {
      io.bSouthOut(logicalCol)(col) := blocks(logicalToPhysicalRow(gridRows - 1))(logicalToPhysicalCol(logicalCol)).io.nsOutput(col)
    }
  }
}

object JamletMxuGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxu(
      n = args.headOption.map(_.toInt).getOrElse(8),
      hasEwLoop = args.drop(1).headOption.forall(_.toBoolean),
      hasNsLoop = args.drop(2).headOption.forall(_.toBoolean),
      registerProduct = args.drop(3).headOption.exists(_.toBoolean))
  }
}

object JamletMxuGridGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxuGrid(
      n = args.headOption.map(_.toInt).getOrElse(4),
      registerProduct = args.drop(1).headOption.exists(_.toBoolean))
  }
}

object JamletMxuTestGridGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxuTestGrid(
      gridRows = args.headOption.map(_.toInt).getOrElse(2),
      gridCols = args.drop(1).headOption.map(_.toInt).getOrElse(2),
      mxuN = args.drop(2).headOption.map(_.toInt).getOrElse(4),
      registerProduct = args.drop(3).headOption.exists(_.toBoolean))
  }
}

object JamletMxuCellGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxuCell(
      registerProduct = args.headOption.exists(_.toBoolean))
  }
}

object JamletMxuMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuGenerator.generate(args(0), args.drop(1))
}

object JamletMxuGridMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuGridGenerator.generate(args(0), args.drop(1))
}

object JamletMxuTestGridMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuTestGridGenerator.generate(args(0), args.drop(1))
}

object JamletMxuCellMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuCellGenerator.generate(args(0), args.drop(1))
}
