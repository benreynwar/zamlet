package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.utils.{RegisterWithPipelinedReset, ResetPipeline, ResetPipelineBudget}

class JamletMxuResetGroup extends RawModule {
  val clock = IO(Input(Clock()))
  val resetIn = IO(Input(Bool()))
  val resetOut = IO(Output(Reset()))

  withClock(clock) {
    val groupReset = RegNext(resetIn)
    dontTouch(groupReset)
    resetOut := groupReset
  }
}

class JamletMxuCDrainRegister(
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(1)) extends Module {
  val io = IO(new Bundle {
    val in = Input(Valid(UInt(32.W)))
    val out = Output(Valid(UInt(32.W)))
  })

  resetBudget.consume(1, "JamletMxuCDrainRegister")
  val localReset = ResetPipeline(clock, reset.asBool, 1)
  withReset(localReset) {
    io.out.valid := RegNext(io.in.valid, false.B)
    io.out.bits := RegNext(io.in.bits)
  }
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
    splitCDrain: Boolean = false,
    resetGroupSize: Int = 0,
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(2)) extends Module {
  override val desiredName =
    s"JamletMxu${n}x${n}_EwLoop${if (hasEwLoop) 1 else 0}" +
      s"_NsLoop${if (hasNsLoop) 1 else 0}" +
      s"_CSA${if (useCarrySaveAccumulator) 1 else 0}" +
      s"_BC${if (registerBC) 1 else 0}_DE${if (registerDE) 1 else 0}" +
      s"_BackwardReg${if (registerBackwardOutput) 1 else 0}" +
      s"_SplitDrain${if (splitCDrain) 1 else 0}_ResetGroup$resetGroupSize"
  require(n == 2 || n == 4 || n == 8)
  require(!splitCDrain || n >= 4)
  require(resetGroupSize >= 0)
  require(resetGroupSize == 0 || n % resetGroupSize == 0)
  val io = IO(new JamletMxuIO(n))

  val resetPipeline = ResetPipeline(clock, reset.asBool, 1, resetBudget, "JamletMxu")
  val cellResetBudget = if (resetGroupSize == 0) {
    resetPipeline.childBudget
  } else {
    resetPipeline.childBudget.consume(1, "JamletMxu reset groups")
  }
  val groupResets = if (resetGroupSize == 0) {
    Seq.empty
  } else {
    Seq.tabulate(n / resetGroupSize, n / resetGroupSize) { (groupRow, groupCol) =>
      val resetGroup = Module(new JamletMxuResetGroup)
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

  def controlRegister(in: Bool, name: String): Bool = {
    val register = withReset(resetPipeline.childReset) {
      Module(new RegisterWithPipelinedReset(
        Bool(),
        resetPipeline.childBudget)).suggestName(name)
    }
    register.io.in := in
    register.io.out
  }

  val ewBackwardInput = Wire(Vec(n, UInt(8.W)))
  val nsBackwardInput = Wire(Vec(n, UInt(8.W)))
  val ewUseBackward = controlRegister(io.ewUseBackward, "ewUseBackward")
  val nsUseBackward = controlRegister(io.nsUseBackward, "nsUseBackward")
  val ewUseBackwardMux = Seq.tabulate(n) { row =>
    controlRegister(ewUseBackward, s"ewUseBackwardMux_$row")
  }
  val nsUseBackwardMux = Seq.tabulate(n) { col =>
    controlRegister(nsUseBackward, s"nsUseBackwardMux_$col")
  }
  var previousInit: Bool = io.init
  val init = Seq.tabulate(n) { lane =>
    previousInit = controlRegister(previousInit, s"init_$lane")
    previousInit
  }
  var previousStepIn: Bool = io.stepIn
  val stepIn = Seq.tabulate(n) { lane =>
    previousStepIn = controlRegister(previousStepIn, s"stepIn_$lane")
    previousStepIn
  }
  var previousCompleteIn: Bool = io.completeIn
  val completeIn = Seq.tabulate(n) { lane =>
    previousCompleteIn = controlRegister(previousCompleteIn, s"completeIn_$lane")
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

  val cells = Seq.tabulate(n, n) { (row, col) =>
    withReset(resetFor(row, col)) {
      Module(new JamletMxuCell(
        useCarrySaveAccumulator = useCarrySaveAccumulator,
        registerBC = registerBC,
        registerDE = registerDE,
        resetBudget = cellResetBudget))
    }
  }

  val middleCDrain = if (splitCDrain) {
    Seq.tabulate(n) { row =>
      val middleCDrainRegister = withReset(resetFor(row, n / 2)) {
        Module(new JamletMxuCDrainRegister(cellResetBudget))
      }
      middleCDrainRegister.io.in.valid := cells(row)(n / 2).io.eCDrainOut.valid
      middleCDrainRegister.io.in.bits := cells(row)(n / 2).io.eCDrainOut.bits.data
      middleCDrainRegister.io.out
    }
  } else {
    Seq.empty
  }

  for (row <- 0 until n) {
    for (col <- 0 until n) {
      val cell = cells(row)(col)
      cell.io.aA := (if (col == 0) ewSelectedInput(row) else cells(row)(col - 1).io.bA)
      cell.io.aB := (if (row == 0) nsSelectedInput(col) else cells(row - 1)(col).io.bB)
      cell.io.aValid := (if (col == 0) stepIn(row) else cells(row)(col - 1).io.bValid)
      cell.io.aFinal := (if (col == 0) completeIn(row) else cells(row)(col - 1).io.bFinal)
      val startsCDrain = col == n - 1 || (splitCDrain && col == 0)
      if (startsCDrain) {
        cell.io.eCDrainIn.valid := false.B
        cell.io.eCDrainIn.bits.data := 0.U
        cell.io.eCDrainIn.bits.fromFar := false.B
      } else if (splitCDrain && col == n / 2 - 1) {
        cell.io.eCDrainIn.valid := middleCDrain(row).valid
        cell.io.eCDrainIn.bits.data := middleCDrain(row).bits
        cell.io.eCDrainIn.bits.fromFar := true.B
      } else {
        cell.io.eCDrainIn := cells(row)(col + 1).io.eCDrainOut
      }
    }

    io.ewForwardOutput(row) := cells(row)(n - 1).io.bA
    io.ewBackwardOutput(row) := ewBackwardInput(row)
    if (splitCDrain) {
      val westCDrain = cells(row)(0).io.eCDrainOut
      val secondWestCDrain = cells(row)(1).io.eCDrainOut
      val nearCDrainValid = secondWestCDrain.valid && !secondWestCDrain.bits.fromFar
      val farCDrainValid = secondWestCDrain.valid && secondWestCDrain.bits.fromFar

      assert(!(westCDrain.valid && nearCDrainValid))
      val nearCDrainRegister = withReset(resetFor(row, 0)) {
        Module(new JamletMxuCDrainRegister(cellResetBudget))
      }
      nearCDrainRegister.io.in.valid := westCDrain.valid || nearCDrainValid
      nearCDrainRegister.io.in.bits := Mux(
        nearCDrainValid,
        secondWestCDrain.bits.data,
        westCDrain.bits.data)

      assert(!(nearCDrainRegister.io.out.valid && farCDrainValid))
      val cToMemoryRegister = withReset(resetFor(row, 0)) {
        Module(new JamletMxuCDrainRegister(cellResetBudget))
      }
      cToMemoryRegister.io.in.valid := nearCDrainRegister.io.out.valid || farCDrainValid
      cToMemoryRegister.io.in.bits := Mux(
        farCDrainValid,
        secondWestCDrain.bits.data,
        nearCDrainRegister.io.out.bits)
      io.cToMemory(row) := cToMemoryRegister.io.out.bits
      io.cToMemoryValid(row) := cToMemoryRegister.io.out.valid
    } else {
      val cToMemoryRegister = withReset(resetFor(row, 0)) {
        Module(new JamletMxuCDrainRegister(cellResetBudget))
      }
      cToMemoryRegister.io.in.valid := cells(row)(0).io.eCDrainOut.valid
      cToMemoryRegister.io.in.bits := cells(row)(0).io.eCDrainOut.bits.data
      io.cToMemory(row) := cToMemoryRegister.io.out.bits
      io.cToMemoryValid(row) := cToMemoryRegister.io.out.valid
    }
  }

  for (col <- 0 until n) {
    io.nsForwardOutput(col) := cells(n - 1)(col).io.bB
    io.nsBackwardOutput(col) := nsBackwardInput(col)
  }

  io.error := controlRegister(
    cells.flatten.map(_.io.error).reduce(_ || _),
    "error")
}

object JamletMxuGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val resetGroupSize = args.drop(8).headOption.map(_.toInt).getOrElse(0)
    new JamletMxu(
      n = args.headOption.map(_.toInt).getOrElse(8),
      hasEwLoop = args.drop(1).headOption.forall(_.toBoolean),
      hasNsLoop = args.drop(2).headOption.forall(_.toBoolean),
      useCarrySaveAccumulator = args.drop(3).headOption.exists(_.toBoolean),
      registerBC = args.drop(4).headOption.exists(_.toBoolean),
      registerDE = args.drop(5).headOption.exists(_.toBoolean),
      registerBackwardOutput = args.drop(6).headOption.exists(_.toBoolean),
      splitCDrain = args.drop(7).headOption.exists(_.toBoolean),
      resetGroupSize = resetGroupSize,
      resetBudget = ResetPipelineBudget(if (resetGroupSize == 0) 2 else 3))
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
