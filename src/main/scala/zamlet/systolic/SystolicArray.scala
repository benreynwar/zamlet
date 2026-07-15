package zamlet.systolic

import chisel3._
import chisel3.util._

class SystolicCellIO extends Bundle {
  val inputIn = Input(UInt(8.W))
  val inputOut = Output(UInt(8.W))

  val weightLoadIn = Input(UInt(8.W))
  val weightLoadOut = Output(UInt(8.W))

  val sumIn = Input(UInt(32.W))
  val sumOut = Output(UInt(32.W))

  val loadWeightIn = Input(Bool())
  val loadWeightOut = Output(Bool())

  val startIn = Input(Bool())
  val startOut = Output(Bool())

  val stepIn = Input(Bool())
  val stepOut = Output(Bool())
}

class SystolicCell extends Module {
  val io = IO(new SystolicCellIO)

  val bInput = RegEnable(io.inputIn, io.stepIn)
  val bStart = RegNext(io.startIn, false.B)
  val bStep = RegNext(io.stepIn, false.B)

  val bWeightShadow = RegEnable(io.weightLoadIn, io.loadWeightIn)
  val bLoadWeight = RegNext(io.loadWeightIn, false.B)
  val bWeight = RegEnable(bWeightShadow, bStart)

  val bSum = RegEnable(io.sumIn, bStep)
  val bProduct = (bInput.asSInt * bWeight.asSInt).asUInt

  val cStep = RegNext(bStep, false.B)
  val cSum = RegEnable(bSum, bStep)
  val cProduct = RegEnable(Cat(Fill(16, bProduct(15)), bProduct), bStep)

  io.inputOut := bInput
  io.weightLoadOut := bWeightShadow
  io.sumOut := Mux(cStep, (cSum + cProduct)(31, 0), cSum)

  io.loadWeightOut := bLoadWeight
  io.startOut := bStart
  io.stepOut := bStep
}

class SystolicArrayIO(n: Int) extends Bundle {
  val inputIn = Input(Vec(n, UInt(8.W)))
  val weightLoadIn = Input(Vec(n, UInt(8.W)))
  val sumIn = Input(Vec(n, UInt(32.W)))

  val loadWeightIn = Input(Vec(n, Bool()))
  val startIn = Input(Vec(n, Bool()))
  val stepIn = Input(Vec(n, Bool()))

  val inputOut = Output(Vec(n, UInt(8.W)))
  val weightLoadOut = Output(Vec(n, UInt(8.W)))
  val sumOut = Output(Vec(n, UInt(32.W)))

  val loadWeightOut = Output(Vec(n, Bool()))
  val startOut = Output(Vec(n, Bool()))
  val stepOut = Output(Vec(n, Bool()))
}

class SystolicArray(n: Int = 8) extends Module {
  require(n > 0)
  val io = IO(new SystolicArrayIO(n))

  val cells = Seq.tabulate(n, n) { (_, _) => Module(new SystolicCell) }

  for (row <- 0 until n) {
    for (col <- 0 until n) {
      val cell = cells(row)(col)

      cell.io.inputIn := (if (col == 0) io.inputIn(row) else cells(row)(col - 1).io.inputOut)
      cell.io.startIn := (if (col == 0) io.startIn(row) else cells(row)(col - 1).io.startOut)
      cell.io.stepIn := (if (col == 0) io.stepIn(row) else cells(row)(col - 1).io.stepOut)

      cell.io.weightLoadIn := (if (row == 0) io.weightLoadIn(col) else cells(row - 1)(col).io.weightLoadOut)
      cell.io.loadWeightIn := (if (row == 0) io.loadWeightIn(col) else cells(row - 1)(col).io.loadWeightOut)

      cell.io.sumIn := (if (row == 0) io.sumIn(col) else cells(row - 1)(col).io.sumOut)
    }
  }

  for (row <- 0 until n) {
    io.inputOut(row) := cells(row)(n - 1).io.inputOut
    io.startOut(row) := cells(row)(n - 1).io.startOut
    io.stepOut(row) := cells(row)(n - 1).io.stepOut
  }

  for (col <- 0 until n) {
    io.weightLoadOut(col) := cells(n - 1)(col).io.weightLoadOut
    io.loadWeightOut(col) := cells(n - 1)(col).io.loadWeightOut
    io.sumOut(col) := cells(n - 1)(col).io.sumOut
  }
}

object SystolicArrayGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    new SystolicArray(
      n = args.headOption.map(_.toInt).getOrElse(8))
  }
}

object SystolicArrayMain extends App {
  if (args.length < 1) {
    println("Usage: <outputDir>")
    System.exit(1)
  }
  SystolicArrayGenerator.generate(args(0), args.drop(1))
}
