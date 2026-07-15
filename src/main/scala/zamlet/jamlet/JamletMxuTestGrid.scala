package zamlet.jamlet

import chisel3._
import chisel3.util._

class JamletMxuTestGridIO(gridRows: Int, gridCols: Int, mxuN: Int) extends Bundle {
  val ewFromMemory = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(8.W)))))
  val ewUseBackward = Input(Vec(gridCols, Bool()))
  val aEastOut = Output(Vec(gridRows, Vec(mxuN, UInt(8.W))))

  val nsFromMemory = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(8.W)))))
  val nsUseBackward = Input(Vec(gridRows, Bool()))
  val bSouthOut = Output(Vec(gridCols, Vec(mxuN, UInt(8.W))))

  val stepIn = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, Bool()))))
  val completeIn = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, Bool()))))
  val init = Input(Vec(gridRows, Vec(gridCols, Vec(mxuN, Bool()))))

  val cToMemory = Output(Vec(gridRows, Vec(gridCols, Vec(mxuN, UInt(16.W)))))
  val cToMemoryValid = Output(Vec(gridRows, Vec(gridCols, Vec(mxuN, Bool()))))

  val error = Output(Bool())
}

class JamletMxuTestGrid(
    gridRows: Int,
    gridCols: Int,
    mxuN: Int,
    bcBuffer: Boolean,
    moduleName: String) extends Module {
  override val desiredName = moduleName
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

      block.io.ewUseBackward := io.ewUseBackward(physicalCol)
      block.io.nsUseBackward := io.nsUseBackward(physicalRow)

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
        nw.io.ewBackwardInput(row) := ne.io.ewForwardOutput(row)
        ne.io.ewBackwardInput(row) := nw.io.ewForwardOutput(row)
        nw.io.ewForwardInput(row) := (if (physicalCol == 0) 0.U else blocks(physicalRow)(physicalCol - 1).io.ewBackwardOutput(row))
        ne.io.ewForwardInput(row) := (if (physicalCol + 2 == gridCols) 0.U else blocks(physicalRow)(physicalCol + 2).io.ewBackwardOutput(row))

        sw.io.ewBackwardInput(row) := se.io.ewForwardOutput(row)
        se.io.ewBackwardInput(row) := sw.io.ewForwardOutput(row)
        sw.io.ewForwardInput(row) := (if (physicalCol == 0) 0.U else blocks(physicalRow + 1)(physicalCol - 1).io.ewBackwardOutput(row))
        se.io.ewForwardInput(row) := (if (physicalCol + 2 == gridCols) 0.U else blocks(physicalRow + 1)(physicalCol + 2).io.ewBackwardOutput(row))
      }

      for (col <- 0 until mxuN) {
        nw.io.nsBackwardInput(col) := sw.io.nsForwardOutput(col)
        sw.io.nsBackwardInput(col) := nw.io.nsForwardOutput(col)
        nw.io.nsForwardInput(col) := (if (physicalRow == 0) 0.U else blocks(physicalRow - 1)(physicalCol).io.nsBackwardOutput(col))
        sw.io.nsForwardInput(col) := (if (physicalRow + 2 == gridRows) 0.U else blocks(physicalRow + 2)(physicalCol).io.nsBackwardOutput(col))

        ne.io.nsBackwardInput(col) := se.io.nsForwardOutput(col)
        se.io.nsBackwardInput(col) := ne.io.nsForwardOutput(col)
        ne.io.nsForwardInput(col) := (if (physicalRow == 0) 0.U else blocks(physicalRow - 1)(physicalCol + 1).io.nsBackwardOutput(col))
        se.io.nsForwardInput(col) := (if (physicalRow + 2 == gridRows) 0.U else blocks(physicalRow + 2)(physicalCol + 1).io.nsBackwardOutput(col))
      }
    }
  }

  for (physicalRow <- 0 until gridRows) {
    for (row <- 0 until mxuN) {
      io.aEastOut(physicalRow)(row) := blocks(physicalRow)(gridCols - 1).io.ewForwardOutput(row)
    }
  }

  for (physicalCol <- 0 until gridCols) {
    for (col <- 0 until mxuN) {
      io.bSouthOut(physicalCol)(col) := blocks(gridRows - 1)(physicalCol).io.nsForwardOutput(col)
    }
  }

  io.error := blocks.flatten.map(_.io.error).reduce(_ || _)
}

object JamletMxuTestGridGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    require(args.length == 5)
    new JamletMxuTestGrid(
      gridRows = args(0).toInt,
      gridCols = args(1).toInt,
      mxuN = args(2).toInt,
      bcBuffer = args(3).toBoolean,
      moduleName = args(4))
  }
}

object JamletMxuTestGridMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  JamletMxuTestGridGenerator.generate(args(0), args.drop(1))
}
