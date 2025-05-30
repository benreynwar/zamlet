package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import fmpvu.ModuleGenerator

class AdjustableDelay(maxDelay: Int, width: Int) extends Module {
  val io = IO(new Bundle {
    val delay = Input(UInt(log2Ceil(maxDelay + 1).W))
    val input = Input(Valid(UInt(width.W)))
    val output = Output(Valid(UInt(width.W)))
    val errors = Output(UInt(1.W))
  })

  val regs = Reg(Vec(maxDelay, Valid(UInt(width.W))))

  for (i <- 0 until maxDelay - 1) {
    regs(i) := Mux((io.delay === (i + 1).U) && io.input.valid, io.input, regs(i + 1))
  }
  regs(maxDelay - 1) := Mux(io.delay === maxDelay.U, io.input, 0.U.asTypeOf(Valid(UInt(width.W))))

  io.output := Mux(io.delay === 0.U && io.input.valid, io.input, regs(0))

  io.errors := Mux(io.delay < maxDelay.U, io.input.valid && regs(io.delay(log2Ceil(maxDelay) - 1, 0)).valid, 0.U)
}


object AdjustableDelayGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 2) {
      println("Usage: <command> <outputDir> AdjustableDelay <maxDelay> <width>")
      null
    } else {
      val maxDelay = args(0).toInt
      val width = args(1).toInt
      new AdjustableDelay(maxDelay, width)
    }
  }
}
