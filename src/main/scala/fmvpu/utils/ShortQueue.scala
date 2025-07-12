package fmvpu.utils

import chisel3._
import chisel3.util._
import fmvpu.ModuleGenerator

class ShortQueue[T <: Data](t: T) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(DecoupledIO(t))
    val o = DecoupledIO(t)
  })

  val queue = Module(new Queue(t, 2))
  queue.io.enq <> io.i
  queue.io.deq <> io.o
}

object ShortQueueGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ShortQueue <width>")
      null
    } else {
      val width = args(0).toInt
      new ShortQueue(UInt(width.W))
    }
  }
}