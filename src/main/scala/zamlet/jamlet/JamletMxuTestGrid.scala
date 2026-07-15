package zamlet.jamlet

import chisel3._
import chisel3.util._

class JamletMxuTestGridIO(gridRows: Int, gridCols: Int, mxuN: Int) extends Bundle {
  val ewFromMemory = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(8.W)))))
  val ewLoop = Input(Vec(gridCols, Bool()))
  val aEastOut = Output(Vec(gridRows, Vec(mxuN, UInt(8.W))))

  val nsFromMemory = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(8.W)))))
  val nsLoop = Input(Vec(gridRows, Bool()))
  val bSouthOut = Output(Vec(gridCols, Vec(mxuN, UInt(8.W))))

  val stepIn = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, Bool()))))
  val completeIn = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, Bool()))))
  val init = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, Bool()))))

  val cToMemory = Output(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(16.W)))))
  val cToMemoryValid = Output(Vec(gridRows, Vec(gridCols, Vec(mxuN, Bool()))))

  val error = Output(Bool())
}

class JamletMxuTestGrid(
    gridRows: Int = 2,
    gridCols: Int = 2,
    mxuN: Int = 4,
    bcBuffer: Boolean = false) extends Module {
  require(gridRows > 0 && isPow2(gridRows))
  require(gridCols > 0 && isPow2(gridCols))
  require(gridRows % 2 == 0)
  require(gridCols % 2 == 0)
  val io = IO(new JamletMxuTestGridIO(gridRows, gridCols, mxuN))

  val blocks = Seq.tabulate(gridRows, gridCols) { (_, _) =>
    Module(new JamletMxu(
      n = mxuN,
      hasEwLoop = true,
      hasNsLoop = true,
      bcBuffer = bcBuffer))
  }

  for (physicalRow <- 0 until gridRows) {
    for (physicalCol <- 0 until gridCols) {
      val block = blocks(physicalRow)(physicalCol)

      block.io.ewLoop := io.ewLoop(physicalCol)
      block.io.nsLoop := io.nsLoop(physicalRow)

      for (row <- 0 until mxuN) {
        block.io.ewFromMemory(row) := io.ewFromMemory(physicalRow)(physicalCol)(row)
        block.io.init(row) := io.init(physicalRow)(physicalCol)(row)
        block.io.stepIn(row) := io.stepIn(physicalRow)(physicalCol)(row)
        block.io.completeIn(row) := io.completeIn(physicalRow)(physicalCol)(row)
        io.cToMemory(physicalRow)(physicalCol)(row) := block.io.cToMemory(row)
        io.cToMemoryValid(physicalRow)(physicalCol)(row) := block.io.cToMemoryValid(row)
      }

      for (col <- 0 until mxuN) {
        block.io.nsFromMemory(col) := io.nsFromMemory(physicalRow)(physicalCol)(col)
      }
    }
  }

  for (physicalRow <- 0 until gridRows by 2) {
    for (physicalCol <- 0 until gridCols by 2) {
      val nw = blocks(physicalRow)(physicalCol)
      val ne = blocks(physicalRow)(physicalCol + 1)
      val sw = blocks(physicalRow + 1)(physicalCol)
      val se = blocks(physicalRow + 1)(physicalCol + 1)

      for (row <- 0 until mxuN) {
        nw.io.ewLoopInput(row) := ne.io.ewOutput(row)
        nw.io.ewInput(row) := (if (physicalCol == 0) 0.U else blocks(physicalRow)(physicalCol - 1).io.ewOutput(row))
        ne.io.ewLoopInput(row) := nw.io.ewOutput(row)
        ne.io.ewInput(row) := (if (physicalCol + 2 == gridCols) 0.U else blocks(physicalRow)(physicalCol + 2).io.ewOutput(row))
        sw.io.ewLoopInput(row) := se.io.ewOutput(row)
        sw.io.ewInput(row) := (if (physicalCol == 0) 0.U else blocks(physicalRow + 1)(physicalCol - 1).io.ewOutput(row))
        se.io.ewLoopInput(row) := sw.io.ewOutput(row)
        se.io.ewInput(row) := (if (physicalCol + 2 == gridCols) 0.U else blocks(physicalRow + 1)(physicalCol + 2).io.ewOutput(row))
      }

      for (col <- 0 until mxuN) {
        nw.io.nsLoopInput(col) := sw.io.nsOutput(col)
        nw.io.nsInput(col) := (if (physicalRow == 0) 0.U else blocks(physicalRow - 1)(physicalCol).io.nsOutput(col))
        sw.io.nsLoopInput(col) := nw.io.nsOutput(col)
        sw.io.nsInput(col) := (if (physicalRow + 2 == gridRows) 0.U else blocks(physicalRow + 2)(physicalCol).io.nsOutput(col))
        ne.io.nsLoopInput(col) := se.io.nsOutput(col)
        ne.io.nsInput(col) := (if (physicalRow == 0) 0.U else blocks(physicalRow - 1)(physicalCol + 1).io.nsOutput(col))
        se.io.nsLoopInput(col) := ne.io.nsOutput(col)
        se.io.nsInput(col) := (if (physicalRow + 2 == gridRows) 0.U else blocks(physicalRow + 2)(physicalCol + 1).io.nsOutput(col))
      }
    }
  }

  for (physicalRow <- 0 until gridRows) {
    for (row <- 0 until mxuN) {
      io.aEastOut(physicalRow)(row) := blocks(physicalRow)(gridCols - 1).io.ewOutput(row)
    }
  }

  for (physicalCol <- 0 until gridCols) {
    for (col <- 0 until mxuN) {
      io.bSouthOut(physicalCol)(col) := blocks(gridRows - 1)(physicalCol).io.nsOutput(col)
    }
  }

  io.error := blocks.flatten.map(_.io.error).reduce(_ || _)
}

object JamletMxuTestGridGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new JamletMxuTestGrid(
      gridRows = args.headOption.map(_.toInt).getOrElse(2),
      gridCols = args.drop(1).headOption.map(_.toInt).getOrElse(2),
      mxuN = args.drop(2).headOption.map(_.toInt).getOrElse(4),
      bcBuffer = args.drop(3).headOption.exists(_.toBoolean))
  }
}

object JamletMxuTestGridMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuTestGridGenerator.generate(args(0), args.drop(1))
}
