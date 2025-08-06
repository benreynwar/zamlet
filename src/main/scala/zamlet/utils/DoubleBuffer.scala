package zamlet.utils

import chisel3._
import chisel3.util._
import zamlet.ModuleGenerator

class DoubleBuffer[T <: Data](t: T) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(DecoupledIO(t))
    val o = DecoupledIO(t)
  })

  val skidBuffer = Module(new SkidBuffer(t))
  val decoupledBuffer = Module(new DecoupledBuffer(t))

  skidBuffer.io.i <> io.i
  decoupledBuffer.io.i <> skidBuffer.io.o
  io.o <> decoupledBuffer.io.o
}

object DoubleBufferGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> DoubleBuffer <width>")
      null
    } else {
      val width = args(0).toInt
      new DoubleBuffer(UInt(width.W))
    }
  }
}
