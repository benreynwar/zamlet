package zamlet.utils

import chisel3._
import chisel3.util._
import zamlet.ModuleGenerator

class DoubleBuffer[T <: Data](t: T, enableForward: Boolean = true, enableBackward: Boolean = true) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(DecoupledIO(t))
    val o = DecoupledIO(t)
    val fromState = Output(Bool())
    val hidden = Output(Valid(t))
  })

  val skidBuffer = Module(new SkidBuffer(t, enableBackward))
  val decoupledBuffer = Module(new DecoupledBuffer(t, enableForward))

  skidBuffer.io.i <> io.i
  decoupledBuffer.io.i <> skidBuffer.io.o
  io.o <> decoupledBuffer.io.o

  // True when io.o is driven from internal buffer state instead of directly
  // from io.i. Clients use this to avoid counting passthrough data as older
  // work in resource conflict checks.
  if (enableForward) {
    io.fromState := decoupledBuffer.io.o.valid
  } else if (enableBackward) {
    io.fromState := !skidBuffer.io.i.ready && skidBuffer.io.o.valid
  } else {
    io.fromState := false.B
  }

  // Hidden is the backward/skid entry parked behind a visible forward-buffer
  // entry. It is not part of io.o, but it is older than new input and must be
  // included by clients that do resource conflict checks across buffered work.
  if (enableForward && enableBackward) {
    io.hidden.valid := !skidBuffer.io.i.ready && decoupledBuffer.io.o.valid
    io.hidden.bits := skidBuffer.io.o.bits
  } else {
    io.hidden.valid := false.B
    io.hidden.bits := DontCare
  }

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

object DoubleBufferMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <width>")
    System.exit(1)
  }
  DoubleBufferGenerator.generate(args(0), Seq(args(1)))
}
