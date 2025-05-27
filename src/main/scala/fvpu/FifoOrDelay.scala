package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.DecoupledIO

import fvpu.ModuleGenerator

class FifoOrDelay[T <: Data](t: T, depth: Int) extends Module {
  assert(depth > 0)
  val configValid = IO(Input(Bool()))
  val configIsFifo = IO(Input(Bool()))
  val configDelay = IO(Input(UInt(log2Ceil(depth+1).W)))
  val input = IO(Flipped(DecoupledIO(t)))
  val output = IO(DecoupledIO(t))

  val regs = Reg(Vec(depth, Valid(t)))
  val readAddress = RegInit(0.U(log2Ceil(depth).W))
  val writeAddress = RegInit(0.U(log2Ceil(depth).W))

  val isFifo = RegInit(true.B)
  val empty = RegInit(true.B)
  val full = RegInit(false.B)
  val zeroDelay = RegInit(false.B)
  val count = RegInit(0.U(log2Ceil(depth+1).W))

  input.ready := !full
  when (isFifo) {
    // If we're operating as a FIFO we don't use the valid
    // stored in the memory.  Instead we look at whether it
    // is empty
    output.valid := !empty
    output.bits := regs(readAddress).bits
  }.otherwise {
    // If we're in delay mode, then if the delay is 0 we're
    // just a passthrough otherwise we read from the memory. 
    when (zeroDelay) {
      output.valid := input.valid
      output.bits := input.bits
    }.otherwise {
      output.valid := regs(readAddress).valid
      output.bits := regs(readAddress).bits
    }
  }

  when (configValid) {
    isFifo := configIsFifo
    zeroDelay := false.B
    count := 0.U
    when (configIsFifo) {
      readAddress := 0.U
      writeAddress := 0.U
      empty := true.B
      full := false.B
    }.otherwise {
      // In delay mode the readAddress is configDelay locations before the writeadress. In will
      // take configDelay cycles to reach the writeAddress so that we get the correct delay
      empty := false.B
      full := false.B
      writeAddress := 0.U
      when (configDelay > 0.U) {
        readAddress := (depth.U - configDelay)
      }.otherwise {
        zeroDelay := true.B
        readAddress := 0.U
      }
    }
    for (i <- 0 until depth) {
      regs(i).valid := false.B
    }
  }.otherwise {
    // The addresses always increment in delay mode.
    // In fifo mode they only increment on a read or write which correspond to both
    // valid and ready being high.
    when (!isFifo || (output.valid && output.ready)) {
      when (readAddress === (depth-1).U) {
        readAddress := 0.U
      }.otherwise {
        readAddress := readAddress + 1.U
      }
    }
    when (!isFifo || (input.valid && input.ready)) {
      regs(writeAddress).bits := input.bits
      regs(writeAddress).valid := input.valid
      when (writeAddress === (depth-1).U) {
        writeAddress := 0.U
      }.otherwise {
        writeAddress := writeAddress + 1.U
      }
    }
    // For fifo mode we keep track of the number of elements in the fifo.
    // We register 'empty' and 'full' so that we can use them to set the
    // valid and ready signals.
    val countIncr = (input.valid && input.ready)
    val countDecr = (output.valid && output.ready)
    when (countIncr && countDecr) {
    }.elsewhen (countIncr) {
      count := count + 1.U
      when (count === (depth-1).U) {
        full := true.B
      }
      empty := false.B
    }.elsewhen (countDecr) {
      count := count - 1.U
      when (count === 1.U) {
        empty := true.B
      }
      full := false.B
    }
  }
}


object FifoOrDelay extends ModuleGenerator {

  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 2) {
      println("Usage: <command> <outputDir> FifoOrDelay <width> <depth>");
      return null;
    }
    val width = args(0).toInt
    val depth = args(1).toInt
    return new FifoOrDelay(UInt(width.W), depth)
  }

}
