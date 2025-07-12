package fmvpu.utils

import chisel3._
import chisel3.util._
import fmvpu.ModuleGenerator

class Fifo[T <: Data](t: T, depth: Int) extends Module {
  val io = IO(new Bundle {
    val enq = Flipped(DecoupledIO(t))
    val deq = DecoupledIO(t)
    val count = Output(UInt(log2Ceil(depth + 1).W))
  })

  val queue = Module(new Queue(t, depth))
  queue.io <> io
}

object FifoGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 2) {
      println("Usage: <command> <outputDir> Fifo <width> <depth>")
      null
    } else {
      val width = args(0).toInt
      val depth = args(1).toInt
      new Fifo(UInt(width.W), depth)
    }
  }
}