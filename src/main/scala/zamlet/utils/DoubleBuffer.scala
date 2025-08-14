package zamlet.utils

import chisel3._
import chisel3.util._
import zamlet.ModuleGenerator

class DoubleBuffer[T <: Data](t: T, enableForward: Boolean = true, enableBackward: Boolean = true) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(DecoupledIO(t))
    val o = DecoupledIO(t)
  })

  val skidBuffer = Module(new SkidBuffer(t, enableBackward))
  val decoupledBuffer = Module(new DecoupledBuffer(t, enableForward))

  skidBuffer.io.i <> io.i
  decoupledBuffer.io.i <> skidBuffer.io.o
  io.o <> decoupledBuffer.io.o
}

object DoubleBuffer {
  def apply[T <: Data](input: DecoupledIO[T], enableForward: Boolean, enableBackward: Boolean): DecoupledIO[T] = {
    val buffer = Module(new DoubleBuffer(input.bits.cloneType, enableForward, enableBackward))
    buffer.io.i <> input
    buffer.io.o
  }
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
